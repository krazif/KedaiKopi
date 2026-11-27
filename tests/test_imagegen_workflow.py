"""Workflow assembly for ComfyUI generation.

Field bug: "right after a very good prompt" the generate call died with
"Unexpected token 'I', "Internal S"... is not valid JSON" — the
%positive% substitution hand-escaped only backslashes and quotes, so a
caption containing a LINE BREAK (long captions wrap) produced invalid
JSON, json.loads raised, and the exception escaped to Uvicorn's plain-
text 500 which the frontend tried to parse."""
import unittest

import imagegen


TEXT_NODE = {"6": {"class_type": "CLIPTextEncode",
                   "inputs": {"text": "%positive%", "clip": ["5", 1]}}}


class TestBuildWorkflow(unittest.TestCase):
    def build(self, template, prompt="hello", neg="bad", **kw):
        real = imagegen.db.IMAGEGEN_WORKFLOW
        imagegen.db.IMAGEGEN_WORKFLOW = template
        try:
            return imagegen.build_workflow(prompt, neg, **kw)
        finally:
            imagegen.db.IMAGEGEN_WORKFLOW = real

    def test_prompt_with_newline_survives_substitution(self):
        prompt = "The room is quiet.\nShe looks up at the camera."
        wf = self.build(dict(TEXT_NODE), prompt=prompt)
        self.assertEqual(wf["6"]["inputs"]["text"], prompt)

    def test_quotes_and_backslashes_survive(self):
        prompt = 'a sign reading "OPEN" \\ path'
        wf = self.build(dict(TEXT_NODE), prompt=prompt)
        self.assertEqual(wf["6"]["inputs"]["text"], prompt)

    def test_control_characters_survive(self):
        prompt = "tab\there\r\nline"
        wf = self.build(dict(TEXT_NODE), prompt=prompt)
        self.assertEqual(wf["6"]["inputs"]["text"], prompt)

    def test_numeric_placeholders_are_raw_numbers(self):
        template = {"5": {"class_type": "EmptyLatentImage",
                          "inputs": {"width": "%width%", "height": "%height%",
                                     "seed": "%seed%", "batch_size": 1}}}
        wf = self.build(template, seed=42, width=768, height=512)
        ins = wf["5"]["inputs"]
        self.assertEqual(ins["width"], 768)
        self.assertEqual(ins["height"], 512)
        self.assertEqual(ins["seed"], 42)
        self.assertIsInstance(ins["seed"], int)

    def test_bare_placeholder_inside_longer_string(self):
        template = {"6": {"inputs": {"text": "cinematic, %positive%!"}}}
        wf = self.build(template, prompt="a fox")
        self.assertEqual(wf["6"]["inputs"]["text"], "cinematic, a fox!")

    def test_negative_placeholder(self):
        template = {"7": {"inputs": {"text": "%negative%"}}}
        wf = self.build(template, neg="blurry")
        self.assertEqual(wf["7"]["inputs"]["text"], "blurry")


if __name__ == "__main__":
    unittest.main()
