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
        eb = engine.build_extra_body("glm-5-3-flash-uncensored", True, venice=True)
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


if __name__ == "__main__":
    unittest.main()
