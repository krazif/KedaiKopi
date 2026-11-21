"""KedaiKopi — character/persona library routes + AI card generation.

Split out of the parent app's school router: these endpoints serve the
card library (list/get/save/delete/upload/download/validate), personas,
and card generation — features shared with any mode, nothing school
specific. Mounted by main.py.
"""
import io
import json
import re
from pathlib import Path

from fastapi import APIRouter, Request, UploadFile, File as FastAPIFile
from fastapi.responses import JSONResponse, Response
from json_repair import repair_json

import db
import engine

router = APIRouter()


@router.get("/api/cards")
async def api_list_cards():
    return JSONResponse(engine.list_cards())


@router.get("/api/cards/{filename}")
async def api_get_card(filename: str):
    try:
        card = engine.load_card(filename)
        return JSONResponse(card)
    except FileNotFoundError:
        return JSONResponse({"error": "Card not found"}, status_code=404)
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)


@router.delete("/api/cards/{filename}")
async def api_delete_card(filename: str):
    """Delete a character card JSON and its associated avatar PNG."""
    path = db.CHARACTERS_DIR / filename
    if not path.exists():
        return JSONResponse({"error": "Card not found"}, status_code=404)
    try:
        path.unlink()
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)
    # Also delete avatar PNG if it exists
    stem = Path(filename).stem
    avatar_path = db.CHARACTERS_DIR / f"{stem}_avatar.png"
    if avatar_path.exists():
        try:
            avatar_path.unlink()
        except Exception:
            pass  # non-fatal if avatar deletion fails
    return JSONResponse({"status": "deleted", "filename": filename})


@router.put("/api/cards/{filename}")
async def api_save_card(filename: str, data: dict):
    try:
        engine.save_card(filename, data)
        return JSONResponse({"status": "saved", "filename": filename})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/cards/upload")
async def api_upload_card(file: UploadFile = FastAPIFile(...)):
    """Upload a character card JSON or PNG file."""
    try:
        content = await file.read()
        filename_in = file.filename or ""

        # Detect PNG files by magic bytes or extension
        is_png = content[:8] == b'\\x89PNG\\r\\n\\x1a\\n' or filename_in.lower().endswith(".png")

        if is_png:
            # Extract chara JSON from PNG tEXt/iTXt chunk
            data = engine.extract_chara_from_png(content)
            if data is None:
                # Check if it's a valid PNG image without chara data
                from PIL import Image
                try:
                    img = Image.open(io.BytesIO(content))
                    return JSONResponse({
                        "error": "No 'chara' metadata found in PNG. This appears to be a regular image, not a character card PNG. Character card PNGs must have embedded JSON metadata (tEXt 'chara' chunk)."
                    }, status_code=400)
                except Exception:
                    return JSONResponse({"error": "File has .png extension but is not a valid PNG image."}, status_code=400)
        else:
            text = content.decode("utf-8")
            data = json.loads(text)

        # Validate basic structure
        d = data.get("data", data)
        name = d.get("name", "")
        if not name:
            return JSONResponse({"error": "Invalid character card: missing 'name' field"}, status_code=400)

        # Derive filename from card name
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name.lower()).strip('_')
        if not safe_name:
            safe_name = "uploaded_card"
        filename = f"{safe_name}.json"

        engine.save_card(filename, data)

        # If it was a PNG, also save the avatar image
        if is_png:
            try:
                from PIL import Image
                img = Image.open(io.BytesIO(content))
                avatar_path = db.CHARACTERS_DIR / f"{safe_name}_avatar.png"
                # Save just the image without metadata to keep it small
                img.convert("RGBA").save(str(avatar_path), format="PNG")
            except Exception:
                pass  # avatar save is best-effort

        return JSONResponse({"status": "uploaded", "filename": filename, "name": name, "format": "png" if is_png else "json"})
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/cards/{filename}/png")
async def api_download_card_png(filename: str):
    """Download a character card as a PNG with embedded chara metadata."""
    try:
        path = db.CHARACTERS_DIR / filename
        if not path.exists():
            return JSONResponse({"error": "Card not found"}, status_code=404)
        data = json.loads(path.read_text(encoding="utf-8"))

        # Check for an existing avatar image
        stem = path.stem
        avatar_bytes = None
        avatar_path = db.CHARACTERS_DIR / f"{stem}_avatar.png"
        if avatar_path.exists():
            avatar_bytes = avatar_path.read_bytes()

        png_bytes = engine.create_chara_png(data, avatar_bytes)

        d = data.get("data", data)
        name = d.get("name", stem)
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', name.lower()).strip('_') or "card"
        download_name = f"{safe_name}.png"

        return Response(
            content=png_bytes,
            media_type="image/png",
            headers={"Content-Disposition": f'attachment; filename="{download_name}"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/cards/{filename}/json")
async def api_download_card_json(filename: str):
    """Download a character card as raw JSON."""
    try:
        path = db.CHARACTERS_DIR / filename
        if not path.exists():
            return JSONResponse({"error": "Card not found"}, status_code=404)
        data = path.read_text(encoding="utf-8")
        return Response(
            content=data,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/cards/{filename}/validate")
async def api_validate_card(filename: str, data: dict):
    """Validate a card's JSON structure and check for common issues."""
    issues = []
    d = data.get("data", data)
    version = engine.detect_card_version(data)

    # Check required fields
    required = ["name", "description", "system_prompt"]
    for field in required:
        val = engine.get_card_field(d, field, version)
        if not val:
            issues.append({"severity": "error", "field": field, "message": f"Missing required field: {field}"})

    # Check for banned divine name references
    banned_words = ["Allah", "Alhamdulillah", "Insya-Allah", "Insya Allah", "Masya-Allah",
                    "Masya Allah", "Subhanallah", "Subhan Allah", "Insha Allah", "Insha-Allah",
                    "Astaghfirullah", "Allahu Akbar", "Bismillah"]
    raw = json.dumps(data)
    for word in banned_words:
        if word.lower() in raw.lower():
            idx = raw.lower().find(word.lower())
            ctx = raw[max(0, idx-40):idx+len(word)+40]
            issues.append({"severity": "warning", "field": "general", "message": f"Found '{word}' in card: ...{ctx}..."})

    # Check for Chinese Manglish particles outside "NOT" context
    import re
    for particle in ["lah", "lor", "meh", "kah"]:
        for m in re.finditer(r'\b' + particle + r'\b', raw):
            pos = m.start()
            ctx = raw[max(0, pos-60):pos+60]
            if "NOT" in ctx or "not Chinese" in ctx or "no lah" in ctx.lower():
                continue
            issues.append({"severity": "warning", "field": "speech", "message": f"Found '{particle}' outside negation context: ...{ctx}..."})

    return JSONResponse({"valid": len([i for i in issues if i["severity"] == "error"]) == 0, "issues": issues})


# ─── Persona API Routes ───────────────────────────────────────────
@router.get("/api/personas")
async def api_list_personas():
    return JSONResponse(engine.list_personas())


@router.get("/api/personas/{filename}")
async def api_get_persona(filename: str):
    try:
        persona = engine.load_persona(filename)
        return JSONResponse(persona)
    except FileNotFoundError:
        return JSONResponse({"error": "Persona not found"}, status_code=404)
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)


@router.put("/api/personas/{filename}")
async def api_save_persona(filename: str, data: dict):
    try:
        engine.save_persona(filename, data)
        return JSONResponse({"status": "saved", "filename": filename})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/personas/upload")
async def api_upload_persona(file: UploadFile = FastAPIFile(...)):
    """Upload a persona JSON file."""
    try:
        content = await file.read()
        text = content.decode("utf-8")
        data = json.loads(text)

        # Validate basic structure
        name = data.get("name", "")
        if not name:
            return JSONResponse({"error": "Invalid persona: missing 'name' field"}, status_code=400)

        # Derive filename from persona name
        import re as _re
        safe_name = _re.sub(r'[^a-zA-Z0-9_-]', '_', name.lower()).strip('_')
        if not safe_name:
            safe_name = "uploaded_persona"
        filename = f"{safe_name}.json"

        engine.save_persona(filename, data)
        return JSONResponse({"status": "uploaded", "filename": filename, "name": name})
    except json.JSONDecodeError as e:
        return JSONResponse({"error": f"Invalid JSON: {e}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/personas/{filename}/validate")
async def api_validate_persona(filename: str, data: dict):
    """Validate a persona's structure."""
    issues = []
    required = ["name", "description", "personality"]
    for field in required:
        if not data.get(field):
            issues.append({"severity": "error", "field": field, "message": f"Missing required field: {field}"})

    return JSONResponse({"valid": len([i for i in issues if i["severity"] == "error"]) == 0, "issues": issues})


GEN_V2_SYSTEM = """You are a character card generator. You create rich, compelling character cards for roleplay.

Output ONLY valid JSON, no markdown fences, no commentary.

Generate a chara_card_v2 character card with this exact structure:
{
  "spec": "chara_card_v2",
  "spec_version": "2.0",
  "data": {
    "name": "",
    "description": "",
    "personality": "",
    "scenario": "",
    "first_mes": "",
    "mes_example": "",
    "creator_notes": "",
    "system_prompt": "",
    "post_history_instructions": "",
    "tags": [],
    "creator": "{creator}",
    "character_version": "",
    "alternate_greetings": [],
    "extensions": {}
  }
}

Field guidelines:
- **name**: The character's full name.
- **description**: Physical appearance, background, and core identity. 2-4 paragraphs. Use {{char}} for the character's name.
- **personality**: Traits, quirks, speech style, values, flaws. 2-3 paragraphs. Use {{char}}.
- **scenario**: The current situation / context where the roleplay begins. 1-2 paragraphs.
- **first_mes**: An opening message in character, 2-4 sentences. Use {{char}} and {{user}}. Write in third person narrative + dialogue.
- **mes_example**: 2-4 example dialogue exchanges showing the character's voice. Use {{char}} and {{user}}. Format as dialogue.
- **creator_notes**: Brief notes for the user about the character. 1-2 sentences.
- **system_prompt**: A brief system instruction for the AI playing this character (e.g. "Stay in character as {{char}}. Maintain their personality and speech patterns.").
- **tags**: 3-8 relevant tags (e.g. ["original", "female", "teacher", "shy"]).
- **alternate_greetings**: Leave empty array [] unless multiple greetings are clearly warranted.
- **extensions**: Leave empty object {}.

Be creative but coherent. Every field must be filled with quality content."""

GEN_V1_SYSTEM = """You are a character card generator. You create rich, compelling character cards for roleplay.

Output ONLY valid JSON, no markdown fences, no commentary.

Generate a V1 character card with this exact flat structure:
{
  "name": "",
  "description": "",
  "personality": "",
  "scenario": "",
  "first_mes": "",
  "mes_example": "",
  "creator": "{creator}",
  "character_version": "",
  "tags": []
}

Field guidelines:
- **name**: The character's full name.
- **description**: Physical appearance, background, and core identity. 2-4 paragraphs. Use {{char}} for the character's name.
- **personality**: Traits, quirks, speech style, values, flaws. 2-3 paragraphs. Use {{char}}.
- **scenario**: The current situation / context where the roleplay begins. 1-2 paragraphs.
- **first_mes**: An opening message in character, 2-4 sentences. Use {{char}} and {{user}}. Write in third person narrative + dialogue.
- **mes_example**: 2-4 example dialogue exchanges showing the character's voice. Use {{char}} and {{user}}. Format as dialogue.
- **tags**: 3-8 relevant tags (e.g. ["original", "female", "teacher", "shy"]).

Be creative but coherent. Every field must be filled with quality content."""


@router.post("/api/generate-character")
async def generate_character(req: Request):
    """Generate a character card using the chat LLM endpoint."""
    body = await req.json()
    concept = (body.get("concept") or "").strip()
    if not concept:
        return JSONResponse({"error": "Concept is required"}, status_code=400)

    version = body.get("version", 2)
    name_hint = (body.get("name") or "").strip()
    age_hint = (body.get("age") or "").strip()
    personality_hint = (body.get("personality") or "").strip()
    scenario_hint = (body.get("scenario") or "").strip()
    appearance_hint = (body.get("appearance") or "").strip()
    nsfw = body.get("nsfw", False)
    creator_name = (body.get("creator") or "").strip() or "Richard"

    # Build user prompt from hints
    parts = [f"Concept: {concept}"]
    if name_hint:
        parts.append(f"Name: {name_hint}")
    if age_hint:
        parts.append(f"Age: {age_hint}")
    if personality_hint:
        parts.append(f"Personality hints: {personality_hint}")
    if scenario_hint:
        parts.append(f"Scenario/setting hints: {scenario_hint}")
    if appearance_hint:
        parts.append(f"Appearance hints: {appearance_hint}")
    if nsfw:
        parts.append("Content rating: NSFW (adult content is acceptable in the card)")
    else:
        parts.append("Content rating: SFW (keep all content safe for work)")

    user_prompt = "\n".join(parts)
    system_prompt = (GEN_V2_SYSTEM if version == 2 else GEN_V1_SYSTEM).replace("{creator}", creator_name)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    console_events = [{
        "type": "console_event", "event": "request", "llm": "character",
        "model": db.CHAT_MODEL, "label": "Character Generation",
        "temperature": 0.9, "max_tokens": 4000,
        "messages": messages, "timestamp": engine._now_iso(),
    }]

    try:
        completion = await db.chat_client.chat.completions.create(
            model=db.CHAT_MODEL,
            messages=messages,
            temperature=0.9,
            max_tokens=4000,
            extra_body=engine.build_extra_body(db.CHAT_MODEL, db.CHAT_ENABLE_THINKING),
        )
        raw = completion.choices[0].message.content or ""

        usage = completion.usage
        console_events.append({
            "type": "console_event", "event": "response", "llm": "character",
            "model": db.CHAT_MODEL, "label": "Character Generation",
            "content": raw,
            "usage": {"prompt_tokens": usage.prompt_tokens, "completion_tokens": usage.completion_tokens, "total_tokens": usage.total_tokens} if usage else None,
            "finish_reason": completion.choices[0].finish_reason, "timestamp": engine._now_iso(),
        })

        card = json.loads(repair_json(raw))

        # Normalize: ensure correct spec for V2
        if version == 2:
            if "data" not in card:
                # LLM put everything at top level — wrap it
                card = {"spec": "chara_card_v2", "spec_version": "2.0", "data": card}
            card["spec"] = "chara_card_v2"
            card["spec_version"] = "2.0"
            card.setdefault("data", {}).setdefault("creator", creator_name)
        else:
            # V1: flatten if accidentally nested
            if "data" in card:
                card = card["data"]
            card.pop("spec", None)
            card.pop("spec_version", None)
            card.setdefault("creator", creator_name)

        return {"card": card, "version": version, "console_events": console_events, "usage": getattr(completion, "usage", None) and completion.usage.model_dump()}

    except Exception as e:
        console_events.append({
            "type": "console_event", "event": "error", "llm": "character",
            "model": db.CHAT_MODEL, "label": "Character Generation",
            "message": str(e), "timestamp": engine._now_iso(),
        })
        return JSONResponse({"error": str(e), "console_events": console_events}, status_code=500)


@router.post("/api/generate-character/save")
async def save_generated_character(req: Request):
    """Save a generated/previewed character card to the characters directory."""
    body = await req.json()
    card = body.get("card")
    if not card or not isinstance(card, dict):
        return JSONResponse({"error": "Invalid card data"}, status_code=400)

    # Extract name for filename
    version = engine.detect_card_version(card)
    data = card.get("data", card) if version >= 2 else card
    name = (data.get("name") or "unnamed").strip()
    if not name:
        name = "unnamed"

    # Sanitize filename
    safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '_', name).strip('_').lower() or "unnamed"
    filename = f"{safe_name}.json"

    # Avoid overwriting existing files
    if db.CHARACTERS_DIR.exists():
        counter = 1
        while (db.CHARACTERS_DIR / filename).exists():
            filename = f"{safe_name}_{counter}.json"
            counter += 1

    engine.save_card(filename, card)
    return {"status": "ok", "filename": filename, "name": name}
