# KedaiKopi

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://www.apache.org/licenses/LICENSE-2.0)

A local web client for roleplaying with character cards — multi-character sessions, token-by-token streaming replies, keyword-triggered lorebooks, and a full card/persona authoring toolkit. Forked from [Character School](https://github.com/krazif/Character_School) as the pure roleplay edition: the school/analysis mode is gone, everything else stays.

![RP Mode](rp.png)

---

## Features

### Roleplay Sessions

- **1–4 characters + a persona** per session, persistent in SQLite and resumable from the sidebar; fork any session to branch a scene.
- **Turn routing**: auto (all characters respond) or directed (target one character — it gets full card detail while the others stay brief mentions, which prevents personality bleed).
- **Response length**: `short` / `moderate` / `long` / `flexible`. The style sets a **ceiling with headroom**, not a hard cut (short → 800 tokens, moderate → 1100 — sized above the word target so a reply that wants that length finishes on its own instead of being chopped mid-sentence). A reply that still reaches the ceiling is **flagged, never trimmed**: the message carries `truncated: true` and shows a `continue` action that extends it. The flag comes from the endpoint's own `finish_reason` — not a guess at the text.
- **Auto-continue**: a reply cut by the *global* budget continues itself inside the same bubble. A style-cap cut is never auto-continued — extending it would defeat the cap.

### Streaming Replies

- Character replies stream token-by-token — the bubble grows as the model generates instead of arriving in one lump.
- The leading `[CharacterName]:` prefix is held back while streaming (a continuation's re-stated header is held and stripped too), so the bubble shows exactly the text the stored message will show.
- Works against any OpenAI-compatible endpoint: if one rejects streaming parameters, the request falls back to a plain call and the reply still arrives.

### Lorebooks (World Info)

- **SillyTavern-compatible** lorebooks: keyword-triggered entries with primary/secondary keys, constant entries, insertion order, and per-entry position.
- Three positions, all real: *before system* (prepend to the system message), *after system* (append), *before chat* (its own message directly before the first user turn).
- ST insertion order honoured: constants first, then ascending `order` — a larger order sits closer to the chat and carries more impact.
- Attach any number of lorebooks per session from the scene bar; the console shows exactly what was injected.

### Character Cards

- Supports **V1** (flat JSON), **V2** (`chara_card_v2`), and **V3** (`chara_card_v3`); V3 field aliases and content arrays handled automatically.
- Card library in the sidebar: upload (JSON or PNG), edit in-app (✏️), download as PNG or JSON, delete.
- **PNG card import/export** — SillyTavern-compatible format with base64-encoded JSON in `chara`/`ccv3` tEXt chunks.
- **AI card generation** from a concept with hints (name, age, personality, scenario, appearance, NSFW toggle); the generation calls are visible in the console.

### Prompt Stack

- Per-session prompt stack builder: system prompt, head/tail windows, summary chunks, custom blocks — with a token estimate per block.
- **Configurable summarization** — summary window and raw window settings manage context length; summaries update as scenes progress.

### Persona System

- Personas are counterparties with physical traits injected into character prompts.
- 6 starter personas included; create and edit personas in-app (Persona → ✏️ Edit in the session setup).

### Scene Images

- Generate scene images via ComfyUI (workflow selectable in Settings), insert into chat or set as session background, regenerate with seed.

### UI Niceties

- `*text*` renders italic, `"text"` renders bold in chat messages.
- LLM console panel: raw, unformatted prompt/response inspector — fully verbose, no truncation — including lorebook injections and auto-continue events.
- Chat backgrounds (upload or URL, per-session persistence), dark theme throughout, swipes on every message (alternatives side by side with left/right arrows).
- **Settings** editable in-app (saved to `config.jsonc`); **Danger Zone** resets the database and VACUUMs.

---

## Installation

### Prerequisites

- Python 3.11+
- Any OpenAI-compatible LLM API endpoint (OpenRouter, a local server, etc.)

### 1. Clone the repo

```bash
git clone https://github.com/krazif/KedaiKopi.git
cd KedaiKopi
```

### 2. (Optional) Create a virtual environment

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## How to Run

```bash
python main.py
```

Or with uvicorn directly:

```bash
python -m uvicorn main:app --host 0.0.0.0 --port 7864
```

The app starts on `http://0.0.0.0:7864` by default. Character School, if also running, holds 7862 — the two coexist side by side. Open `http://localhost:7864` in your browser.

> **Note:** The server starts even without API keys configured. Go to the Settings page in the UI to add your LLM API keys.

### Configuration

Settings live in `config.jsonc` (auto-created on first run; JSONC — comments allowed). Edit in-app via Settings or by hand:

```jsonc
{
  // Chat endpoint — drives character responses
  "chat": {
    "base_url": "https://openrouter.ai/api/v1",
    "api_key": "your-api-key",
    "model": "deepseek/deepseek-v4-flash",
    "temperature": 0.8,
    "max_tokens": 2000
  },
  "server": {
    "host": "0.0.0.0",
    "port": 7864
  },
  "paths": {
    "characters_dir": null,  // null = defaults to ./characters
    "personas_dir": null     // null = defaults to ./personas
  }
}
```

All settings can also be overridden via environment variables with the `KEDAIKOPI_` prefix:

| Env Var | Description |
|---------|-------------|
| `KEDAIKOPI_CHAT_BASE_URL` | Chat LLM API base URL |
| `KEDAIKOPI_CHAT_API_KEY` | Chat LLM API key |
| `KEDAIKOPI_CHAT_MODEL` | Chat LLM model name |
| `KEDAIKOPI_HOST` | Server bind address |
| `KEDAIKOPI_PORT` | Server port |

---

## Tests

Unit tests for the streaming layer, the response-style ceilings, and the lorebook engine (keyword matching, ST insertion order, placement), plus an end-to-end check that starts a mock LLM and a second app instance (throwaway copy — the real database is never touched) and drives the real WebSocket protocol:

```bash
python -m unittest discover -s tests      # streaming / length / lorebook units
python tests/e2e_stream_check.py          # A–E over /ws/rp: streaming, prefix,
                                          # auto-continue, style ceiling, fallback
```

`tests/mock_llm.py` is a standalone OpenAI-compatible endpoint (streamed, word by word) that can also be run by hand for poking at the UI.

## Project Layout

```
KedaiKopi/
├── main.py                # FastAPI app entry point (routers + static mount)
├── db.py                  # Backward-compat shim (config + database)
├── config.py              # JSONC config + LLM clients
├── database.py            # SQLite data layer (RP sessions/messages/characters)
├── engine.py              # Pure logic (cards, personas, prompts, streaming, PNG)
├── rp.py                  # RP routes + WebSocket + config API
├── library.py             # Card/persona library + AI card generation routes
├── lorebook.py            # World Info: matching, ST order, placement, injection
├── imagegen.py            # ComfyUI scene image generation
├── config.jsonc           # Configuration (auto-created, editable in-app)
├── kedai.db               # SQLite database (sessions, messages) — gitignored
├── tests/                 # unit tests, mock LLM, end-to-end WS check
├── LICENSE                # Apache 2.0
├── NOTICE                 # Attribution notice
├── README.md              # This file
├── characters/            # Character card JSON/PNG files
├── personas/              # Persona JSON files
├── lorebooks/             # Lorebook (World Info) JSON files
└── static/
    ├── index.html         # Frontend shell (inline CSS)
    └── js/                # core / cards / ui / rp / sessions / stack /
                           # lorebook / settings / messages / imagegen
```

---

## Tech Stack

- **Backend**: Python, FastAPI, uvicorn, SQLite
- **Frontend**: HTML/CSS/JS (no build step, no framework)
- **LLM**: Any OpenAI-compatible API
- **Image handling**: Pillow (PNG card import/export)

---

## Provenance

KedaiKopi is a fork of [Character School](https://github.com/krazif/Character_School) and keeps its git history — `git diff Character_School` remains available for syncing. Bugs in shared code are fixed in both repos.

## License

Apache License 2.0 — see [LICENSE](LICENSE) for details.

Copyright 2026 M. Razif Hussin
