"""Texting style — the system-prompt directive and its token ceiling.

    python3 -m unittest discover -s tests

The directive is prompt text that must not drift: asserted byte-for-byte.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine


# The one authoritative wording — kept in engine._STYLE_LENGTH_NOTES.
TEXTING_DIRECTIVE = (
    "[IMPORTANT — Texting mode: you are sending text messages, not writing "
    "prose. Reply ONLY with the text inside the bubbles — no narration, no inner monologue, no "
    "action asterisks, no scene description, no speaker tags. Write like a "
    "real texter: lowercase, informal, fragments, abbreviations, ellipses, "
    "emoji. Keep every bubble to 1-3 short lines; split a thought across "
    "bubbles by putting a line containing only ··· between them. Total under "
    "150 words. Even if earlier messages read as prose, keep texting. Never "
    "end on handover cues; finish naturally.]"
)


class TextingInstructionTests(unittest.TestCase):
    def test_texting_directive_wording_is_exact(self):
        # Byte-for-byte: substring checks miss the parts you didn't think to
        # check, and this text goes verbatim into every texting-mode prompt.
        self.assertEqual(engine.response_style_instruction("texting"),
                         TEXTING_DIRECTIVE)

    def test_texting_prompt_suppresses_inner_monologue(self):
        # his sessions run with the Thoughts toggle ON — texting mode must
        # not carry the "mandatory in every response" directive
        card = {"data": {"name": "Lisa", "description": "A cook.", "personality": "warm."}}
        persona = {"name": "Razif"}
        texting = engine.build_rp_system_prompt([card], persona, "texting",
                                                inner_monologue=True)
        rp = engine.build_rp_system_prompt([card], persona, "moderate",
                                           inner_monologue=True)
        self.assertNotIn("INNER MONOLOGUE: ON", texting)
        self.assertIn("INNER MONOLOGUE: ON", rp)   # narration keeps it

    def test_texting_ceiling_sits_above_the_word_target(self):
        # Under 150 words ≈ 230 tokens at 1.44–1.59 tok/word; bursts carry
        # separator lines, so the ceiling matches 'short' (800) — generous
        # enough never to bite a natural reply, tight enough to cut a runaway.
        self.assertEqual(engine.response_style_max_tokens("texting", 2000), 800)
        self.assertGreater(800, 150 * 1.59)

    def test_texting_and_short_are_distinct_from_long_and_flexible(self):
        # long/flexible keep the global budget; texting is capped like short.
        self.assertEqual(engine.response_style_max_tokens("long", 2000), 2000)
        self.assertEqual(engine.response_style_max_tokens("flexible", 2000), 2000)


if __name__ == "__main__":
    unittest.main()
