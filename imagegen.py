"""
ComfyUI image generation module.
Provides a REST endpoint and helper functions for generating scene images
via a ComfyUI instance.

ComfyUI API flow:
  1. POST /prompt  →  {prompt_id, number}
  2. Poll GET /history/{prompt_id}  →  outputs with image filenames
  3. GET /view?filename=...&subfolder=...&type=output  →  image bytes
"""
import asyncio
import json
import re
import time
import uuid
from pathlib import Path

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI

import db
import engine
from engine import _now_iso

router = APIRouter()

POLL_INTERVAL = 1.0  # seconds between history polls
MAX_POLL_TIME = 120   # max seconds to wait for generation


def _resolve_seed(override: int | None = None) -> int:
    """Return the seed to use for this generation — explicit override, fixed, or random."""
    if override is not None:
        return override
    if db.IMAGEGEN_RANDOM_SEED:
        return __import__('random').randint(0, 2**32 - 1)
    return db.IMAGEGEN_SEED


def _default_workflow(prompt_text: str, negative: str = "", seed: int | None = None, width: int | None = None, height: int | None = None) -> dict:
    """Build a minimal txt2img ComfyUI workflow (API format, node IDs as string keys)."""
    s = _resolve_seed(seed)
    w = width if width is not None else db.IMAGEGEN_WIDTH
    h = height if height is not None else db.IMAGEGEN_HEIGHT
    return {
        "3": {
            "class_type": "KSampler",
            "inputs": {
                "seed": s,
                "steps": db.IMAGEGEN_STEPS,
                "cfg": db.IMAGEGEN_CFG_SCALE,
                "sampler_name": db.IMAGEGEN_SAMPLER,
                "scheduler": db.IMAGEGEN_SCHEDULER,
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0],
            },
        },
        "4": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"},
        },
        "5": {
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": w,
                "height": h,
                "batch_size": 1,
            },
        },
        "6": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": prompt_text, "clip": ["4", 1]},
        },
        "7": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative or "bad quality, low resolution, blurry", "clip": ["4", 1]},
        },
        "8": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["3", 0], "vae": ["4", 2]},
        },
        "9": {
            "class_type": "SaveImage",
            "inputs": {"images": ["8", 0], "filename_prefix": "cs_scene"},
        },
    }


async def _poll_history(base_url: str, prompt_id: str, timeout: float = MAX_POLL_TIME) -> dict:
    """Poll ComfyUI /history/{prompt_id} until the result is ready."""
    start = time.time()
    async with httpx.AsyncClient(timeout=30) as client:
        while time.time() - start < timeout:
            try:
                resp = await client.get(f"{base_url}/history/{prompt_id}")
                if resp.status_code == 200:
                    data = resp.json()
                    if prompt_id in data:
                        return data[prompt_id]
            except (httpx.RequestError, json.JSONDecodeError):
                pass
            await asyncio.sleep(POLL_INTERVAL)
    raise TimeoutError(f"ComfyUI generation timed out after {timeout}s (prompt_id={prompt_id})")


def _extract_output_filename(history_entry: dict):
    """Extract the first output image filename + subfolder from a history entry."""
    outputs = history_entry.get("outputs", {})
    for node_id, node_output in outputs.items():
        images = node_output.get("images", [])
        if images:
            img = images[0]
            return img.get("filename"), img.get("subfolder", ""), img.get("type", "output")
    return None, None, None


async def generate_image(prompt_text: str, negative_prompt: str = "", seed: int | None = None, width: int | None = None, height: int | None = None) -> dict:
    """
    Call ComfyUI to generate an image from a text prompt.
    Returns dict with:
      - success: bool
      - image_path: str (relative filename in UPLOAD_DIR) on success
      - seed: int (the seed actually used)
      - error: str on failure
    """
    base_url = db.IMAGEGEN_BASE_URL.rstrip("/")
    if not db.IMAGEGEN_ENABLED:
        return {"success": False, "error": "Image generation is disabled. Enable it in Settings → Image Generation."}

    # Build workflow (custom or default)
    seed_val = _resolve_seed(seed)
    if db.IMAGEGEN_WORKFLOW and isinstance(db.IMAGEGEN_WORKFLOW, dict):
        # Inject prompt/negative via %positive% / %negative% placeholders.
        # Serialize → replace → parse so placeholders can appear anywhere in the workflow.
        neg_text = negative_prompt or db.IMAGEGEN_NEGATIVE or "bad quality, low resolution, blurry"
        # String placeholders: replaced as escaped JSON strings
        string_replacements = {
            "%positive%": prompt_text,
            "%negative%": neg_text,
        }
        # Numeric placeholders: must be injected as raw JSON numbers, not quoted strings.
        # We do this by replacing the quoted placeholder " %placeholder% " with the raw number.
        numeric_replacements = {
            "%width%": width if width is not None else db.IMAGEGEN_WIDTH,
            "%height%": height if height is not None else db.IMAGEGEN_HEIGHT,
            "%steps%": db.IMAGEGEN_STEPS,
            "%cfg%": db.IMAGEGEN_CFG_SCALE,
            "%seed%": seed_val,
        }
        workflow_json = json.dumps(db.IMAGEGEN_WORKFLOW)
        # String replacements (escape for JSON)
        for placeholder, value in string_replacements.items():
            workflow_json = workflow_json.replace(placeholder, value.replace("\\", "\\\\").replace('"', '\\"'))
        # Numeric replacements: replace quoted "%placeholder%" with raw number (unquoted)
        for placeholder, value in numeric_replacements.items():
            workflow_json = workflow_json.replace(f'"{placeholder}"', str(value))
            # Also replace bare %placeholder% for inline use in text strings
            workflow_json = workflow_json.replace(placeholder, str(value))
        workflow = json.loads(workflow_json)
    else:
        workflow = _default_workflow(prompt_text, negative_prompt or db.IMAGEGEN_NEGATIVE, seed=seed, width=width, height=height)

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 1. Queue the prompt
            resp = await client.post(
                f"{base_url}/prompt",
                json={"prompt": workflow, "client_id": str(uuid.uuid4())},
            )
            if resp.status_code != 200:
                return {"success": False, "error": f"ComfyUI /prompt returned {resp.status_code}: {resp.text[:200]}"}
            result = resp.json()
            prompt_id = result.get("prompt_id")
            if not prompt_id:
                return {"success": False, "error": f"ComfyUI did not return prompt_id: {result}"}

        # 2. Poll for completion
        history_entry = await _poll_history(base_url, prompt_id)

        # 3. Extract image info
        filename, subfolder, img_type = _extract_output_filename(history_entry)
        if not filename:
            return {"success": False, "error": "No image output found in ComfyUI history"}

        # 4. Download the image
        async with httpx.AsyncClient(timeout=60) as client:
            params = {"filename": filename}
            if subfolder:
                params["subfolder"] = subfolder
            if img_type:
                params["type"] = img_type
            img_resp = await client.get(f"{base_url}/view", params=params)
            if img_resp.status_code != 200:
                return {"success": False, "error": f"Failed to download image: {img_resp.status_code}"}

            # 5. Save to UPLOAD_DIR with a unique name
            ext = Path(filename).suffix or ".png"
            safe_name = f"gen_{int(time.time())}_{uuid.uuid4().hex[:8]}{ext}"
            save_path = db.UPLOAD_DIR / safe_name
            save_path.write_bytes(img_resp.content)

            # Save sidecar metadata JSON
            meta = {
                "prompt": prompt_text,
                "seed": seed_val,
                "negative_prompt": negative_prompt or "",
                "width": width if width is not None else db.IMAGEGEN_WIDTH,
                "height": height if height is not None else db.IMAGEGEN_HEIGHT,
                "timestamp": time.time(),
            }
            meta_path = db.UPLOAD_DIR / (safe_name + ".json")
            meta_path.write_text(json.dumps(meta, ensure_ascii=False))

        return {"success": True, "image_path": safe_name, "prompt": prompt_text, "seed": seed_val}

    except TimeoutError as e:
        return {"success": False, "error": str(e)}
    except httpx.RequestError as e:
        return {"success": False, "error": f"Cannot connect to ComfyUI at {base_url}: {e}"}
    except Exception as e:
        return {"success": False, "error": f"Unexpected error: {e}"}


# ─── Auto image prompt generation (Phase 3) ────────────────────────

AUTO_IMG_SYSTEM = """You are the scene captioner for a roleplay chat app feeding an image generation model trained on captions of FINISHED IMAGES, not instructions, and built for long descriptive prompts.

Read the conversation and character context, then answer with one of two things:
- SKIP — the exchange is mundane (greetings, short talk, no visual change, OOC chatter).
- ONE English prose caption of the finished frame.

Writing the caption:
1. Faithfulness. Subject, action and count come from the chat (clothing per 4). Never contradict the chat; invent no props, characters or plot.
2. Location, in precedence: what the chat states; if the chat only implies it, make the implication explicit; if the chat is silent, the location from the character's scenario; if that is silent too, stay generic ("a simple interior"). Never invent specifics you were not given.
3. Visuals only — what a camera would see. No dialogue, speech, sounds, thoughts or backstory: spoken lines are never rendered as text. Visible writing the chat mentions (a sign, a note) is quoted verbatim in double quotes with its placement.
4. Identity comes from the character context below (face, hair, body). Clothing precedence: the chat's outfit for THIS scene wins; when the chat is silent about clothing, their usual outfit from the card ("usual look"); if none is known, generic. The chat beats the card — never the card's default outfit over it (naked stays naked).
5. Structure: subject first with its action and position; then setting with word positions (left, right, foreground, background); then camera, medium, light, materials, palette, mood. One subject per clause, concrete verbs, simple prepositions. Plain prose — no lists, markdown, or quality words ("masterpiece, 8k" banned).
6. Camera: keep any vantage the chat states (POV, first-person, over-the-shoulder, low angle, "seen from behind") and compose around it; otherwise eye level. Never re-frame mid-caption.
7. Style budget: use each given phrase exactly once — one medium, one lighting, one mood. If none is given, choose fitting ones yourself.
8. Depict the scene as the chat shows it: nudity, partial nudity and sexual content are described plainly when that is what is happening — never softened, implied, or re-clothed. Sexualized minors are refused with one short refusal line and no caption.
9. No living artists — translate a named artist into observable traits instead.
10. Output: one paragraph, target {words} words — approach the {tokens}-token ceiling, never over it. Reply with the caption alone — or the single word SKIP. No preamble, no wrapping quotes, no explanation."""


# Selectable output ceilings (the Scene gen panel's token select).
TOKEN_CAPS = (512, 1024, 2048, 4096)


def auto_img_system(word_target=None, token_cap=None) -> str:
    """The captioner's system prompt; {words} from config, {tokens} the
    selectable output ceiling (default 512; unknown values fall back).

    Above 512 the selection is a LENGTH choice, not just a cap — the
    word target scales with it (~1.33 tokens/word leaves headroom under
    the ceiling). An explicit word_target stays authoritative."""
    try:
        token_cap = int(token_cap)
    except (TypeError, ValueError):
        token_cap = 512
    if token_cap not in TOKEN_CAPS:
        token_cap = 512
    if word_target is None:
        word_target = db.IMAGEGEN_CAPTION_WORDS
        if token_cap > 512:
            word_target = max(word_target, round(token_cap * 0.6))
    return AUTO_IMG_SYSTEM.replace("{words}", str(word_target)).replace("{tokens}", str(token_cap))


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "\u2026"


def _habit_from_card(card: dict, d: dict) -> str:
    """The character's usual look/presentation, flattened to one line.

    Lives in the card's character book (V2 top-level or V3 nested) and the
    example dialogue — the description alone misses "what she usually
    wears". Budgeted so a fat book cannot flood the captioner.
    """
    parts = []
    book = card.get("character_book") or d.get("character_book") or {}
    used = 0
    for e in (book.get("entries") or []):
        if not e.get("enabled", True):
            continue
        content = " ".join(str(e.get("content") or "").split())
        content = _clip(content, 250)
        if not content:
            continue
        if used + len(content) > 1200:
            break
        parts.append(content)
        used += len(content)
    mes = " ".join(str(d.get("mes_example") or "").split())
    mes = _clip(mes, 400)
    if mes:
        parts.append(mes)
    return " ".join(parts)


def caption_session_context(session_id) -> tuple:
    """(characters_block, persona_block) for the captioner, from the session.

    Characters carry the card's description (appearance) and scenario —
    the scenario is background knowledge; the chat overrides it when the
    story has moved on.
    """
    characters_block, persona_block = "", ""
    try:
        sess = db.db_rp_get_session(session_id) if session_id else None
    except Exception:
        sess = None
    if sess:
        lines = []
        for c in (sess.get("characters") or []):
            fn = c.get("card_filename") or ""
            try:
                card = engine.load_card(fn)
            except Exception:
                continue
            d = card.get("data", card)
            name = engine.resolve_char_name(card)
            line = "- " + name
            desc = _clip(str(d.get("description") or ""), 800)
            scen = _clip(str(d.get("scenario") or ""), 400)
            if desc:
                line += ": " + desc
            if scen:
                line += " | scenario: " + scen
            habit = _habit_from_card(card, d)
            if habit:
                line += " | usual look: " + habit
            lines.append(line)
        characters_block = "\n".join(lines)
        pfn = sess.get("persona_filename")
        if pfn:
            try:
                persona = json.loads((db.PERSONAS_DIR / pfn).read_text(encoding="utf-8"))
                pdesc = _clip(str(persona.get("description") or ""), 500)
                persona_block = f"- {persona.get('name', 'Unknown')}" + (f": {pdesc}" if pdesc else "")
            except Exception:
                persona_block = ""
    return characters_block, persona_block


def build_caption_messages(messages, session_id=None, characters_block=None,
                           persona_block=None, style=None, word_target=None,
                           window=None, pov=None, token_cap=None) -> list:
    """Assemble [system, user] for the scene captioner.

    `window` (config caption_window) trims the chat slice; `style` maps to
    {"medium", "lighting", "mood"} and each non-empty phrase is handed over
    as a use-once budget. Explicit blocks skip the session lookup (tests).

    `pov="user"` renders the frame from the user's eyes (per-session
    `image_pov` setting; explicit arg wins): a fixed first-person camera —
    the persona is the camera and never in frame. `None`/`"auto"` leaves
    the camera to the chat (the system prompt's rule 6).
    """
    if window is None:
        window = db.IMAGEGEN_CAPTION_WINDOW
    if style is None:
        style = {"medium": db.IMAGEGEN_STYLE_MEDIUM,
                 "lighting": db.IMAGEGEN_STYLE_LIGHTING,
                 "mood": db.IMAGEGEN_STYLE_MOOD}
    if characters_block is None and persona_block is None and session_id:
        characters_block, persona_block = caption_session_context(session_id)
    if pov is None and session_id:
        # autogen path: the standing per-session setting decides
        try:
            pov = (db.db_rp_get_session(session_id) or {}).get("image_pov")
        except Exception:
            pov = None
    if token_cap is None and session_id:
        # same standing-setting pattern as the POV option
        try:
            token_cap = (db.db_rp_get_session(session_id) or {}).get("image_token_cap")
        except Exception:
            token_cap = None
    pov = (pov or "").strip().lower()
    pov_user = pov == "user"
    window = max(1, int(window))
    convo_lines = []
    for m in list(messages)[-window:]:
        label = m.get("speaker") or m.get("role") or "unknown"
        convo_lines.append(f"[{label}]: {m.get('content', '')}")
    parts = ["Recent conversation (the scene to illustrate):",
             "\n".join(convo_lines) or "(none)"]
    if characters_block:
        parts += ["",
                  "Characters in the scene — appearance comes from their cards; this is how they look:",
                  characters_block]
    if persona_block:
        if pov_user:
            # the persona IS the camera — identity never rendered
            parts += ["", "The persona you play is the camera — never visible in frame:", persona_block]
        else:
            parts += ["", "The persona you play (also visible if the scene shows it):", persona_block]
    if pov_user:
        cam_name = "the user"
        if persona_block:
            cam_name = persona_block.lstrip("- ").split(":", 1)[0].strip() or cam_name
        parts += ["",
                  f"Camera (fixed): first-person POV — the scene is seen from the eyes of {cam_name}. "
                  f"{cam_name} is not visible in frame (at most their hands or arms enter it). "
                  f"Every character faces the camera as if looking at {cam_name}. "
                  "Compose around this vantage; keep it for the whole caption."]
    budget = [f'{k}="{str(v).strip()}"' for k, v in
              (("medium", style.get("medium")), ("lighting", style.get("lighting")),
               ("mood", style.get("mood"))) if v and str(v).strip()]
    if budget:
        parts += ["", "Style budget — use each exactly once: " + "; ".join(budget)]
    parts += ["", "Write the scene caption, or SKIP."]
    return [{"role": "system", "content": auto_img_system(word_target, token_cap=token_cap)},
            {"role": "user", "content": "\n".join(parts)}]


def parse_caption_response(raw: str | None):
    """Caption string, or None for SKIP.

    Reasoning wrappers are stripped first — the configured captioner is a
    DeepSeek-R1 variant whose thinking must not leak into the prompt.
    The SKIP decision reads the FIRST LINE only: a caption containing a
    word like "skipping" must never be mistaken for it (the old parser's
    whole-text `if "SKIP" in raw` check did exactly that).
    """
    text = (raw or "").strip()
    text = re.sub(r"\$\$.*?\$\$", "", text, flags=re.S)      # DeepSeek-R1 thinking
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.S | re.I)
    text = text.replace("$$", "")
    text = text.strip()
    first = text.split("\n", 1)[0].strip()
    if re.match(r"SKIP(?:$|[.:!,;\s-])", first, re.I):
        return None
    if text.upper().startswith("PROMPT:"):
        text = text[7:].strip()
    return text or None


async def auto_generate_image_prompt(messages: list[dict], send_fn=None, force: bool = False,
                                     session_id=None, raise_errors: bool = False) -> str | None:
    """
    Ask the captioner LLM for a MOSS-Image scene caption (or SKIP).
    Returns the caption, or None on SKIP. `session_id` adds the session's
    character cards (appearance/scenario) and persona as context.
    When `force=True`, bypasses the enabled check (manual on-demand use).
    raise_errors=True re-raises LLM failures instead of returning None —
    a dead endpoint must not be reported to the user as "the LLM said SKIP".
    """
    if not force and not db.IMAGEGEN_AUTO_ENABLED:
        return None

    llm_messages = build_caption_messages(messages, session_id=session_id)

    if send_fn:
        await send_fn({
            "type": "console_event", "event": "request", "llm": "imagegen_auto",
            "model": db.IMAGEGEN_AUTO_MODEL, "label": "Auto Image Prompt",
            "temperature": db.IMAGEGEN_AUTO_TEMPERATURE, "max_tokens": db.IMAGEGEN_AUTO_MAX_TOKENS,
            "messages": llm_messages, "timestamp": _now_iso(),
        })

    try:
        kwargs = dict(
            model=db.IMAGEGEN_AUTO_MODEL,
            messages=llm_messages,
            temperature=db.IMAGEGEN_AUTO_TEMPERATURE,
            max_tokens=db.IMAGEGEN_AUTO_MAX_TOKENS,
        )
        resp = await db.imagegen_auto_client.chat.completions.create(**kwargs)
        raw = resp.choices[0].message.content.strip()
        usage = resp.usage

        if send_fn:
            await send_fn({
                "type": "console_event", "event": "response", "llm": "imagegen_auto",
                "model": db.IMAGEGEN_AUTO_MODEL, "label": "Auto Image Prompt",
                "content": raw,
                "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "total_tokens": usage.total_tokens} if usage else None,
                "finish_reason": resp.choices[0].finish_reason, "timestamp": _now_iso(),
            })

        # First-line SKIP decision + reasoning-wrapper stripping
        return parse_caption_response(raw)

    except Exception as e:
        if send_fn:
            try:
                await send_fn({"type": "error", "message": f"Auto image prompt error: {e}"})
            except Exception:
                pass
        if raise_errors:
            raise
        return None


async def maybe_auto_generate_image(session_id: int, messages: list[dict], send_fn,
                                     image_add_fn=None) -> None:
    """
    Check if auto image generation should trigger (based on message count interval),
    ask the LLM for a prompt, generate the image, and insert it into the chat.

    Args:
        session_id: DB session ID
        messages: recent messages from the session (list of dicts with role/content)
        send_fn: async callable for sending WS events
        image_add_fn: async callable(image_path: str) to insert the generated image
                      into the session's DB + send the WS message. If None, uses a default.
    """
    if not db.IMAGEGEN_AUTO_ENABLED or not db.IMAGEGEN_ENABLED:
        return

    interval = max(1, db.IMAGEGEN_AUTO_INTERVAL)
    msg_count = len(messages)
    if msg_count == 0 or msg_count % interval != 0:
        return

    # Ask LLM for a prompt
    prompt = await auto_generate_image_prompt(messages, send_fn=send_fn, session_id=session_id)
    if not prompt:
        return

    await send_fn({"type": "console_event", "event": "auto_image_prompt", "content": prompt, "timestamp": _now_iso()})

    # Generate the image via ComfyUI
    negative = db.IMAGEGEN_AUTO_NEGATIVE or db.IMAGEGEN_NEGATIVE or ""
    result = await generate_image(prompt, negative)
    if not result.get("success"):
        await send_fn({"type": "console_event", "event": "auto_image_error", "error": result.get("error", "unknown"), "timestamp": _now_iso()})
        return

    image_path = result["image_path"]
    await send_fn({"type": "console_event", "event": "auto_image_generated", "image_path": image_path, "prompt": prompt, "timestamp": _now_iso()})

    # Insert into session via callback
    if image_add_fn:
        await image_add_fn(image_path, prompt, result.get("seed"))


# ─── REST endpoints ────────────────────────────────────────────────

@router.post("/api/generate-image")
async def api_generate_image(request: Request):
    """
    Generate a scene image via ComfyUI.
    Request body: {"prompt": "...", "negative_prompt": "...", "session_id": N}
    Returns: {"success": true, "image_path": "..."} or {"success": false, "error": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)

    prompt_text = body.get("prompt", "").strip()
    if not prompt_text:
        return JSONResponse({"success": False, "error": "Prompt is required"}, status_code=400)

    negative = body.get("negative_prompt", "") or db.IMAGEGEN_NEGATIVE

    seed_override = body.get("seed")
    if seed_override is not None:
        try:
            seed_override = int(seed_override)
        except (ValueError, TypeError):
            seed_override = None

    result = await generate_image(prompt_text, negative, seed=seed_override,
                                  width=body.get("width"), height=body.get("height"))
    if not result["success"]:
        return JSONResponse(result, status_code=500)
    return JSONResponse(result)


@router.post("/api/imagegen/auto-prompt")
async def api_auto_image_prompt(request: Request):
    """
    Use the auto-gen LLM to produce a scene image prompt from recent messages.
    Request body: {"messages": [{"role": "...", "content": "...", ...}, ...]}
    Returns: {"success": true, "prompt": "..."} or {"success": false, "error": "..."}
    When the LLM decides SKIP, returns {"success": true, "prompt": null, "skipped": true}.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)
    messages = body.get("messages", [])
    if not messages:
        return JSONResponse({"success": False, "error": "No messages provided"}, status_code=400)
    session_id = body.get("session_id")
    try:
        prompt = await auto_generate_image_prompt(messages, force=True,
                                                  session_id=session_id,
                                                  raise_errors=True)
    except Exception as e:
        return JSONResponse({"success": False,
                             "error": f"Captioner LLM failed: {e}"},
                            status_code=502)
    if prompt is None:
        return JSONResponse({"success": True, "prompt": None, "skipped": True})
    return JSONResponse({"success": True, "prompt": prompt, "skipped": False})


@router.get("/api/imagegen/status")
async def api_imagegen_status():
    """Check if ComfyUI is reachable and image generation is enabled."""
    if not db.IMAGEGEN_ENABLED:
        return JSONResponse({"enabled": False, "reachable": False, "base_url": db.IMAGEGEN_BASE_URL})

    base_url = db.IMAGEGEN_BASE_URL.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{base_url}/system_stats")
            reachable = resp.status_code == 200
        return JSONResponse({"enabled": True, "reachable": reachable, "base_url": db.IMAGEGEN_BASE_URL})
    except Exception:
        return JSONResponse({"enabled": True, "reachable": False, "base_url": db.IMAGEGEN_BASE_URL})
