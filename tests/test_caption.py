"""MOSS-Image scene captioner tests.

The captioner replaced the old tag-soup prompt generator: MOSS-Image is
trained on captions of finished images and wants long English prose, not
comma-separated tags. Covers the system prompt's contract, the message
builder (window/character/persona/style-budget plumbing), session context
loading, and the response parser — whose old whole-text `if "SKIP" in raw`
check would have swallowed any caption containing "skipping".
"""
import unittest

import db
import imagegen


class TestCaptionSystemPrompt(unittest.TestCase):
    def test_specifies_finished_image_captions(self):
        sysp = imagegen.auto_img_system()
        self.assertIn("FINISHED IMAGES", sysp)
        self.assertIn("SKIP", sysp)
        self.assertIn("512 tokens", sysp)

    def test_old_tag_soup_spec_is_gone(self):
        sysp = imagegen.auto_img_system()
        self.assertNotIn("comma-separated", sysp)
        self.assertNotIn("under 80 words", sysp)
        self.assertNotIn('Prefer "anime style"', sysp)

    def test_covers_the_location_precedence(self):
        sysp = imagegen.auto_img_system()
        self.assertIn("precedence", sysp)
        self.assertIn("scenario", sysp)
        self.assertIn("generic", sysp)

    def test_word_target_filled_from_argument(self):
        sysp = imagegen.auto_img_system(180)
        self.assertIn("target 180 words", sysp)
        self.assertNotIn("{words}", sysp)

    def test_word_target_defaults_to_config(self):
        sysp = imagegen.auto_img_system()
        self.assertNotIn("{words}", sysp)
        self.assertIn(f"target {db.IMAGEGEN_CAPTION_WORDS} words", sysp)

    def test_stays_compact(self):
        # He rejects long drafts; his accepted shape is a ~300-word rule set.
        wc = len(imagegen.auto_img_system().split())
        self.assertLess(wc, 420, f"system prompt grew to {wc} words")


def _msgs(n=15):
    return [{"role": "user" if i % 2 == 0 else "character",
             "speaker": "" if i % 2 == 0 else "Ramlee",
             "content": f"msg-{i}"} for i in range(1, n + 1)]


class TestBuildCaptionMessages(unittest.TestCase):
    def test_window_trims_the_chat_slice(self):
        msgs = imagegen.build_caption_messages(
            _msgs(), window=5, characters_block="", persona_block="",
            style={}, word_target=200)
        user = msgs[1]["content"]
        self.assertIn(": msg-15", user)
        self.assertIn(": msg-11", user)
        self.assertNotIn(": msg-10", user)

    def test_roles_and_system_prompt(self):
        msgs = imagegen.build_caption_messages(
            _msgs(3), characters_block="", persona_block="", style={},
            word_target=200)
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        self.assertIn("target 200 words", msgs[0]["content"])
        self.assertIn("MOSS-Image caption, or SKIP", msgs[1]["content"])

    def test_character_and_persona_blocks_are_included(self):
        msgs = imagegen.build_caption_messages(
            _msgs(3),
            characters_block="- P. Ramlee: tall, batik shirt | scenario: coffee shop regular",
            persona_block="- Razif: average build, glasses",
            style={}, word_target=200)
        user = msgs[1]["content"]
        self.assertIn("Characters in the scene", user)
        self.assertIn("batik shirt", user)
        self.assertIn("coffee shop regular", user)
        self.assertIn("persona", user.lower())
        self.assertIn("average build", user)

    def test_style_budget_lists_only_nonempty_phrases(self):
        msgs = imagegen.build_caption_messages(
            _msgs(3), characters_block="", persona_block="",
            style={"medium": "watercolor illustration", "lighting": "",
                   "mood": "quiet melancholy"}, word_target=200)
        user = msgs[1]["content"]
        self.assertIn("Style budget", user)
        self.assertIn('medium="watercolor illustration"', user)
        self.assertIn('mood="quiet melancholy"', user)
        self.assertNotIn('lighting="', user)

    def test_no_budget_line_when_style_is_empty(self):
        msgs = imagegen.build_caption_messages(
            _msgs(3), characters_block="", persona_block="",
            style={"medium": "", "lighting": "", "mood": ""}, word_target=200)
        self.assertNotIn("Style budget", msgs[1]["content"])

    def test_empty_conversation_is_tolerated(self):
        msgs = imagegen.build_caption_messages(
            [], characters_block="", persona_block="", style={}, word_target=200)
        self.assertIn("(none)", msgs[1]["content"])


class TestCaptionSessionContext(unittest.TestCase):
    def test_missing_session_yields_empty_blocks(self):
        chars, persona = imagegen.caption_session_context(999999999)
        self.assertEqual((chars, persona), ("", ""))

    def test_no_session_yields_empty_blocks(self):
        self.assertEqual(imagegen.caption_session_context(None), ("", ""))
        self.assertEqual(imagegen.caption_session_context(0), ("", ""))

    def test_clip_limits_and_keeps_short_text(self):
        self.assertEqual(imagegen._clip("short text", 100), "short text")
        clipped = imagegen._clip("word " * 100, 50)
        self.assertLessEqual(len(clipped), 52)
        self.assertTrue(clipped.endswith("…"))


class TestParseCaption(unittest.TestCase):
    def test_plain_caption_passes_through(self):
        cap = "A woman reads by the window, late sun on the floor."
        self.assertEqual(imagegen.parse_caption_response(cap), cap)

    def test_skip_variants(self):
        for raw in ("SKIP", "skip", "SKIP.", "Skip\n", "  SKIP  "):
            self.assertIsNone(imagegen.parse_caption_response(raw), raw)

    def test_caption_containing_skipping_is_not_skip(self):
        # The old parser's `if "SKIP" in raw.upper()` returned None here.
        cap = "Skipping through the market, red dress swinging, laughing."
        self.assertEqual(imagegen.parse_caption_response(cap), cap)

    def test_old_prompt_prefix_still_accepted(self):
        self.assertEqual(
            imagegen.parse_caption_response("PROMPT: a cat on a mat"),
            "a cat on a mat")

    def test_r1_thinking_blocks_are_stripped(self):
        raw = "$$the user wants a cozy scene, let me think about light$$\n\nA cat asleep on a windowsill in warm light."
        self.assertEqual(
            imagegen.parse_caption_response(raw),
            "A cat asleep on a windowsill in warm light.")
        raw2 = "<thinking>cozy</thinking>\nA cat asleep on a windowsill."
        self.assertEqual(
            imagegen.parse_caption_response(raw2),
            "A cat asleep on a windowsill.")

    def test_leading_blanks_and_whitespace(self):
        self.assertEqual(
            imagegen.parse_caption_response("\n\n  A quiet room.  \n"),
            "A quiet room.")

    def test_empty_is_none(self):
        self.assertIsNone(imagegen.parse_caption_response(""))
        self.assertIsNone(imagegen.parse_caption_response(None))


if __name__ == "__main__":
    unittest.main()
