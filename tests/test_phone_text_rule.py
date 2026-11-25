"""The phone-text protocol line in the RP system prompt.

    python3 -m unittest discover -s tests

Texts are identified by their line format (`Name: message`), so the rule
that teaches the model the format must be byte-stable — and must stay out
of texting mode, where the style directive owns the format alone.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import engine


def rp_prompt(style):
    card = {"data": {"name": "Lisa", "description": "A cook.", "personality": "warm."}}
    persona = {"name": "Razif"}
    return engine.build_rp_system_prompt([card], persona, style)


class PhoneTextRuleTests(unittest.TestCase):
    def test_rule_present_for_normal_roleplay(self):
        p = rp_prompt("moderate")
        self.assertIn("PHONE TEXTS: when a character sends a text message", p)
        # the worked example is the contract the extraction parser matches
        self.assertIn("`Lisa: leaving in twenty minutes`", p)

    def test_text_line_holds_the_message_only(self):
        # no narration inside a text — the line is the message and nothing else
        p = rp_prompt("moderate")
        self.assertIn("no narration, no actions, no stage directions", p)

    def test_a_reply_may_be_texts_only(self):
        # the model decides to text: allowed to answer the phone with no prose
        p = rp_prompt("moderate")
        self.assertIn("A reply may be one or more of these lines with no narration at all", p)

    def test_rule_stays_out_of_texting_mode(self):
        # texting mode's directive owns the format; a competing rule would
        # tell the model to prefix `Name:` lines it must write bare.
        p = rp_prompt("texting")
        self.assertNotIn("PHONE TEXTS", p)


if __name__ == "__main__":
    unittest.main()
