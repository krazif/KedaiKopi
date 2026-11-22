"""Venice AI extra_body tests.

Venice (api.venice.ai) validates ChatCompletionRequest with
additionalProperties:false — a top-level `enable_thinking` gets a 400
"Invalid request parameters" (probed live 2026-11-21). With the Venice
tick on, build_extra_body must emit ONLY venice-accepted fields.
"""
import unittest

import engine


class TestVeniceExtraBody(unittest.TestCase):
    def test_venice_replaces_enable_thinking(self):
        # The live-probed 400 case: {"enable_thinking": true} must not appear.
        eb = engine.build_extra_body("glm-5-3-flash-uncensored", True, venice=True,
                                     venice_system_prompt=False)
        self.assertNotIn("enable_thinking", eb)
        self.assertNotIn("reasoning_effort", eb)
        vp = eb["venice_parameters"]
        self.assertIs(vp["include_venice_system_prompt"], False)
        self.assertIs(vp["strip_thinking_response"], True)

    def test_thinking_allowed_leaves_disable_thinking_unset(self):
        vp = engine.build_extra_body("m", True, venice=True)["venice_parameters"]
        self.assertNotIn("disable_thinking", vp)  # default is off anyway

    def test_thinking_off_maps_to_disable_thinking(self):
        vp = engine.build_extra_body("m", False, venice=True)["venice_parameters"]
        self.assertIs(vp["disable_thinking"], True)

    def test_custom_parameters_override_defaults(self):
        eb = engine.build_extra_body(
            "m", True, venice=True,
            venice_parameters={"include_venice_system_prompt": True,
                               "enable_web_search": "off"})
        vp = eb["venice_parameters"]
        self.assertIs(vp["include_venice_system_prompt"], True)   # overridden
        self.assertEqual(vp["enable_web_search"], "off")          # passthrough
        self.assertIs(vp["strip_thinking_response"], True)        # default kept

    def test_none_values_in_custom_parameters_are_skipped(self):
        vp = engine.build_extra_body(
            "m", True, venice=True,
            venice_parameters={"enable_web_search": None})["venice_parameters"]
        self.assertNotIn("enable_web_search", vp)

    def test_venice_tick_wins_over_gemma_branch(self):
        # Endpoint is Venice even if the model name matches the local Gemma
        # pattern — only Venice-accepted fields may be sent.
        eb = engine.build_extra_body("gemma-3-27b-it", False, venice=True)
        self.assertIn("venice_parameters", eb)
        self.assertNotIn("reasoning_effort", eb)

    def test_non_venice_behaviour_unchanged(self):
        self.assertEqual(engine.build_extra_body("deepseek-v4", True, venice=False),
                         {"enable_thinking": True})
        self.assertEqual(engine.build_extra_body("deepseek-v4", False, venice=False),
                         {"enable_thinking": False})
        self.assertEqual(engine.build_extra_body("gemma-3-27b-it", False, venice=False),
                         {"reasoning_effort": "none"})
        self.assertEqual(engine.build_extra_body("gemma-3-27b-it", True, venice=False), {})

    def test_empty_custom_parameters_still_yields_defaults(self):
        eb = engine.build_extra_body("m", True, venice=True, venice_parameters={})
        self.assertIn("venice_parameters", eb)


class TestVeniceReasoningControls(unittest.TestCase):
    """reasoning.enabled / reasoning.effort — Venice's documented controls.

    Docs rule: reasoning.enabled is IGNORED when an effort is set, so the
    off case must never carry an effort alongside it.
    """

    def test_thinking_off_uses_both_off_switches(self):
        eb = engine.build_extra_body("m", False, venice=True,
                                     reasoning_effort="auto")
        self.assertEqual(eb["reasoning"], {"enabled": False})
        self.assertIs(eb["venice_parameters"]["disable_thinking"], True)
        self.assertNotIn("effort", eb["reasoning"])

    def test_effort_level_sent_when_thinking_is_on(self):
        eb = engine.build_extra_body("m", True, venice=True,
                                     reasoning_effort="high")
        self.assertEqual(eb["reasoning"], {"effort": "high"})
        self.assertNotIn("disable_thinking", eb["venice_parameters"])

    def test_auto_and_empty_effort_send_no_reasoning_key(self):
        for v in ("auto", "", "  "):
            eb = engine.build_extra_body("m", True, venice=True,
                                         reasoning_effort=v)
            self.assertNotIn("reasoning", eb, repr(v))

    def test_every_documented_level_is_accepted(self):
        for level in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
            eb = engine.build_extra_body("m", True, venice=True,
                                         reasoning_effort=level)
            self.assertEqual(eb["reasoning"], {"effort": level}, level)

    def test_thinking_off_wins_over_a_set_effort(self):
        eb = engine.build_extra_body("m", False, venice=True,
                                     reasoning_effort="high")
        self.assertEqual(eb["reasoning"], {"enabled": False})

    def test_invalid_effort_is_ignored(self):
        eb = engine.build_extra_body("m", True, venice=True,
                                     reasoning_effort="turbo")
        self.assertNotIn("reasoning", eb)

    def test_effort_never_leaks_when_venice_is_off(self):
        eb = engine.build_extra_body("deepseek-v4", True, venice=False,
                                     reasoning_effort="high")
        self.assertEqual(eb, {"enable_thinking": True})

    def test_explicit_args_ignore_the_config_fallback(self):
        # Deterministic regardless of what config.jsonc holds.
        eb = engine.build_extra_body("m", True, venice=True,
                                     venice_parameters={},
                                     reasoning_effort="medium")
        self.assertEqual(eb["reasoning"], {"effort": "medium"})


class TestVeniceSystemPromptTick(unittest.TestCase):
    """include_venice_system_prompt — the Settings tick maps to it; a
    hand-edited venice_parameters dict still wins (merge-over contract)."""

    def test_tick_off_keeps_venice_preamble_out(self):
        vp = engine.build_extra_body("m", True, venice=True,
                                     venice_system_prompt=False)["venice_parameters"]
        self.assertIs(vp["include_venice_system_prompt"], False)

    def test_tick_on_appends_venice_preamble(self):
        vp = engine.build_extra_body("m", True, venice=True,
                                     venice_system_prompt=True)["venice_parameters"]
        self.assertIs(vp["include_venice_system_prompt"], True)

    def test_hand_edited_dict_still_wins_over_the_tick(self):
        # venice_parameters merges OVER the tick — the config escape hatch
        # stays authoritative when explicitly set.
        vp = engine.build_extra_body(
            "m", True, venice=True, venice_system_prompt=True,
            venice_parameters={"include_venice_system_prompt": False})["venice_parameters"]
        self.assertIs(vp["include_venice_system_prompt"], False)

    def test_never_sent_when_venice_is_off(self):
        eb = engine.build_extra_body("deepseek-v4", True, venice=False,
                                     venice_system_prompt=True)
        self.assertEqual(eb, {"enable_thinking": True})


if __name__ == "__main__":
    unittest.main()
