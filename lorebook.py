"""
KedaiKopi — Lorebook (World Info) module.
SillyTavern-compatible lorebook storage and keyword-triggered injection.

Lorebooks are stored as JSON files in the lorebooks directory.
Each lorebook has the SillyTavern World Info format:
{
  "entries": {
    "0": {
      "uid": 0,
      "key": ["keyword1", "keyword2"],
      "keysecondary": ["keyword3"],
      "comment": "Entry description",
      "content": "Lore text to inject",
      "constant": false,
      "selective": true,
      "order": 100,
      "position": 0,       # 0=before system, 1=after system, 2=before chat
      "disable": false,
      "extensions": {}
    }
  }
}
"""
import json
import re

from json_repair import repair_json
import os
from pathlib import Path
from typing import Optional
import db


def _lorebooks_dir() -> Path:
    """Get the lorebooks directory, creating it if needed."""
    d = Path(db.APP_DIR) / "lorebooks"
    d.mkdir(parents=True, exist_ok=True)
    return d


def list_lorebooks() -> list[dict]:
    """List all lorebooks with summary info."""
    d = _lorebooks_dir()
    result = []
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            entries = data.get("entries", {})
            entry_count = len(entries)
            active_count = sum(1 for e in entries.values() if not e.get("disable", False))
            constant_count = sum(1 for e in entries.values() if e.get("constant", False) and not e.get("disable", False))
            result.append({
                "filename": p.name,
                "name": data.get("name", p.stem),
                "description": data.get("description", ""),
                "entry_count": entry_count,
                "active_count": active_count,
                "constant_count": constant_count,
            })
        except (json.JSONDecodeError, KeyError):
            result.append({"filename": p.name, "name": p.stem, "description": "", "entry_count": 0, "active_count": 0, "constant_count": 0, "error": True})
    return result


def load_lorebook(filename: str) -> dict:
    """Load a lorebook by filename."""
    path = _lorebooks_dir() / filename
    if not path.exists():
        raise FileNotFoundError(f"Lorebook not found: {filename}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_lorebook(filename: str, data: dict) -> None:
    """Save a lorebook by filename."""
    path = _lorebooks_dir() / filename
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def delete_lorebook(filename: str) -> bool:
    """Delete a lorebook. Returns True if deleted."""
    path = _lorebooks_dir() / filename
    if not path.exists():
        return False
    path.unlink()
    return True


def create_lorebook(name: str, description: str = "") -> dict:
    """Create a new empty lorebook and return its info."""
    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in name.lower()).strip("_")
    if not safe_name:
        safe_name = "lorebook"
    filename = f"{safe_name}.json"
    # Avoid overwrites
    d = _lorebooks_dir()
    counter = 1
    while (d / filename).exists():
        filename = f"{safe_name}_{counter}.json"
        counter += 1
    data = {
        "name": name,
        "description": description,
        "entries": {},
    }
    save_lorebook(filename, data)
    return {"filename": filename, "name": name, "description": description, "entry_count": 0}


# ─── Keyword Matching Engine ───────────────────────────────────────

def _check_keywords(keywords: list[str], text: str, case_insensitive: bool = True) -> bool:
    """Check if any of the keywords appear in the text.
    Keywords can be single words or multi-word phrases."""
    if not keywords:
        return False
    haystack = text.lower() if case_insensitive else text
    for kw in keywords:
        if not kw:
            continue
        needle = kw.lower() if case_insensitive else kw
        if needle in haystack:
            return True
    return False


def scan_for_active_entries(lorebook: dict, recent_messages: list[dict],
                            scan_depth: int = 10) -> list[dict]:
    """Scan recent messages for keyword triggers and return active entries.

    Args:
        lorebook: The lorebook dict with "entries"
        recent_messages: List of message dicts with "content" key
        scan_depth: Number of recent messages to scan (from the end)

    Returns:
        List of active entry dicts sorted by order (descending = higher priority first)
    """
    entries = lorebook.get("entries", {})
    if not entries:
        return []

    # Build the text to scan from recent messages
    msgs_to_scan = recent_messages[-scan_depth:] if len(recent_messages) > scan_depth else recent_messages
    scan_text = " ".join(m.get("content", "") for m in msgs_to_scan)

    active = []
    for uid_str, entry in entries.items():
        if entry.get("disable", False):
            continue

        is_active = False

        if entry.get("constant", False):
            # Constant entries are always active
            is_active = True
        else:
            keys = entry.get("key", [])
            if not keys:
                continue

            if entry.get("selective", False) and entry.get("keysecondary"):
                # Selective mode: need at least one primary AND one secondary match
                primary_match = _check_keywords(keys, scan_text)
                secondary_match = _check_keywords(entry["keysecondary"], scan_text)
                is_active = primary_match and secondary_match
            else:
                # Normal mode: any primary keyword match
                is_active = _check_keywords(keys, scan_text)

        if is_active:
            active.append(entry)

    # SillyTavern insertion order: constant entries first, then ascending
    # `order` — ST puts larger order numbers CLOSER to the end of the
    # context ("an entry with Order 100 appears before an entry with
    # Order 250"), i.e. higher order = more impact.
    active.sort(key=lambda e: (0 if e.get("constant") else 1, e.get("order", 100)))
    return active


# Entry placement, simplified from SillyTavern's insertion positions to what
# this prompt structure supports:
#   0 = before system — prepended to the system message (moderate impact)
#   1 = after system  — appended to the system message (greater impact)
#   2 = before chat   — its own system message directly before the first
#                       user turn (greatest impact)
POSITION_BEFORE_SYSTEM = 0
POSITION_AFTER_SYSTEM = 1
POSITION_BEFORE_CHAT = 2


def build_lorebook_blocks(lorebooks: list[dict], recent_messages: list[dict],
                          scan_depth: int = 10) -> dict:
    """Scan lorebooks and group active entries by position.

    Returns {0: text, 1: text, 2: text} with "" for positions that fired
    nothing. Within a position, entries keep ST insertion order: constants
    first, then ascending `order` (larger order = closer to the end of the
    context = more impact), merged across books as if one file.
    """
    groups: dict = {POSITION_BEFORE_SYSTEM: [], POSITION_AFTER_SYSTEM: [],
                    POSITION_BEFORE_CHAT: []}
    for lb in lorebooks:
        lb_name = lb.get("name", "Unknown")
        for entry in scan_for_active_entries(lb, recent_messages, scan_depth):
            content = (entry.get("content") or "").strip()
            if not content:
                continue
            # Missing/unknown position -> after system = where the old
            # code always put it (appended to the system message).
            pos = entry.get("position", POSITION_AFTER_SYSTEM)
            if pos not in groups:
                pos = POSITION_AFTER_SYSTEM
            groups[pos].append({
                "lorebook": lb_name,
                "comment": entry.get("comment", ""),
                "content": content,
                "order": entry.get("order", 100),
                "constant": bool(entry.get("constant", False)),
            })

    blocks = {}
    for pos, entries in groups.items():
        entries.sort(key=lambda e: (0 if e["constant"] else 1, e["order"]))
        if not entries:
            blocks[pos] = ""
            continue
        parts = ["WORLD INFO (LOREBOOK ENTRIES):"]
        for e in entries:
            label = e["comment"] if e["comment"] else "(unnamed)"
            parts.append(f"[{e['lorebook']} — {label}]")
            parts.append(e["content"])
            parts.append("")
        blocks[pos] = "\n".join(parts)
    return blocks


def _join(a: str, b: str) -> str:
    """Concatenate two prompt fragments without a stray blank line."""
    if not a:
        return b
    if not b:
        return a
    return a + "\n\n" + b


def apply_lorebook_blocks(llm_messages: list[dict], blocks: dict) -> str:
    """Place each position block into llm_messages; returns injected text.

    Position 0/1 need a leading system message — if the stack built none,
    one is created rather than silently dropping the lore (the old code's
    failure mode).
    """
    before = (blocks.get(POSITION_BEFORE_SYSTEM) or "").strip()
    after = (blocks.get(POSITION_AFTER_SYSTEM) or "").strip()
    chat = (blocks.get(POSITION_BEFORE_CHAT) or "").strip()
    injected = "\n\n".join(t for t in (before, after, chat) if t)
    if not injected:
        return ""

    has_system = bool(llm_messages) and llm_messages[0].get("role") == "system"
    if (before or after) and not has_system:
        llm_messages.insert(0, {"role": "system", "content": ""})
    if before:
        sys_msg = llm_messages[0]
        sys_msg["content"] = _join(before, sys_msg.get("content", ""))
    if after:
        sys_msg = llm_messages[0]
        sys_msg["content"] = _join(sys_msg.get("content", ""), after)
    if chat:
        idx = next((i for i, m in enumerate(llm_messages)
                    if m.get("role") != "system"), len(llm_messages))
        llm_messages.insert(idx, {"role": "system", "content": chat})
    return injected


def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


async def inject_lorebook(llm_messages: list[dict], session: dict,
                          all_msgs: list[dict], send,
                          scan_depth: int = 10) -> str:
    """Load a session's attached lorebooks, inject active entries, notify.

    This is the single injection path: it replaced six hand-rolled blocks
    in the parent codebase. `send` is the async JSON sender for the console
    event (ws.send_json / _safe_send). Returns the injected text ('' if none).
    """
    filenames = []
    raw = (session or {}).get("lorebooks")
    if raw:
        try:
            filenames = json.loads(raw)
        except (TypeError, ValueError):
            filenames = []
    if not filenames:
        return ""
    blocks = build_lorebook_blocks(load_lorebooks_for_session(filenames),
                                   all_msgs, scan_depth)
    injected = apply_lorebook_blocks(llm_messages, blocks)
    if injected:
        await send({
            "type": "console_event", "event": "lorebook_injection",
            "content": injected, "timestamp": _now_iso(),
        })
    return injected


def load_lorebooks_for_session(lorebook_filenames: list[str]) -> list[dict]:
    """Load multiple lorebooks by filename, skipping missing ones."""
    result = []
    for fn in lorebook_filenames:
        try:
            result.append(load_lorebook(fn))
        except FileNotFoundError:
            pass
    return result


def _unique_filename(safe_name: str) -> str:
    """Generate a unique .json filename, appending _N if needed."""
    filename = f"{safe_name}.json"
    d = _lorebooks_dir()
    counter = 1
    while (d / filename).exists():
        filename = f"{safe_name}_{counter}.json"
        counter += 1
    return filename


def _normalize_entry(uid, entry: dict) -> dict:
    """Normalize a single lorebook entry to have all required fields."""
    try:
        uid_int = int(uid)
    except (ValueError, TypeError):
        uid_int = uid
    return {
        "uid": entry.get("uid", uid_int),
        "key": entry.get("key", []) or [],
        "keysecondary": entry.get("keysecondary", []) or [],
        "comment": entry.get("comment", ""),
        "content": entry.get("content", ""),
        "constant": entry.get("constant", False),
        "selective": entry.get("selective", False),
        "order": entry.get("order", 100),
        "position": entry.get("position", POSITION_AFTER_SYSTEM),
        "disable": entry.get("disable", False),
        "extensions": entry.get("extensions", {}) or {},
    }


def import_lorebook(data: dict, override_name: str = "") -> dict:
    """Import a lorebook from SillyTavern World Info JSON or our own format.

    Accepts both SillyTavern format (entries dict at top level) and our
    extended format (name, description, entries). All entries are normalized
    to have every required field. A unique filename is generated to avoid
    overwriting existing lorebooks.

    Returns the new lorebook's summary info.
    """
    lb_name = override_name or data.get("name", "")
    description = data.get("description", "")
    entries = data.get("entries", {})

    if not lb_name:
        lb_name = "Imported Lorebook"

    # Normalize all entries
    normalized = {}
    for uid_str, entry in entries.items():
        normalized[str(uid_str)] = _normalize_entry(uid_str, entry)

    out_data = {
        "name": lb_name,
        "description": description,
        "entries": normalized,
    }

    safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in lb_name.lower()).strip("_")
    if not safe_name:
        safe_name = "lorebook"
    filename = _unique_filename(safe_name)

    save_lorebook(filename, out_data)
    return {"filename": filename, "name": lb_name, "description": description, "entry_count": len(normalized)}


# ─── Lorebook generation (card + chats -> entries) ──────────────────

MIN_KEY_LEN = 3
MAX_GEN_ENTRIES = 16

LORE_DISTILL_SYSTEM = """You distill story facts from one chunk of a roleplay chat, about the speaking character and their world: past events, places, objects, relationships, promises, recurring references.

Rules:
1. Nothing invented — each fact traces to the text; when unsure, skip it.
2. Use the conversation's own words for names and terms.
3. One fact per line, plain text, at most 25 words each.
4. Skip greetings, banter, style and formatting.
5. If the chunk establishes nothing new, reply exactly: NONE

Output: fact lines only — no numbering, headers or commentary."""

LORE_GEN_SYSTEM = """You write lorebook (World Info) entries for a roleplay character — the lore BEHIND the card.

Input: the character card (optional), established facts from real chats (optional), his notes (optional).
Output: one JSON object, nothing else:
{"entries":[{"key":["trigger"],"keysecondary":[],"comment":"label","content":"lore","constant":false,"order":100,"position":1}]}

Rules:
1. Scope: backstory, places, past events, items, factions, relationships — anything the story may revisit. Never persona, voice, dialogue or reply guidance: that belongs to the card.
2. One self-contained topic per entry. Content: 50-120 words of third-person factual lore. No second person, no "you/your character", no meta talk.
3. Keys (1-4 per entry): distinctive triggers likely to appear in chat — proper nouns, place names, signature items, multi-word phrases. Never generic words; every key at least 3 characters. keysecondary: extra triggers that must ALSO appear before the entry fires ([] if none).
4. constant:false and position:1 for every entry. order: 100 default; raise to 200 only for the character's most central lore.
5. Chat facts beat the card where they differ — the story is canon. Never mention the conflict.
6. Nothing invented: every detail comes from the input. Missing detail: omit the topic instead of fabricating.
7. At most {max_entries} entries; include only topics worth injecting.

Reply with the JSON object alone — no code fences, no commentary."""


def _clip(text: str, limit: int) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0] + "\u2026"


def _chunk_contents(messages: list[dict], max_chars: int = 6000,
                    max_chunks: int = 12) -> list[str]:
    """Group message texts into chunks at message boundaries; oldest are
    dropped first when the cap bites (recent words are the recurring ones).
    """
    texts = [(m.get("content") or "").strip() for m in messages]
    texts = [t for t in texts if t]
    chunks, cur = [], []
    size = 0
    for t in texts:
        if cur and size + len(t) > max_chars:
            chunks.append("\n\n".join(cur))
            cur, size = [], 0
        cur.append(t)
        size += len(t) + 2
    if cur:
        chunks.append("\n\n".join(cur))
    return chunks[-max_chunks:]


async def _llm_chat(client, model: str, messages: list[dict], max_tokens: int,
                    temperature: float = 0.4, extra_body=None) -> str:
    kwargs = dict(model=model, messages=messages, temperature=temperature,
                  max_tokens=max_tokens)
    if extra_body:
        kwargs["extra_body"] = extra_body
    resp = await client.chat.completions.create(**kwargs)
    return resp.choices[0].message.content or ""


async def distill_chat_facts(messages: list[dict], client, model: str,
                             extra_body=None) -> tuple:
    """(facts_text, chunk_count) — one distill LLM call per chunk.

    The facts feed the entry writer; only words the chats already use
    survive, which is what makes the generated keys actually fire.
    """
    chunks = _chunk_contents(messages)
    facts = []
    for c in chunks:
        raw = await _llm_chat(
            client, model,
            [{"role": "system", "content": LORE_DISTILL_SYSTEM},
             {"role": "user", "content": c}],
            max_tokens=700, extra_body=extra_body)
        for line in (raw or "").splitlines():
            line = line.strip()
            if not line or line.upper() == "NONE":
                continue
            facts.append(line)
    seen = set()
    out = []
    for f in facts:
        if f.lower() not in seen:
            seen.add(f.lower())
            out.append(f)
    return "\n".join(out), len(chunks)


def build_lorebook_gen_messages(card: dict, facts: str = "", notes: str = "",
                                include_card: bool = True,
                                max_entries: int = MAX_GEN_ENTRIES) -> list[dict]:
    """[system, user] for the entry writer."""
    d = card.get("data", card)
    parts = []
    if include_card:
        name = d.get("name") or "Unknown"
        lines = [f"Character name: {name}"]
        desc = _clip(str(d.get("description") or ""), 2000)
        scen = _clip(str(d.get("scenario") or ""), 800)
        pers = _clip(str(d.get("personality") or ""), 600)
        notes_c = _clip(str(d.get("creator_notes") or ""), 600)
        if desc:
            lines.append("Card description:\n" + desc)
        if scen:
            lines.append("Card scenario:\n" + scen)
        if pers:
            lines.append("Card personality:\n" + pers)
        if notes_c:
            lines.append("Creator notes:\n" + notes_c)
        parts.append("\n".join(lines))
    if facts.strip():
        parts.append("Established facts from the character's chats:\n" + facts.strip())
    if notes.strip():
        parts.append("His notes on lore to cover:\n" + notes.strip())
    user = "\n\n".join(parts) if parts else "(no source content)"
    system = LORE_GEN_SYSTEM.replace("{max_entries}", str(int(max_entries)))
    return [{"role": "system", "content": system},
            {"role": "user", "content": user}]


def parse_generated_entries(raw: str, max_entries: int = MAX_GEN_ENTRIES) -> tuple:
    """(uid-keyed entries dict, warnings list) from the LLM reply.

    Guards: JSON (json_repair fallback for fences/comma slips), keys at
    least MIN_KEY_LEN, non-empty content, ST order semantics kept, entry
    count capped. A key that only exists inside another entry's key list
    keeps its first entry — duplicates waste injection budget.
    """
    warnings = []
    text = (raw or "").strip()
    text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
    text = re.sub(r"\s*```$", "", text).strip()
    data = None
    try:
        data = json.loads(text)
    except Exception:
        try:
            data = json.loads(repair_json(text))
            warnings.append("repaired malformed JSON")
        except Exception:
            return {}, ["reply was not JSON"]
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list):
        return {}, ["reply had no entries list"]

    entries, seen_keys = {}, set()
    for e in data:
        if not isinstance(e, dict):
            continue
        if len(entries) >= max_entries:
            warnings.append(f"entry cap ({max_entries}) reached — extra entries dropped")
            break
        norm = _normalize_entry(len(entries), e)
        keys = [k for k in norm.get("key", [])
                if isinstance(k, str) and len(k.strip()) >= MIN_KEY_LEN]
        keys = [k.strip() for k in keys]
        if not keys:
            warnings.append("dropped entry with no usable keys: "
                            + (norm.get("comment") or "unnamed"))
            continue
        if not (norm.get("content") or "").strip():
            warnings.append("dropped entry with empty content: "
                            + (norm.get("comment") or "unnamed"))
            continue
        sig = tuple(sorted(k.lower() for k in keys))
        if sig in seen_keys:
            warnings.append("dropped duplicate key set: " + (norm.get("comment") or "unnamed"))
            continue
        seen_keys.add(sig)
        norm["key"] = keys
        norm["constant"] = False          # always-on lore belongs in the card
        norm["position"] = POSITION_AFTER_SYSTEM
        entries[str(len(entries))] = norm
    return entries, warnings


async def generate_lorebook_entries(card: dict, facts: str = "", notes: str = "",
                                    client=None, model: str = "",
                                    include_card: bool = True,
                                    extra_body=None,
                                    max_entries: int = MAX_GEN_ENTRIES) -> tuple:
    """(entries dict, warnings) — one LLM call writing the entry set."""
    messages = build_lorebook_gen_messages(card, facts, notes,
                                          include_card=include_card,
                                          max_entries=max_entries)
    raw = await _llm_chat(client, model, messages, max_tokens=3500,
                          temperature=0.5, extra_body=extra_body)
    return parse_generated_entries(raw, max_entries=max_entries)
