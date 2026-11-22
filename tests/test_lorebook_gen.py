"""Lorebook generator tests (card + chats -> entries).

Two-pass design: distill story facts from chat chunks, then write
ST-format entries from card + facts + notes. Everything here is synthetic
— no chat database is ever read by the test suite.
"""
import asyncio
import unittest
from types import SimpleNamespace

import lorebook


class FakeCompletions:
    def __init__(self, parent):
        self.p = parent

    async def create(self, **kw):
        self.p.calls.append(kw)
        content = self.p.replies.pop(0) if self.p.replies else "NONE"
        msg = SimpleNamespace(content=content)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=msg, finish_reason="stop")])


class FakeClient:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []
        self.chat = SimpleNamespace(completions=FakeCompletions(self))


def run(coro):
    return asyncio.run(coro)


class TestChunker(unittest.TestCase):
    def test_chunks_at_message_boundaries(self):
        msgs = [{"content": "a" * 30}, {"content": "b" * 30}, {"content": "c" * 30}]
        chunks = lorebook._chunk_contents(msgs, max_chars=70)  # 30+2+30 fits, +c not
        self.assertEqual(len(chunks), 2)
        self.assertNotIn("c" * 30, chunks[0])

    def test_drops_oldest_when_chunk_cap_bites(self):
        msgs = [{"content": f"m{i}"} for i in range(30)]
        chunks = lorebook._chunk_contents(msgs, max_chars=2, max_chunks=3)
        self.assertEqual(len(chunks), 3)
        self.assertIn("m29", chunks[-1])
        self.assertNotIn("m0", chunks[0])

    def test_empty_content_skipped(self):
        chunks = lorebook._chunk_contents(
            [{"content": ""}, {"content": None}, {"content": "x"}])
        self.assertEqual(chunks, ["x"])


class TestBuildGenMessages(unittest.TestCase):
    card = {"data": {"name": "Farah", "description": "Cafe owner",
                     "scenario": "The cafe", "personality": "quiet",
                     "creator_notes": "my notes"}}

    def test_card_fields_included(self):
        msgs = lorebook.build_lorebook_gen_messages(self.card)
        user = msgs[1]["content"]
        self.assertIn("Farah", user)
        self.assertIn("Cafe owner", user)
        self.assertIn("The cafe", user)
        self.assertIn("my notes", user)

    def test_facts_and_notes_blocks(self):
        msgs = lorebook.build_lorebook_gen_messages(
            self.card, facts="the cafe burned", notes="cover the fire")
        user = msgs[1]["content"]
        self.assertIn("Established facts", user)
        self.assertIn("the cafe burned", user)
        self.assertIn("His notes", user)
        self.assertIn("cover the fire", user)

    def test_card_can_be_excluded(self):
        msgs = lorebook.build_lorebook_gen_messages(
            self.card, facts="fact", include_card=False)
        self.assertNotIn("Cafe owner", msgs[1]["content"])
        self.assertIn("fact", msgs[1]["content"])

    def test_max_entries_reaches_the_system_prompt(self):
        msgs = lorebook.build_lorebook_gen_messages(self.card, max_entries=7)
        self.assertIn("At most 7 entries", msgs[0]["content"])
        self.assertNotIn("{max_entries}", msgs[0]["content"])


class TestParseEntries(unittest.TestCase):
    def test_valid_entries_normalized(self):
        raw = ('{"entries": [{"key": ["Tanjung Rasa"], "comment": "cafe", '
               '"content": "lore here", "order": 200}]}')
        entries, warnings = lorebook.parse_generated_entries(raw)
        self.assertEqual(len(entries), 1)
        e = entries["0"]
        self.assertEqual(e["key"], ["Tanjung Rasa"])
        self.assertEqual(e["order"], 200)
        self.assertIs(e["constant"], False)     # forced
        self.assertEqual(e["position"], 1)      # forced (after system)
        self.assertEqual(warnings, [])

    def test_short_keys_dropped_with_warning(self):
        raw = ('{"entries": [{"key": ["x", "ok key"], "content": "a"},'
               ' {"key": ["y"], "content": "b"}]}')
        entries, warnings = lorebook.parse_generated_entries(raw)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries["0"]["key"], ["ok key"])
        self.assertTrue(any("no usable keys" in w for w in warnings))

    def test_empty_content_dropped(self):
        raw = '{"entries": [{"key": ["good key"], "content": "   "}]}'
        entries, warnings = lorebook.parse_generated_entries(raw)
        self.assertEqual(entries, {})
        self.assertTrue(any("empty content" in w for w in warnings))

    def test_duplicate_key_sets_dropped(self):
        raw = ('{"entries": [{"key": ["alpha", "beta"], "content": "1"},'
               ' {"key": ["Beta", "ALPHA"], "content": "2"}]}')
        entries, warnings = lorebook.parse_generated_entries(raw)
        self.assertEqual(len(entries), 1)
        self.assertTrue(any("duplicate" in w for w in warnings))

    def test_entry_cap_enforced(self):
        raw = '{"entries": [' + ",".join(
            '{"key": ["key%d"], "content": "c"}' % i for i in range(20)) + "]}"
        entries, warnings = lorebook.parse_generated_entries(raw, max_entries=5)
        self.assertEqual(len(entries), 5)
        self.assertTrue(any("cap" in w for w in warnings))

    def test_fenced_and_repaired_json(self):
        raw = '```json\n{"entries": [{"key": ["good key"], "content": "c"},]}\n```'
        entries, warnings = lorebook.parse_generated_entries(raw)
        self.assertEqual(len(entries), 1)
        self.assertTrue(any("repaired" in w for w in warnings))

    def test_garbage_reply(self):
        entries, warnings = lorebook.parse_generated_entries("I cannot help with that.")
        self.assertEqual(entries, {})
        self.assertIn("reply was not JSON", warnings)


class TestDistill(unittest.TestCase):
    def test_merges_chunks_and_drops_none(self):
        client = FakeClient([
            "the jetty key stayed with her\nNONE",
            "she never locks the blue drawer\nthe jetty key stayed with her",
        ])
        msgs = [{"content": "a" * 7000}, {"content": "b" * 7000}]  # 2 chunks
        facts, chunks = run(lorebook.distill_chat_facts(
            msgs, client, "mock-model"))
        self.assertEqual(chunks, 2)
        self.assertIn("blue drawer", facts)
        self.assertNotIn("NONE", facts)

    def test_dedupes_repeated_facts(self):
        client = FakeClient(["same fact\nsame fact", "same fact"])
        msgs = [{"content": "a" * 7000}, {"content": "b" * 7000}]
        facts, chunks = run(lorebook.distill_chat_facts(msgs, client, "mock-model"))
        self.assertEqual(chunks, 2)
        self.assertEqual(facts.count("same fact"), 1)


class TestGenerate(unittest.TestCase):
    def test_end_to_end_with_fake_client(self):
        raw = '{"entries": [{"key": ["the cafe"], "content": "burned down"}]}'
        client = FakeClient([raw])
        entries, warnings = run(lorebook.generate_lorebook_entries(
            {"data": {"name": "Farah", "description": "d"}},
            facts="the cafe burned", client=client, model="mock-model"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(client.calls[0]["model"], "mock-model")
        self.assertIn("max_tokens", client.calls[0])

    def test_extra_body_forwarded(self):
        client = FakeClient(['{"entries": []}'])
        run(lorebook.generate_lorebook_entries(
            {"data": {"name": "X"}}, client=client, model="m",
            extra_body={"venice_parameters": {"x": 1}}))
        self.assertEqual(client.calls[0]["extra_body"], {"venice_parameters": {"x": 1}})


class TestPromptContract(unittest.TestCase):
    def test_gen_prompt_compact_and_complete(self):
        sysp = lorebook.LORE_GEN_SYSTEM
        self.assertLess(len(sysp.split()), 320)          # his compact rule
        self.assertIn("{max_entries}", sysp)
        self.assertIn("at least 3 characters", sysp)
        self.assertIn("50-120 words", sysp)
        self.assertIn("Nothing invented", sysp)
        self.assertIn("no code fences", sysp)

    def test_distill_prompt_compact(self):
        sysp = lorebook.LORE_DISTILL_SYSTEM
        self.assertLess(len(sysp.split()), 130)
        self.assertIn("NONE", sysp)
        self.assertIn("Nothing invented", sysp)


if __name__ == "__main__":
    unittest.main()
