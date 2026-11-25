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

    def test_a_text_is_answered_with_texts(self):
        # Razif's field report: he texted and got narration back in the chat.
        # A text must be answered in kind — texts, not prose.
        p = rp_prompt("moderate")
        self.assertIn("Answer in kind: if the user's latest message is a text", p)
        self.assertIn("reply with one or more `Name: message` lines of your own", p)

    def test_rule_stays_out_of_texting_mode(self):
        # texting mode's directive owns the format; a competing rule would
        # tell the model to prefix `Name:` lines it must write bare.
        p = rp_prompt("texting")
        self.assertNotIn("PHONE TEXTS", p)


class TextingReminderTests(unittest.TestCase):
    """The per-reply answer-in-kind reminder (author's-note position).

    Field evidence: the system-prompt rule alone did not make the model
    answer a text with a text — but typing @name DID, because it sat in
    the final user message. The reminder rides that proven position.
    """

    @staticmethod
    def _msgs(last_user_content):
        return [{"role": "system", "content": "sys"},
                {"role": "user", "content": last_user_content}]

    def test_fires_when_the_last_user_message_is_a_text(self):
        note = engine.texting_reminder_for_reply(
            self._msgs("You: on my way"), "moderate", ["You", "User", "Farah"])
        self.assertIsNotNone(note)
        self.assertIn("Reply ONLY with text lines", note)
        # a concrete example at the generation point — imitation beats instruction
        self.assertIn("`Farah: on my way`", note)
        # no escape hatch: the phone input asked for a text, it gets a text
        self.assertNotIn("Narrate only if", note)

    def test_stays_silent_for_narration(self):
        # a prose message must never be told to answer with texts
        self.assertIsNone(engine.texting_reminder_for_reply(
            self._msgs("I walk in and close the door."), "moderate", ["You"]))

    def test_stays_silent_in_texting_mode(self):
        # texting mode always texts — no competing note
        self.assertIsNone(engine.texting_reminder_for_reply(
            self._msgs("You: on my way"), "texting", ["You"]))

    def test_matches_any_known_sender_case_insensitively(self):
        note = engine.texting_reminder_for_reply(
            self._msgs("farah: you there?"), "moderate", ["Farah"])
        self.assertIsNotNone(note)


class NameAliasTests(unittest.TestCase):
    """Field evidence: the card says "Lisa Surihani", the model writes
    `Lisa:` — exact-match extraction missed the reply entirely (it sat
    in the chat as a plain row, absent from the phone)."""

    def test_multi_word_names_expand_to_their_tokens(self):
        aliases = engine.expand_name_aliases(["Lisa Surihani", "Farah"])
        self.assertIn("Lisa", aliases)
        self.assertIn("Surihani", aliases)
        self.assertIn("Lisa Surihani", aliases)   # canonical kept
        self.assertIn("Farah", aliases)           # single-word untouched

    def test_reminder_matches_the_short_form(self):
        # a user line written with a persona's first token still counts
        note = engine.texting_reminder_for_reply(
            [{"role": "user", "content": "Razif: on my way"}],
            "moderate", ["M. Razif Hussin", "You", "User"])
        self.assertIsNotNone(note)

    def test_example_uses_the_natural_short_form(self):
        # model the writing style models actually use
        note = engine.texting_reminder_for_reply(
            [{"role": "user", "content": "You: on my way"}],
            "moderate", ["Lisa Surihani", "You", "User"])
        self.assertIn("`Lisa: on my way`", note)


class PerReplyNoteTests(unittest.TestCase):
    """Exactly ONE note rides the final user turn — the field regression
    appended the answer-in-kind reminder NEXT TO the length note, so the
    model got "150-300 words" and "no narration" at the same moment and
    chose prose."""

    @staticmethod
    def _msgs(last_user_content):
        return [{"role": "system", "content": "sys"},
                {"role": "user", "content": last_user_content}]

    def test_a_text_gets_the_reminder_and_never_the_length_note(self):
        note = engine.per_reply_note(self._msgs("You: on my way"), "moderate",
                                     ["Farah", "You", "User"], ["some old prose reply"])
        self.assertIsNotNone(note)
        self.assertIn("was a text", note)
        self.assertNotIn("150", note)          # the contradiction, gone
        self.assertNotIn("This reply stays", note)

    def test_narration_keeps_the_length_note(self):
        note = engine.per_reply_note(self._msgs("I walk in."), "moderate",
                                     ["Farah"], ["some old prose reply"])
        self.assertIn("150 and 300", note)

    def test_texting_mode_gets_no_note_at_all(self):
        self.assertIsNone(engine.per_reply_note(self._msgs("You: hi"), "texting",
                                               ["Farah", "You", "User"], None))

    def test_flexible_narration_still_gets_no_note(self):
        self.assertIsNone(engine.per_reply_note(self._msgs("I walk in."), "flexible",
                                               ["Farah"], None))


if __name__ == "__main__":
    unittest.main()
