"""Missed-reply recovery policy (pure).

Razif's pain: a disconnect (or an LLM error) can leave his last message
unanswered — "when it reconnects, i dont have the respond so i need to
copy and paste back my chat entry". Recovery: on resume, an unanswered
user TEXT message means the reply must be generated."""
import unittest

import engine


def msg(role, content, **kw):
    m = {"role": role, "content": content}
    m.update(kw)
    return m


class TestNeedsReplyRecovery(unittest.TestCase):
    def test_unanswered_user_text_needs_recovery(self):
        self.assertTrue(engine.needs_reply_recovery([
            msg("character", "hi"), msg("user", "hello there")]))

    def test_answered_user_message_needs_nothing(self):
        self.assertFalse(engine.needs_reply_recovery([
            msg("user", "hello"), msg("character", "hi back")]))

    def test_trailing_system_line_is_ignored(self):
        self.assertTrue(engine.needs_reply_recovery([
            msg("user", "hello"), msg("system", "Connection lost")]))

    def test_image_only_message_expects_no_reply(self):
        self.assertFalse(engine.needs_reply_recovery([
            msg("character", "hi"), msg("user", "", image_path="x.png")]))

    def test_ends_on_character_needs_nothing(self):
        self.assertFalse(engine.needs_reply_recovery([
            msg("user", "x"), msg("character", "y")]))

    def test_empty_history_needs_nothing(self):
        self.assertFalse(engine.needs_reply_recovery([]))
        self.assertFalse(engine.needs_reply_recovery(None))

    def test_whitespace_only_user_message_needs_nothing(self):
        self.assertFalse(engine.needs_reply_recovery([msg("user", "   \n ")]))


if __name__ == "__main__":
    unittest.main()
