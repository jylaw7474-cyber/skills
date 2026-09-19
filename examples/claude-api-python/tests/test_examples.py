"""Offline checks for the example programs - no API calls are made."""
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))

os.environ.setdefault("AGENT_WORKSPACE", tempfile.mkdtemp(prefix="agent-ws-"))
import agent  # noqa: E402
import batch_processor  # noqa: E402
from anthropic.lib.tools import ToolError  # noqa: E402


class AgentToolTests(unittest.TestCase):
    def test_tools_have_schemas(self):
        names = {tool.name for tool in agent.TOOLS}
        self.assertEqual(names, {"list_files", "read_file", "write_file", "calculate", "get_current_datetime"})
        for tool in agent.TOOLS:
            self.assertIn("input_schema", tool.to_dict())

    def test_paths_outside_workspace_are_refused(self):
        with self.assertRaises(ToolError):
            agent._resolve("../outside.txt")
        with self.assertRaises(ToolError):
            agent._resolve("/etc/passwd")
        self.assertEqual(agent._resolve("a/b.txt"), agent.WORKSPACE / "a" / "b.txt")

    def test_write_then_read_and_list(self):
        agent.auto_approve = True
        try:
            self.assertIn("Wrote", agent.write_file.call({"path": "sub/hello.txt", "content": "hi there"}))
        finally:
            agent.auto_approve = False
        self.assertEqual(agent.read_file.call({"path": "sub/hello.txt"}), "hi there")
        self.assertIn("sub/hello.txt", agent.list_files.call({"directory": "."}))

    def test_write_declined_without_terminal(self):
        agent.auto_approve = False
        with mock.patch.object(sys, "stdin", io.StringIO("")):
            with self.assertRaises(ToolError):
                agent.write_file.call({"path": "never.txt", "content": "x"})
        self.assertFalse((agent.WORKSPACE / "never.txt").exists())

    def test_calculate(self):
        self.assertAlmostEqual(json.loads(agent.calculate.call({"expression": "(1200 * 47.5) * 1.08"})), 61560.0)
        self.assertEqual(json.loads(agent.calculate.call({"expression": "sqrt(16) + 2 ** 3"})), 12.0)
        for bad in ("__import__('os')", "2 ** 999999", "1 / 0", "open('x')"):
            with self.assertRaises(ToolError):
                agent.calculate.call({"expression": bad})

    def test_datetime_rejects_unknown_zone(self):
        self.assertRegex(agent.get_current_datetime.call({"timezone": "UTC"}), r"\d{4}-\d{2}-\d{2}T")
        with self.assertRaises(ToolError):
            agent.get_current_datetime.call({"timezone": "Mars/Olympus"})


class BatchBuildTests(unittest.TestCase):
    def test_load_items_jsonl_and_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp, "items.jsonl")
            jsonl.write_text('{"id": "a", "text": "one"}\n\n{"text": "two"}\n', encoding="utf-8")
            self.assertEqual(batch_processor.load_items(jsonl),
                             [{"id": "a", "text": "one"}, {"id": "3", "text": "two"}])
            txt = Path(tmp, "items.txt")
            txt.write_text("first\nsecond\n", encoding="utf-8")
            self.assertEqual([i["text"] for i in batch_processor.load_items(txt)], ["first", "second"])

    def test_classify_requests_use_structured_output(self):
        args = batch_processor.parse_args(["submit", "x.jsonl", "--task", "classify", "--labels", "pos,neg"])
        task = batch_processor.build_task(args)
        requests = batch_processor.build_requests(
            [{"id": "a", "text": "great"}, {"id": "b", "text": "awful"}], task, "claude-opus-5", None)
        self.assertEqual([r["custom_id"] for r in requests], ["item-000000", "item-000001"])
        params = requests[0]["params"]
        self.assertEqual(params["model"], "claude-opus-5")
        self.assertEqual(params["output_config"]["effort"], "low")
        self.assertEqual(params["output_config"]["format"]["schema"]["properties"]["label"]["enum"], ["pos", "neg"])
        self.assertIn("cache_control", params["system"][-1])
        self.assertIn("<text>\ngreat\n</text>", params["messages"][0]["content"])

    def test_context_file_carries_cache_breakpoint(self):
        args = batch_processor.parse_args(["submit", "x.jsonl", "--task", "summarize"])
        task = batch_processor.build_task(args)
        system = batch_processor.build_system(task, "shared guideline document")
        self.assertEqual(len(system), 2)
        self.assertNotIn("cache_control", system[0])
        self.assertEqual(system[1]["cache_control"], {"type": "ephemeral"})
        self.assertIsNone(task["schema"])

    def test_custom_task_requires_placeholder(self):
        args = batch_processor.parse_args(["submit", "x.jsonl", "--task", "custom", "--prompt", "no placeholder"])
        with self.assertRaises(SystemExit):
            batch_processor.build_task(args)


if __name__ == "__main__":
    unittest.main()
