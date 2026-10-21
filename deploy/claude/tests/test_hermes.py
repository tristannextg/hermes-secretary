"""Run: python3 -m unittest discover -s deploy/claude/tests"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

BIN = os.path.join(os.path.dirname(__file__), "..", "bin")
sys.path.insert(0, BIN)

import hermes_mcp  # noqa: E402
import hermes_run  # noqa: E402


class AccountSpec(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def file(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, "w") as f:
            f.write(text)
        return path

    def test_merges_files_in_order_and_keeps_the_first_of_a_name(self):
        a = self.file("a.env", 'X=1\nCLAUDE_ACCOUNT_TOKENS="Duxalpha1:tok-a Duxalpha2:tok-b"\n')
        b = self.file("b.env", 'CLAUDE_ACCOUNT_TOKENS="work:tok-w Duxalpha2:tok-other"\n')
        missing = os.path.join(self.dir.name, "absent.env")
        with mock.patch.dict(os.environ, {"HERMES_ACCOUNT_FILES": f"{a} {missing} {b}"}):
            self.assertEqual(
                hermes_run.account_spec(), "Duxalpha1:tok-a Duxalpha2:tok-b work:tok-w"
            )

    def test_no_accounts_is_an_error_not_an_idle_run(self):
        empty = self.file("e.env", 'CLAUDE_ACCOUNT_TOKENS=""\n')
        with mock.patch.dict(os.environ, {"HERMES_ACCOUNT_FILES": empty}):
            code, res = hermes_run.run_job("check", "hi")
        self.assertEqual(code, 1)
        self.assertIn("empty", res["result"])


class VaultTools(unittest.TestCase):
    def test_unlisted_endpoints_are_refused(self):
        with self.assertRaisesRegex(ValueError, "not a write tool"):
            hermes_mcp.vault_write({"tool": "create_morning_briefing", "body": {}})
        with self.assertRaisesRegex(ValueError, "not a read tool"):
            hermes_mcp.vault_read({"tool": "../health"})

    def test_approval_secret_is_added_server_side(self):
        with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as f:
            f.write("OTHER=x\nOBSIDIAN_APPROVAL_SECRET='s3cret'\n")
        self.addCleanup(os.remove, f.name)
        with mock.patch.dict(os.environ, {"HERMES_SECRET_FILES": f.name}), mock.patch.object(
            hermes_mcp, "http", return_value='{"ok": true}'
        ) as http:
            hermes_mcp.vault_write({"tool": "apply_suggestion", "body": {"suggestion_id": "7"}})
            hermes_mcp.vault_write({"tool": "write_agent_note", "body": {"path": "p"}})
        apply_body, note_body = http.call_args_list[0].args[2], http.call_args_list[1].args[2]
        self.assertEqual(apply_body, {"suggestion_id": "7", "approval_token": "s3cret"})
        self.assertNotIn("approval_token", note_body)

    def test_read_params_are_encoded(self):
        with mock.patch.object(hermes_mcp, "http", return_value="{}") as http:
            hermes_mcp.vault_read({"tool": "read_note", "params": {"path": "a b.md", "with_ages": True}})
        self.assertEqual(
            http.call_args.args[1],
            f"{hermes_mcp.OPS}/tools/read_note?path=a+b.md&with_ages=true",
        )

    def test_missing_secret_names_the_key(self):
        with mock.patch.dict(os.environ, {"HERMES_SECRET_FILES": "/nonexistent"}):
            with self.assertRaisesRegex(RuntimeError, "TELEGRAM_BOT_TOKEN"):
                hermes_mcp.secret("TELEGRAM_BOT_TOKEN")


class Protocol(unittest.TestCase):
    def test_initialize_list_and_a_failing_call(self):
        reqs = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "vault_read", "arguments": {"tool": "nope"}}},
        ]
        out = subprocess.run(
            [sys.executable, "-I", os.path.join(BIN, "hermes_mcp.py")],
            input="".join(json.dumps(r) + "\n" for r in reqs),
            capture_output=True, text=True, timeout=20, check=True,
        ).stdout.splitlines()
        init, listed, call = (json.loads(line) for line in out)
        self.assertEqual(init["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(
            {t["name"] for t in listed["result"]["tools"]},
            {"vault_read", "vault_write", "telegram_send", "remember", "chat_history"},
        )
        self.assertTrue(call["result"]["isError"])
        self.assertIn("not a read tool", call["result"]["content"][0]["text"])


class DeskMode(unittest.TestCase):
    def test_desk_mode_swaps_telegram_send_for_log_exchange(self):
        with mock.patch.dict(os.environ, {"HERMES_MCP_MODE": "desk"}):
            self.assertIn("log_exchange", hermes_mcp.tools())
            self.assertNotIn("telegram_send", hermes_mcp.tools())
        with mock.patch.dict(os.environ, {"HERMES_MCP_MODE": ""}):
            self.assertIn("telegram_send", hermes_mcp.tools())
            self.assertNotIn("log_exchange", hermes_mcp.tools())

    def test_log_exchange_lands_in_the_shared_chat_log(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hermes_mcp, "CHAT_LOG", os.path.join(d, "chat.jsonl")):
            hermes_mcp.log_exchange({"tristan": "how is #4373?", "hermes": "waiting on review"})
            history = hermes_mcp.chat_history({"days": 1})
        self.assertIn("tristan: how is #4373?", history)
        self.assertIn("hermes: waiting on review", history)


class Commands(unittest.TestCase):
    def test_no_pending_commands_starts_no_session(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hermes_run, "STATE", d), \
                mock.patch.object(hermes_mcp, "http", return_value='{"data": {"commands": []}}'), \
                mock.patch.object(hermes_run, "run_job") as run_job:
            self.assertEqual(hermes_run.commands(), 0)
        run_job.assert_not_called()

    def test_unreachable_vault_api_alerts(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(hermes_run, "STATE", d), \
                mock.patch.object(hermes_mcp, "http", side_effect=OSError("refused")), \
                mock.patch.object(hermes_mcp, "send_telegram") as send:
            self.assertEqual(hermes_run.commands(), 1)
        self.assertIn("not answering", send.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
