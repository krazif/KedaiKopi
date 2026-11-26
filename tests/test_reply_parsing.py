"""Reply-shape parsing: the stream and the stored message must agree.

Razif: "when i pick flexible (dynamic) length output, i saw the output
message nicely long, suddenly i saw it cutted and become 40~50 words" —
reproduced on a throwaway: a reply containing a second `[Name]:` marker
(streamed in full) was stored as its FIRST segment only, the final
message replacing the long stream bubble at half its length.

Two shapes cause it:
  A. the same speaker re-states its header mid-reply (a fresh-reply twin
     of the continuation case engine.maybe_auto_continue already strips)
  B. a genuinely different speaker's block after the first
"""
import unittest

import engine


class TestParseSegments(unittest.TestCase):
    NAMES = {"farah.json": "Farah", "lisa.json": "Lisa"}
    ORDER = ["farah.json", "lisa.json"]

    def parse(self, raw):
        return engine.parse_rp_response(raw, self.NAMES, self.ORDER)

    def test_restated_header_merges_into_one_segment(self):
        # shape A: the tail is a continuation of the SAME turn — nothing lost
        segs = self.parse("[Farah]: She set the cup down and waited.\n[Farah]: Then the door opened.")
        self.assertEqual(len(segs), 1)
        self.assertIn("She set the cup down", segs[0]["content"])
        self.assertIn("Then the door opened", segs[0]["content"])
        self.assertEqual(segs[0]["name"], "Farah")

    def test_restated_header_case_insensitive(self):
        segs = self.parse("[farah]: part one\n[FARAH]: part two")
        self.assertEqual(len(segs), 1)
        self.assertIn("part two", segs[0]["content"])

    def test_different_speakers_stay_separate(self):
        segs = self.parse("[Farah]: her line\n[Lisa]: her line")
        self.assertEqual(len(segs), 2)
        self.assertEqual([s["name"] for s in segs], ["Farah", "Lisa"])

    def test_plain_prose_still_parses_to_nothing(self):
        self.assertEqual(self.parse("no markers here at all"), [])


class TestAutoModeSegments(unittest.TestCase):
    """What the auto mode stores after parsing. The stream showed the
    whole reply — the store keeps as much of it as is safe to keep:
    never the persona's lines (the model must not speak for the user),
    never late marker noise, every real session character's block."""

    def test_persona_blocks_are_never_kept(self):
        parsed = [{"filename": "farah.json", "name": "Farah", "content": "a"},
                  {"filename": None, "name": "Razif", "content": "user line"}]
        kept = engine.auto_mode_segments(parsed, persona_name="Razif")
        self.assertEqual([s["name"] for s in kept], ["Farah"])

    def test_late_unknown_block_is_kept_no_silent_loss(self):
        # an out-of-session speaker's tail is still story the stream showed —
        # dropping it is the bug this module exists to prevent
        parsed = [{"filename": "farah.json", "name": "Farah", "content": "a"},
                  {"filename": None, "name": "Lisa", "content": "the tail"}]
        kept = engine.auto_mode_segments(parsed, persona_name="Razif")
        self.assertEqual([s["name"] for s in kept], ["Farah", "Lisa"])

    def test_real_other_character_block_is_kept(self):
        parsed = [{"filename": "farah.json", "name": "Farah", "content": "a"},
                  {"filename": "lisa.json", "name": "Lisa", "content": "b"}]
        kept = engine.auto_mode_segments(parsed, persona_name="Razif")
        self.assertEqual([s["name"] for s in kept], ["Farah", "Lisa"])

    def test_join_mode_merges_kept_segments_for_one_message(self):
        parsed = [{"filename": "farah.json", "name": "Farah", "content": "a"},
                  {"filename": "lisa.json", "name": "Lisa", "content": "b"}]
        kept = engine.auto_mode_segments(parsed, persona_name="Razif", join=True)
        self.assertEqual(len(kept), 1)
        self.assertIn("a", kept[0]["content"])
        self.assertIn("b", kept[0]["content"])

    def test_everything_dropped_falls_back_to_the_first(self):
        parsed = [{"filename": None, "name": "Razif", "content": "only block"}]
        kept = engine.auto_mode_segments(parsed, persona_name="Razif")
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0]["content"], "only block")


if __name__ == "__main__":
    unittest.main()


class TestDialogueSplit(unittest.TestCase):
    """Speaker-attributed QUOTED dialogue gets its own bubble per speaker.

    Razif's sample: one reply carrying Lisa's, Farah's and Aqil's spoken
    lines inside the author's bubble. He chose "separate bubbles per
    speaker": narration stays with the reply's author, the scene's order
    is preserved. Quoted speech is the discriminator — the PHONE TEXTS
    protocol says a text carries no quotes, so bare `Name: message`
    lines stay put (diegetic texts keep their chip + phone extraction)."""

    NAMES = {"farah.json": "Farah", "lisa.json": "Lisa Surihani"}

    def split(self, content):
        parsed = [{"filename": "yusry.json", "name": "Yusry", "content": content}]
        return engine.split_dialogue_messages(parsed, self.NAMES, persona_name="Razif")

    def test_quoted_dialogue_splits_to_its_speaker(self):
        msgs = self.split(
            "He unplugs, wiping his neck.\n\n"
            'Lisa: "Half gone. Blame your daughter."\n\n'
            "She slides off the bench.")
        self.assertEqual([m["name"] for m in msgs], ["Yusry", "Lisa", "Yusry"])
        self.assertIn("Half gone", msgs[1]["content"])
        self.assertNotIn("Lisa:", msgs[1]["content"])       # label carries it
        self.assertIn("She slides", msgs[2]["content"])     # order preserved

    def test_action_tagged_speaker_name_is_cleaned(self):
        msgs = self.split('Aqil, mouth full: "Worth it."')
        self.assertEqual([m["name"] for m in msgs], ["Aqil"])
        self.assertEqual(msgs[0]["content"], '"Worth it."')

    def test_packed_attributions_in_one_paragraph_all_split(self):
        msgs = self.split(
            'Lisa: "Half gone."\nFarah: "Blame Aqil!"\nAqil, mouth full: "Worth it."')
        self.assertEqual([m["name"] for m in msgs], ["Lisa", "Farah", "Aqil"])

    def test_multi_line_speech_stays_with_its_speaker(self):
        msgs = self.split('Lisa: "Half gone.\nBlame your daughter."')
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["name"], "Lisa")
        self.assertIn("Blame your daughter", msgs[0]["content"])

    def test_narration_after_a_closed_quote_returns_to_the_author(self):
        msgs = self.split('Aqil: "Worth it."\nFarah slides off the bench.')
        self.assertEqual([m["name"] for m in msgs], ["Aqil", "Yusry"])

    def test_unquoted_phone_text_stays_with_the_author(self):
        msgs = self.split("She checks her phone.\nLisa: leaving in 20\nShe sighs.")
        self.assertEqual([m["name"] for m in msgs], ["Yusry"])
        self.assertIn("Lisa: leaving in 20", msgs[0]["content"])

    def test_persona_speech_folds_back_never_a_fake_user_bubble(self):
        msgs = self.split('Razif: "ok lah, coming"')
        self.assertEqual([m["name"] for m in msgs], ["Yusry"])
        self.assertIn("ok lah, coming", msgs[0]["content"])

    def test_quoted_special_labels_do_not_split(self):
        msgs = self.split('Thoughts: "weird, that look"')
        self.assertEqual([m["name"] for m in msgs], ["Yusry"])

    def test_multi_word_speaker_name_is_kept(self):
        msgs = self.split('Lisa Surihani: "Half gone."')
        self.assertEqual(msgs[0]["name"], "Lisa Surihani")

    def test_prose_colon_sentence_is_not_a_speaker(self):
        msgs = self.split('He said: "something odd" and kept walking.')
        self.assertEqual([m["name"] for m in msgs], ["Yusry"])

    def test_plain_narration_is_unchanged(self):
        msgs = self.split("Just narration, no dialogue at all.")
        self.assertEqual(len(msgs), 1)
        self.assertEqual(msgs[0]["content"], "Just narration, no dialogue at all.")
