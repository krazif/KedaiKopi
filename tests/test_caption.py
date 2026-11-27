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

    def test_nsfw_is_described_not_sanitized(self):
        # "if it is naked, should be naked" — the old dignity rule re-clothed
        # NSFW scenes; the captioner must follow the chat's state of dress.
        sysp = imagegen.auto_img_system()
        self.assertNotIn("clothing covers anatomy", sysp)
        self.assertNotIn("no nudity", sysp)
        self.assertIn("re-clothed", sysp)
        self.assertIn("never the card", sysp)   # chat overrides card outfit

    def test_minors_refusal_still_present(self):
        # The one refusal that stays regardless of uncensoring.
        self.assertIn("Sexualized minors are refused", imagegen.auto_img_system())


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
        self.assertIn("scene caption, or SKIP", msgs[1]["content"])

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


class TestCaptionPov(unittest.TestCase):
    """POV option: the image is seen from the user's eyes. Field ask:
    'i want to have an option for pov, means from the pov of the user' —
    a standing per-session setting both Autogen and the auto-images honor."""

    MSGS = [{"role": "character", "speaker": "Farah", "content": "She waves from the porch."}]

    def test_pov_user_adds_a_fixed_camera_block(self):
        msgs = imagegen.build_caption_messages(
            self.MSGS, characters_block="- Farah: dark hair",
            persona_block="- Razif: tall, short hair", pov="user")
        user = msgs[1]["content"]
        self.assertIn("first-person POV", user)
        self.assertIn("not visible in frame", user)
        self.assertIn("Razif", user)
        self.assertIn("faces the camera", user)

    def test_pov_user_reframes_the_persona_block(self):
        msgs = imagegen.build_caption_messages(
            self.MSGS, persona_block="- Razif: tall", pov="user")
        user = msgs[1]["content"]
        # the persona is the CAMERA, not a subject
        self.assertIn("camera", user.lower())
        self.assertNotIn("also visible if the scene shows it", user)

    def test_default_has_no_camera_block(self):
        msgs = imagegen.build_caption_messages(
            self.MSGS, persona_block="- Razif: tall")
        self.assertNotIn("first-person POV", msgs[1]["content"])
        self.assertIn("also visible if the scene shows it", msgs[1]["content"])

    def test_pov_falls_back_to_the_session_setting(self):
        # no explicit pov: the session's image_pov decides (autogen path)
        real = imagegen.db.db_rp_get_session
        imagegen.db.db_rp_get_session = lambda sid: {"image_pov": "user",
                                                    "characters": [], "persona_filename": None}
        try:
            msgs = imagegen.build_caption_messages(self.MSGS, session_id=7,
                                                   characters_block="- Farah: dark hair",
                                                   persona_block="- Razif: tall")
        finally:
            imagegen.db.db_rp_get_session = real
        self.assertIn("first-person POV", msgs[1]["content"])

    def test_explicit_pov_overrides_the_session(self):
        real = imagegen.db.db_rp_get_session
        imagegen.db.db_rp_get_session = lambda sid: {"image_pov": "user",
                                                    "characters": [], "persona_filename": None}
        try:
            msgs = imagegen.build_caption_messages(self.MSGS, session_id=7,
                                                   persona_block="- Razif: tall", pov="auto")
        finally:
            imagegen.db.db_rp_get_session = real
        self.assertNotIn("first-person POV", msgs[1]["content"])


class TestCaptionHabit(unittest.TestCase):
    """The card's USUAL LOOK must reach the captioner: what the character
    habitually wears/keeps about them lives in the character book and the
    example dialogue, not only the description. Field ask: 'did it check
    the character card? something the character usually wear'."""

    @staticmethod
    def _fake_db_session():
        return {"characters": [{"card_filename": "x.json", "char_name": "Farah",
                                "display_order": 0}],
                "persona_filename": None}

    @staticmethod
    def _fake_card():
        return {"data": {
            "name": "Farah",
            "description": "dark hair, sharp eyes",
            "scenario": "a family house",
            "mes_example": "{{char}}: *pushes her glasses up* Hello there.",
            "character_book": {"entries": [
                {"keys": ["outfit"], "content": "She usually wears a floral kebaya and a green tudung.", "enabled": True},
                {"keys": ["disabled one"], "content": "NEVER RENDER ME", "enabled": False},
            ]},
        }}

    def _context(self, card=None):
        real_sess, real_load = imagegen.db.db_rp_get_session, imagegen.engine.load_card
        imagegen.db.db_rp_get_session = lambda sid: self._fake_db_session()
        imagegen.engine.load_card = lambda fn: card or self._fake_card()
        try:
            return imagegen.caption_session_context(7)
        finally:
            imagegen.db.db_rp_get_session, imagegen.engine.load_card = real_sess, real_load

    def test_habit_from_character_book_and_mes_example(self):
        block, _ = self._context()
        self.assertIn("usually wears a floral kebaya", block)
        self.assertIn("pushes her glasses up", block)

    def test_disabled_book_entries_are_skipped(self):
        block, _ = self._context()
        self.assertNotIn("NEVER RENDER ME", block)

    def test_habit_text_is_flattened_and_bounded(self):
        card = self._fake_card()
        card["data"]["character_book"]["entries"] = [
            {"keys": ["k"], "content": "line one\nline two", "enabled": True}] + [
            {"keys": [f"k{i}"], "content": "x" * 250, "enabled": True} for i in range(20)]
        block, _ = self._context(card)
        self.assertIn("line one line two", block)          # no newline breaks the list
        self.assertNotIn("\n", block)
        self.assertLess(len(block), 3000)                   # budget holds

    def test_top_level_v2_character_book_also_read(self):
        card = self._fake_card()
        book = card["data"].pop("character_book")
        card["character_book"] = book                       # V2 placement
        block, _ = self._context(card)
        self.assertIn("usually wears a floral kebaya", block)


class TestClothingPrecedence(unittest.TestCase):
    """chat > card habit > generic — the NSFW win (never re-cloth from the
    card) must survive, scoped to when the chat actually states clothing."""

    def test_precedence_is_spelled_out(self):
        sysp = imagegen.auto_img_system()
        self.assertIn("when the chat is silent about clothing", sysp)
        self.assertIn("usual outfit", sysp)

    def test_chat_still_beats_the_card(self):
        sysp = imagegen.auto_img_system()
        self.assertIn("never the card", sysp)     # existing NSFW contract phrase
        self.assertIn("re-clothed", sysp)


class TestCaptionTokenCap(unittest.TestCase):
    """Selectable output token ceiling (512/1024/2048/4096). Field ask:
    'can we have the hard tokens ceiling can be selected' — a standing
    per-session setting like image_pov, default 512."""

    MSGS = [{"role": "character", "speaker": "Farah", "content": "She waves."}]

    def cap_of(self, **kw):
        msgs = imagegen.build_caption_messages(
            self.MSGS, characters_block="- Farah: dark hair", **kw)
        return msgs[0]["content"]

    def test_default_ceiling_is_512(self):
        self.assertIn("hard ceiling 512 tokens", self.cap_of())

    def test_explicit_cap_fills_the_slot(self):
        content = self.cap_of(token_cap=2048)
        self.assertIn("hard ceiling 2048 tokens", content)
        self.assertNotIn("hard ceiling 512", content)

    def test_cap_falls_back_to_the_session_setting(self):
        real = imagegen.db.db_rp_get_session
        imagegen.db.db_rp_get_session = lambda sid: {"image_token_cap": "4096"}
        try:
            self.assertIn("hard ceiling 4096 tokens", self.cap_of(session_id=7))
        finally:
            imagegen.db.db_rp_get_session = real

    def test_explicit_cap_wins_over_the_session_setting(self):
        real = imagegen.db.db_rp_get_session
        imagegen.db.db_rp_get_session = lambda sid: {"image_token_cap": "4096"}
        try:
            self.assertIn("hard ceiling 1024 tokens",
                          self.cap_of(session_id=7, token_cap=1024))
        finally:
            imagegen.db.db_rp_get_session = real

    def test_unknown_cap_falls_back_to_512(self):
        self.assertIn("hard ceiling 512 tokens", self.cap_of(token_cap=777))

    def test_rule_ten_keeps_the_ceiling_slot(self):
        self.assertIn("hard ceiling {tokens} tokens", imagegen.AUTO_IMG_SYSTEM)
