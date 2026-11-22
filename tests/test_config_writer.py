"""Config writer tests.

The writer hand-serializes each section line by line; anything it doesn't
know gets dropped on save. That silently ate the venice_system_prompt
tick on 2026-11-22 (Settings save from a backend 25 minutes older than
the frontend). _dump_extras now carries unknown keys through every save.
"""
import tempfile
import unittest
from pathlib import Path

import config


def tmp_path():
    return Path(tempfile.mkdtemp()) / "config.jsonc"


class TestConfigWriterPreservesUnknownKeys(unittest.TestCase):
    def test_unknown_keys_survive_a_save(self):
        path = tmp_path()
        cfg = {
            "server": {"host": "0.0.0.0", "port": 7864},
            "chat": {"api_key": "SECRET-TEST-KEY", "venice": True,
                     "venice_system_prompt": True, "my_experiment": 7,
                     "venice_parameters": {"enable_web_search": "off"}},
            "imagegen": {"enabled": True, "my_img_key": "x"},
        }
        config.save_config(cfg, path)
        back = config.load_config(path)
        self.assertIs(back["chat"]["venice_system_prompt"], True)
        self.assertEqual(back["chat"]["my_experiment"], 7)
        self.assertEqual(back["chat"]["api_key"], "SECRET-TEST-KEY")
        self.assertEqual(back["chat"]["venice_parameters"],
                         {"enable_web_search": "off"})
        self.assertEqual(back["imagegen"]["my_img_key"], "x")

    def test_known_keys_still_written_with_defaults(self):
        path = tmp_path()
        config.save_config({}, path)
        back = config.load_config(path)
        self.assertEqual(back["server"]["port"], 7864)
        self.assertIn("reasoning_effort", back["chat"])
        self.assertIn("venice", back["chat"])
        # official MOSS negatives are the default
        self.assertIn("bad anatomy", back["imagegen"]["negative_prompt"])

    def test_save_is_idempotent(self):
        path = tmp_path()
        cfg = {"chat": {"api_key": "k", "extra_one": 1, "extra_two": "z"}}
        config.save_config(cfg, path)
        first = path.read_text(encoding="utf-8")
        config.save_config(config.load_config(path), path)
        second = path.read_text(encoding="utf-8")
        self.assertEqual(first, second)

    def test_trailing_comment_lines_stay_parseable(self):
        # imagegen.workflow and paths entries end in // comments — an
        # extras append must insert the comma BEFORE the comment.
        path = tmp_path()
        config.save_config({"imagegen": {"workflow": "wf.json",
                                         "added_key": True}}, path)
        back = config.load_config(path)
        self.assertEqual(back["imagegen"]["workflow"], "wf.json")
        self.assertIs(back["imagegen"]["added_key"], True)

    def test_no_comma_artifacts(self):
        # load_config forgives trailing commas, so its round-trip would
        # mask the exact mistakes _dump_extras could make — check the raw
        # text for them instead.
        path = tmp_path()
        config.save_config({"chat": {"api_key": "k", "odd key!": "kept"},
                            "imagegen": {"workflow": "wf.json", "x": 1},
                            "paths": {"personas_dir": "/p", "y": 2}}, path)
        raw = path.read_text(encoding="utf-8")
        self.assertNotRegex(raw, r",\s*,", "double comma")
        self.assertNotRegex(raw, r",\s*\}", "trailing comma before }")
        self.assertNotRegex(raw, r",\s*\]", "trailing comma before ]")
        self.assertEqual(config.load_config(path)["chat"]["odd key!"], "kept")


if __name__ == "__main__":
    unittest.main()
