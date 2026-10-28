"""Run: python3 -m unittest discover -s deploy/harness/tests

Everything here runs without hermes-agent, Telegram, Claude or the cockpit: Hermes core modules
are stubbed in sys.modules, the Session API is a fake `call`, and Claude Code is a stub binary.
"""

import asyncio
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
HARNESS = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(HARNESS, "bin"))
sys.path.insert(0, os.path.join(HARNESS, "scripts"))
sys.path.insert(0, os.path.join(HARNESS, "..", "claude", "bin"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(coro):
    return asyncio.run(coro)


# ------------------------------------------------------------ claude-as
class ClaudeAs(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        self.store = os.path.join(d, "accounts")
        os.makedirs(self.store)
        with open(os.path.join(self.store, "work.token"), "w") as f:
            f.write("sk-ant-oat01-" + "x" * 40 + "\n")
        with open(os.path.join(self.store, "alienware.token"), "w") as f:
            f.write('{"base_url": "http://h", "key": "k"}')
        # a stand-in claude that reports what it was given (the token only as its length)
        self.fake = os.path.join(d, "claude")
        with open(self.fake, "w") as f:
            f.write("#!/bin/sh\necho \"args=$*\"\necho \"tok_len=${#CLAUDE_CODE_OAUTH_TOKEN}\"\n"
                    "echo \"cfg=$CLAUDE_CONFIG_DIR\"\necho \"api_key=${ANTHROPIC_API_KEY:-unset}\"\n")
        os.chmod(self.fake, 0o755)
        self.root = os.path.join(d, "cfgroot")

    def run_as(self, *args):
        env = dict(os.environ, NVC_ACCOUNTS_DIR=self.store, CLAUDE_AS_BIN=self.fake,
                   CLAUDE_AS_CONFIG_ROOT=self.root, ANTHROPIC_API_KEY="leaked")
        return subprocess.run([os.path.join(HARNESS, "bin", "claude-as"), *args], env=env,
                              capture_output=True, text=True)

    def test_token_goes_by_env_never_argv_and_each_account_has_its_own_config_dir(self):
        r = self.run_as("work", "-p", "--model", "sonnet")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("args=-p --model sonnet", r.stdout)
        self.assertIn("tok_len=53", r.stdout)  # the trailing newline is stripped
        self.assertNotIn("sk-ant", r.stdout + r.stderr)
        self.assertIn(f"cfg={self.root}/work", r.stdout)
        self.assertTrue(os.path.isdir(os.path.join(self.root, "work")))
        self.assertIn("api_key=unset", r.stdout)

    def test_refuses_bad_names_missing_tokens_and_self_hosted_sources(self):
        self.assertEqual(self.run_as("../work").returncode, 2)
        self.assertEqual(self.run_as("").returncode, 2)
        r = self.run_as("Duxalpha1")
        self.assertEqual(r.returncode, 3)
        self.assertIn("no token for account Duxalpha1", r.stderr)
        r = self.run_as("alienware")
        self.assertEqual(r.returncode, 3)
        self.assertIn("self-hosted source", r.stderr)


# ------------------------------------------------------------ claude-accounts provider plugin
OFFICIAL_INIT = '''
from .directsdk_setup import fetch_usage
from providers import register_provider
class Profile:
    def __init__(self):
        self.name = "claude-subscription-directsdk-experimental"
        self.display_name = "official"
        self.description = ""
        self.base_url = "process://claude-subscription-directsdk-experimental"
        self.process_command = "claude"
        self.process_args = ()
        self.process_command_env_vars = ("CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND",)
        self.aliases = ("official-alias",)
        self.native_reasoning_details_type = "claude-subscription-directsdk-experimental.native_assistant"
        self.supports_streaming = True
    def create_client(self, **kw):
        c = type("Client", (), {})()
        c.kw = kw
        c.base_url = "process://claude-subscription-directsdk-experimental"
        return c
    def setup_status(self, **kw):
        return kw
    def discover_models(self, **kw):
        return kw
def usage_windows(limits):
    return (["w:" + str(limits)], [])
profile = Profile()
register_provider(profile)
'''
OFFICIAL_SETUP = '''
CALLS = []
def fetch_usage(command=None, env=None, timeout=8):
    CALLS.append(command)
    return {"five_hour": 1}, None
'''


class ClaudeAccounts(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        home = self.dir.name
        official = os.path.join(home, "plugins", "claude-subscription-directsdk-experimental")
        os.makedirs(official)
        with open(os.path.join(official, "__init__.py"), "w") as f:
            f.write(OFFICIAL_INIT)
        with open(os.path.join(official, "directsdk_setup.py"), "w") as f:
            f.write(OFFICIAL_SETUP)
        self.wrapper = os.path.join(home, "bin", "claude-as")
        os.makedirs(os.path.dirname(self.wrapper))
        with open(self.wrapper, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.wrapper, 0o755)
        with open(os.path.join(home, "claude-accounts.json"), "w") as f:
            json.dump({"wrapper": self.wrapper, "accounts": [
                {"provider": "claude-work", "account": "work"},
                {"provider": "claude-dx1", "account": "Duxalpha1", "label": "Claude (dx1)"}]}, f)
        self.registered = {}
        providers = types.ModuleType("providers")
        providers.register_provider = lambda p: self.registered.__setitem__(p.name, p)
        providers._user_module_name = lambda d, key: f"_test_user_{key}_{os.path.basename(d).replace('-', '_')}"
        consts = types.ModuleType("hermes_constants")
        consts.get_hermes_home = lambda: home
        consts.hermes_home_key = lambda h: "k" + str(abs(hash(h)) % 10000)
        usage = types.ModuleType("agent.account_usage")
        usage.AccountUsageSnapshot = lambda **kw: kw
        agent = types.ModuleType("agent")
        self.mods = {"providers": providers, "hermes_constants": consts, "agent": agent,
                     "agent.account_usage": usage}
        patcher = mock.patch.dict(sys.modules, self.mods)
        patcher.start()
        self.addCleanup(patcher.stop)

    def plugin(self):
        return load("claude_accounts_under_test",
                    os.path.join(HARNESS, "plugins", "model-providers", "claude-accounts", "__init__.py"))

    def test_one_provider_per_account_running_the_wrapper(self):
        self.plugin()
        self.assertEqual(sorted(self.registered),
                         ["claude-dx1", "claude-subscription-directsdk-experimental", "claude-work"])
        work = self.registered["claude-work"]
        client = work.create_client(command="claude", args=[], timeout=5)
        self.assertEqual(client.kw["command"], self.wrapper)
        self.assertEqual(client.kw["args"], ["work"])
        self.assertEqual(client.base_url, "process://claude-work")
        self.assertEqual(work.process_command_env_vars, ())
        self.assertEqual(work.aliases, ())
        # the replay carrier stays the official one, or every cached prefix is dropped
        self.assertEqual(work.native_reasoning_details_type,
                         "claude-subscription-directsdk-experimental.native_assistant")
        self.assertTrue(work.supports_streaming)
        self.assertEqual(self.registered["claude-dx1"].display_name, "Claude (dx1)")
        self.assertNotEqual(work.base_url, self.registered["claude-dx1"].base_url)
        # the official profile itself is untouched
        official = self.registered["claude-subscription-directsdk-experimental"]
        self.assertEqual(official.process_command, "claude")
        self.assertEqual(official.aliases, ("official-alias",))

    def test_usage_and_setup_ask_the_accounts_own_cli(self):
        self.plugin()
        dx1 = self.registered["claude-dx1"]
        snap = dx1.fetch_account_usage()
        self.assertEqual(snap["provider"], "claude-dx1")
        self.assertEqual(snap["windows"], ("w:{'five_hour': 1}",))
        setup = next(m for n, m in sys.modules.items() if n.endswith("directsdk_setup"))
        self.assertEqual(setup.CALLS[-1], [self.wrapper, "Duxalpha1"])
        self.assertEqual(dx1.setup_status()["command"], [self.wrapper, "Duxalpha1"])

    def test_account_list_errors_are_named(self):
        mod = self.plugin()
        bad = os.path.join(self.dir.name, "bad.json")
        with open(bad, "w") as f:
            json.dump({"accounts": [{"provider": "a", "account": "x"}, {"provider": "a", "account": "y"}]}, f)
        with self.assertRaisesRegex(ValueError, "listed twice"):
            mod.load_accounts(mod.Path(bad))
        with open(bad, "w") as f:
            json.dump({"accounts": [{"provider": "a"}]}, f)
        with self.assertRaisesRegex(ValueError, "needs provider and account"):
            mod.load_accounts(mod.Path(bad))


# ------------------------------------------------------------ cockpit-cards
cards = load("cockpit_cards_under_test", os.path.join(HARNESS, "plugins", "cockpit-cards", "__init__.py"))


def card(cid="c1", state="open", rev=1, **kw):
    c = {"card": cid, "kind": "blocking", "vm": "dev-1", "id": "3d76bde7", "html": "<b>x</b> needs you",
         "buttons": [[{"label": "1. Allow once", "action": "1"}, {"label": "2. Deny", "action": "2"}],
                     [{"label": "open in the cockpit", "action": "o"}, {"label": "later", "action": "l"}]],
         "state": state, "rev": rev, "silent": False, "at": time.time()}
    c.update(kw)
    return c


class FakeApi:
    def __init__(self):
        self.pending = {"ok": True, "result": {"via": "hermes", "cards": []}}
        self.calls = []
        self.answers = {}

    async def __call__(self, method, args, why=None):
        self.calls.append((method, args, why))
        if method == "notify.pending":
            return self.pending
        return self.answers.get(method, {"ok": True, "result": {"ok": True, "message": "Sent to x: Allow once"}})


class CockpitCards(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.api = FakeApi()
        self.sent, self.edits, self.next = [], [], 100
        self.relay = self.make()

    def make(self):
        relay = cards.Relay(391230543, os.path.join(self.dir.name, "state", "cards.json"), call=self.api)

        async def send(text, rows, silent):
            self.next += 1
            self.sent.append((self.next, text, rows, silent))
            return self.next

        async def edit(mid, text, rows):
            self.edits.append((mid, text, rows))

        relay.send, relay.edit = send, edit
        return relay

    def poll(self):
        return run(self.relay.poll_once())

    def test_a_new_card_goes_out_once_with_its_buttons_and_sound(self):
        self.api.pending["result"]["cards"] = [card(silent=True)]
        self.assertEqual(self.poll(), 1)
        self.assertEqual(self.poll(), 0)
        mid, text, rows, silent = self.sent[0]
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(text, "<b>x</b> needs you")
        self.assertEqual(rows[0], [("1. Allow once", "nvc:c1:1"), ("2. Deny", "nvc:c1:2")])
        self.assertTrue(silent)
        self.assertEqual(self.relay.card_of_message(mid), "c1")

    def test_a_closed_or_later_card_is_edited_without_buttons(self):
        self.api.pending["result"]["cards"] = [card()]
        self.poll()
        self.api.pending["result"]["cards"] = [card(state="closed", rev=2, closed="answered: Allow once")]
        self.poll()
        mid, text, rows = self.edits[-1]
        self.assertEqual(mid, 101)
        self.assertTrue(text.endswith("<b>answered: Allow once</b>"))
        self.assertEqual(rows, [])
        self.api.pending["result"]["cards"] = [card("c2"), card("c2", state="later", rev=2, until=0)]
        self.api.pending["result"]["cards"] = [card("c2")]
        self.poll()
        self.api.pending["result"]["cards"] = [card("c2", state="later", rev=2, until=time.time() + 3600)]
        self.poll()
        self.assertIn("later: it comes back at", self.edits[-1][1])
        self.assertEqual(self.edits[-1][2], [])

    def test_never_sends_what_closed_before_delivery_nor_a_first_run_backlog(self):
        self.api.pending["result"]["cards"] = [card("old", at=time.time() - 3 * 86400),
                                               card("gone", state="closed", rev=3)]
        self.poll()
        self.assertEqual(self.sent, [])
        self.api.pending["result"]["cards"].append(card("new"))
        self.poll()
        self.assertEqual([s[1] for s in self.sent], ["<b>x</b> needs you"])
        self.assertEqual(self.relay.card_of_message(self.sent[0][0]), "new")

    def test_nothing_is_relayed_unless_the_cockpit_hands_cards_to_hermes(self):
        self.api.pending = {"ok": True, "result": {"via": "bot", "cards": [card()]}}
        self.assertEqual(self.poll(), 0)
        self.api.pending = {"ok": False, "error": {"code": "unavailable", "message": "laptop asleep"}}
        self.assertEqual(self.poll(), 0)
        self.assertIsNotNone(self.relay.down)
        self.assertEqual(self.relay.interval(8), 16)
        for _ in range(9):
            self.poll()
        self.assertEqual(self.relay.interval(8), cards.BACKOFF_MAX_S)
        self.api.pending = {"ok": True, "result": {"via": "hermes", "cards": [card()]}}
        self.assertEqual(self.poll(), 1)
        self.assertIsNone(self.relay.down)
        self.assertEqual(self.relay.interval(8), 8)

    def test_taps_and_replies_go_to_the_api_with_a_why(self):
        ok, text = run(self.relay.tap("nvc:c7:2"))
        self.assertTrue(ok)
        self.assertEqual(self.api.calls[-1][:2], ("notify.answer", {"card": "c7", "option": 2}))
        self.assertIn("Tristan tapped option 2", self.api.calls[-1][2])
        run(self.relay.tap("nvc:c7:o"))
        self.assertEqual(self.api.calls[-1][:2], ("notify.open", {"card": "c7"}))
        run(self.relay.tap("nvc:c7:l"))
        self.assertEqual(self.api.calls[-1][:2], ("notify.later", {"card": "c7"}))
        n = len(self.api.calls)
        self.assertEqual(run(self.relay.tap("nvc:c7:x")), (False, "Nothing was sent: unknown button."))
        self.assertEqual(run(self.relay.tap("other:c7:1"))[0], False)
        self.assertEqual(len(self.api.calls), n)
        self.api.answers["notify.answer"] = {"ok": False, "error": {"code": "refused",
                                                                    "message": "Not sent: already answered."}}
        self.assertEqual(run(self.relay.reply("c7", "use the second one")), "Not sent: already answered.")
        self.assertEqual(self.api.calls[-1][1], {"card": "c7", "text": "use the second one"})

    def test_delivery_state_survives_a_restart(self):
        self.api.pending["result"]["cards"] = [card()]
        self.poll()
        self.relay = self.make()
        self.assertEqual(self.poll(), 0)
        self.assertEqual(len(self.sent), 1)


# ------------------------------------------------------------ keep-alive
class KeepAlive(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ka = load("keep_alive_under_test", os.path.join(HARNESS, "scripts", "keep_alive.py"))
        d = self.dir.name
        self.ka.WATCHES = os.path.join(d, "keep-alive.json")
        self.ka.STATE = os.path.join(d, "keep-alive-state.json")
        self.ka.LOG = os.path.join(d, "keep-alive.log")
        self.now = 1_800_000_000
        self.session = {"id": "0eaee10c", "vm": "dev-3", "name": "FMIS", "account": "work",
                        "state": "working", "need": None, "failure": None, "archived": False}
        self.calls = []
        self.answers = {}
        self.ka.api = self.fake_api
        self.watch()

    def watch(self, **kw):
        w = {"vm": "dev-3", "id": "0eaee10c", "until": self.now + 3600, "why": "Tristan: keep it going"}
        w.update(kw)
        with open(self.ka.WATCHES, "w") as f:
            json.dump({"watches": [w]}, f)

    def fake_api(self, method, args, why=None):
        self.calls.append((method, args, why))
        if method == "session.get":
            return {"ok": True, "result": dict(self.session)}
        if method == "policy.get":
            return {"ok": True, "result": {"auto": True, "accounts": {
                "work": {"priority": 3}, "Duxalpha1": {"priority": 2, "five_hour": 10, "week": 20},
                "Duxalpha2": {"priority": 2, "five_hour": 50, "week": 60},
                "private": {"priority": 9, "reserved": True}, "bernd": {"priority": 5, "capped": True}}}}
        if method == "accounts.list":
            return {"ok": True, "result": {"accounts": [
                {"name": n, "vms": ["dev-3"]} for n in ("work", "Duxalpha1", "Duxalpha2", "private", "bernd")]}}
        return self.answers.get(method, {"ok": True, "result": {"ok": True, "how": "started again"}})

    def acts(self):
        return [c[0] for c in self.calls if c[0] not in ("session.get", "policy.get", "accounts.list")]

    def test_a_working_or_asking_session_is_left_alone(self):
        self.assertEqual(self.ka.tick(self.now), [])
        self.session.update(state="needs-you", need={"kind": "permission"})
        self.assertEqual(self.ka.tick(self.now), [])
        self.assertEqual(self.acts(), [])

    def test_a_dead_claude_is_revived_once_then_nudged_once_at_its_prompt(self):
        self.session.update(state="failed", failure={"type": "process_exit", "at": 5})
        out = self.ka.tick(self.now)
        self.assertEqual(self.acts(), ["session.revive"])
        self.assertIn("had stopped", out[0])
        self.assertIn("keep-alive until", self.calls[-1][2])
        self.session.update(state="needs-you", need={"kind": "dialog"})
        self.ka.tick(self.now + 300)  # back up but showing a dialog: no nudge into it
        self.assertEqual(self.acts(), ["session.revive"])
        self.session.update(state="done", need=None)
        out = self.ka.tick(self.now + 600)
        self.assertEqual(self.acts(), ["session.revive", "session.send_text"])
        nudge = [c for c in self.calls if c[0] == "session.send_text"][0]
        self.assertIn("Continue where you left off", nudge[1]["text"])
        self.assertIn("nudged", out[0])
        self.session.update(state="failed", failure={"type": "process_exit", "at": 5})
        self.ka.tick(self.now + 900)  # the same failure record again: no second revive or nudge
        self.ka.tick(self.now + 1200)
        self.assertEqual(self.acts(), ["session.revive", "session.send_text"])

    def test_a_session_stuck_at_its_limit_moves_after_the_grace_to_the_best_allowed_account(self):
        self.session.update(state="failed", failure={"type": "rate_limit", "at": 1})
        self.ka.tick(self.now)
        self.ka.tick(self.now + self.ka.LIMIT_GRACE_S - 1)
        self.assertNotIn("session.switch_account", self.acts())
        out = self.ka.tick(self.now + self.ka.LIMIT_GRACE_S)
        switch = [c for c in self.calls if c[0] == "session.switch_account"]
        self.assertEqual(switch[0][1]["account"], "Duxalpha1")  # never private, never capped bernd
        self.assertEqual(switch[0][1]["when"], "if_idle")
        self.assertIn("moved to Duxalpha1", out[0])

    def test_watches_end_at_until_when_archived_or_gone(self):
        self.assertIn("ended", self.ka.tick(self.now + 3600)[0])
        self.assertEqual(self.ka.load(self.ka.WATCHES, {})["watches"], [])
        self.watch()
        self.session["archived"] = True
        self.assertIn("archived", self.ka.tick(self.now)[0])
        self.watch()
        self.ka.api = lambda m, a, why=None: {"ok": False, "error": {"code": "not_found", "message": "x"}}
        self.assertIn("gone", self.ka.tick(self.now)[0])

    def test_an_unreachable_cockpit_keeps_the_watch(self):
        self.ka.api = lambda m, a, why=None: {"ok": False, "error": {"code": "unavailable", "message": "asleep"}}
        self.assertEqual(self.ka.tick(self.now), [])
        self.assertEqual(len(self.ka.load(self.ka.WATCHES, {})["watches"]), 1)

    def test_silent_at_night(self):
        import datetime
        self.assertTrue(self.ka.night(datetime.datetime(2026, 10, 28, 23, 0)))
        self.assertTrue(self.ka.night(datetime.datetime(2026, 10, 29, 6, 59)))
        self.assertFalse(self.ka.night(datetime.datetime(2026, 10, 29, 7, 0)))
        with mock.patch.object(self.ka, "tick", return_value=["acted"]), \
                mock.patch.object(self.ka, "night", return_value=True), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.ka.main()
        self.assertEqual(out.getvalue(), "")


# ------------------------------------------------------------ hermes-ops MCP
class HermesOps(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.ops = load("hermes_ops_under_test", os.path.join(HARNESS, "bin", "hermes_ops_mcp.py"))
        d = self.dir.name
        self.ops.WATCHES = os.path.join(d, "state", "keep-alive.json")
        self.ops.MEMORY = os.path.join(d, "memory")
        self.ops.DOCS = os.path.join(d, "docs")
        os.makedirs(self.ops.MEMORY)
        os.makedirs(self.ops.DOCS)
        with open(os.path.join(self.ops.MEMORY, "rule.md"), "w") as f:
            f.write("---\nname: rule\ndescription: \"merge only on request\"\n---\nNever merge. token=abcdefghijkl\n")
        with open(os.path.join(d, "secret.md"), "w") as f:
            f.write("outside")
        with open(os.path.join(self.ops.DOCS, "README.md"), "w") as f:
            f.write("# cockpit\n\n## Keys\n\n| `Alt-i` | the inbox: `d` dismisses an item |\n| `Alt-1` | VM 1 |\n\n"
                    "## Telegram\n\nCards.\n\n## Where each requirement lives\n\n" + "| inbox | x |\n" * 30)

    def test_keepalive_watches_are_validated_and_replaced_per_session(self):
        r = json.loads(self.ops.keepalive_add({"vm": "dev-3", "id": "0eaee10c", "until": "2h", "why": "Tristan asked"}))
        self.assertEqual(r["watches"], 1)
        self.ops.keepalive_add({"vm": "dev-3", "id": "0eaee10c", "until": "3h", "why": "again"})
        self.assertEqual(len(self.ops.load_watches()), 1)
        self.assertEqual(oct(os.stat(self.ops.WATCHES).st_mode & 0o777), "0o600")
        for bad in ({"vm": "dev-3", "id": "nothex!!", "until": "2h", "why": "x"},
                    {"vm": "dev-3", "id": "0eaee10c", "until": "2h", "why": " "},
                    {"vm": "dev-3", "id": "0eaee10c", "until": "2020-01-01T00:00", "why": "x"},
                    {"vm": "dev-3", "id": "0eaee10c", "until": "400h", "why": "x"},
                    {"vm": "../x", "id": "0eaee10c", "until": "2h", "why": "x"}):
            with self.assertRaises(ValueError):
                self.ops.keepalive_add(bad)
        self.ops.keepalive_remove({"vm": "dev-3", "id": "0eaee10c"})
        self.assertEqual(self.ops.load_watches(), [])

    def test_memory_is_read_only_confined_and_redacted(self):
        self.assertIn("rule.md: merge only on request", self.ops.memory_list({}))
        text = self.ops.memory_read({"name": "rule.md"})
        self.assertIn("Never merge", text)
        self.assertNotIn("abcdefghijkl", text)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.ops.memory_read({"name": "../secret.md"})
        self.assertIn("rule.md:5:", self.ops.memory_search({"query": "never MERGE"}))

    def test_redaction_covers_the_token_shapes(self):
        for s in ("ghp_" + "a" * 36, "github_pat_" + "b" * 40, "sk-ant-oat01-" + "c" * 30,
                  "123456789:" + "D" * 35, "Authorization: token=" + "e" * 20, "AKIA" + "F" * 16):
            self.assertNotIn(s, self.ops.redact(f"x {s} y"), s)
        self.assertEqual(self.ops.redact("12 failed, 340 passed"), "12 failed, 340 passed")

    def test_cockpit_doc_finds_the_section(self):
        self.assertIn("## Keys", self.ops.cockpit_doc({"doc": "README"}))
        found = self.ops.cockpit_doc({"doc": "README", "query": "inbox dismiss"})
        # the line matching both words wins over a long table that repeats one of them
        self.assertIn("## Keys\n  | `Alt-i` | the inbox: `d` dismisses an item |", found)
        self.assertNotIn("| inbox | x |", found)
        self.assertIn("Cards.", self.ops.cockpit_doc({"doc": "README", "query": "telegram"}))
        with self.assertRaises(ValueError):
            self.ops.cockpit_doc({"doc": "../../etc/passwd"})

    def test_github_is_get_only_and_the_token_never_follows_a_redirect(self):
        tokfile = os.path.join(self.dir.name, "gh.env")
        with open(tokfile, "w") as f:
            f.write("GITHUB_TOKEN=github_pat_testtoken\n")
        self.ops.TOKEN_FILES = [tokfile]
        seen = []

        class Redirect(Exception):
            pass

        def opener_open(req, timeout=None):
            seen.append(("api", req.get_method(), req.get_header("Authorization")))
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, 302, "Found", {"Location": "https://blob/x"}, io.BytesIO())

        def urlopen(url, timeout=None):
            seen.append(("blob", url))
            return io.BytesIO(b"line1\nok 12 passed\n")

        fake = types.SimpleNamespace(open=opener_open)
        with mock.patch.object(self.ops.urllib.request, "build_opener", return_value=fake), \
                mock.patch.object(self.ops.urllib.request, "urlopen", side_effect=urlopen):
            out = self.ops.gh_job_log({"job_id": 5, "tail": 20})
        self.assertIn("ok 12 passed", out)
        self.assertEqual(seen[0], ("api", "GET", "Bearer github_pat_testtoken"))
        self.assertEqual(seen[1], ("blob", "https://blob/x"))  # a bare URL: no header can ride along
        with open(os.path.join(HARNESS, "bin", "hermes_ops_mcp.py")) as f:
            src = f.read()
        self.assertNotRegex(src, r"method=\"(POST|PUT|PATCH|DELETE)\"")
        with self.assertRaisesRegex(ValueError, "repo must be one of"):
            self.ops.gh_pr({"number": 1, "repo": "someone/else"})


# ------------------------------------------------------------ the vault gate, hermes_mcp agent mode
class VaultGate(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.gate = load("gate_under_test", os.path.join(HARNESS, "scripts", "vault_commands_gate.py"))
        self.gate.MARK = os.path.join(self.dir.name, "mark")

    def run_gate(self, response):
        with mock.patch.object(self.gate.urllib.request, "urlopen", side_effect=response), \
                mock.patch("sys.stdout", new_callable=io.StringIO) as out:
            self.gate.main()
        return out.getvalue().strip().splitlines()

    def test_no_commands_skips_the_model_and_commands_wake_it(self):
        def ok(body):
            return lambda *a, **k: io.BytesIO(json.dumps(body).encode())

        self.assertEqual(self.run_gate(ok({"data": {"commands": []}})), ['{"wakeAgent": false}'])
        out = self.run_gate(ok({"data": {"commands": [{"raw_text": "@hermes remind me"}]}}))
        self.assertEqual(out[0], "Pending @hermes vault commands:")

    def test_a_down_api_wakes_once_in_six_hours_never_reads_as_empty(self):
        def down(*a, **k):
            raise OSError("connection refused")
        self.assertIn("VAULT API DOWN", self.run_gate(down)[0])
        self.assertEqual(self.run_gate(down), ['{"wakeAgent": false}'])


class HermesMcpAgentMode(unittest.TestCase):
    def test_agent_mode_has_the_vault_and_the_log_to_read_only(self):
        import hermes_mcp
        with mock.patch.dict(os.environ, {"HERMES_MCP_MODE": "agent"}):
            self.assertEqual(sorted(hermes_mcp.tools()), ["chat_history", "vault_read", "vault_write"])
        with mock.patch.dict(os.environ, {"HERMES_MCP_MODE": "desk"}):
            self.assertIn("log_exchange", hermes_mcp.tools())
        with mock.patch.dict(os.environ, {"HERMES_MCP_MODE": ""}):
            self.assertIn("telegram_send", hermes_mcp.tools())
            self.assertNotIn("log_exchange", hermes_mcp.tools())


# ------------------------------------------------------------ configure.py
class Configure(unittest.TestCase):
    def setUp(self):
        fake_yaml = types.ModuleType("hermes_yaml")
        patcher = mock.patch.dict(sys.modules, {"hermes_yaml": fake_yaml})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.cfg = load("configure_under_test", os.path.join(HARNESS, "configure.py"))

    def test_managed_keys_replace_whole_sections_and_leave_the_rest(self):
        old = {"model": {"provider": "custom", "default": "claude-opus-4-8", "base_url": "http://10.16.0.34:8018/v1",
                         "key_env": "OPENAI_API_KEY"},
               "terminal": {"backend": "docker", "docker_forward_env": ["OBSIDIAN_APPROVAL_SECRET"]},
               "memory": {"memory_enabled": True}, "plugins": {"enabled": ["other"]},
               "platforms": {"discord": {"enabled": True}}}
        new = self.cfg.apply(old, 391230543, "keep")
        self.assertEqual(new["model"], {"provider": "claude-work", "default": "sonnet"})
        self.assertEqual([e["provider"] for e in new["fallback_providers"]], ["claude-dx1", "claude-dx2", "custom"])
        self.assertEqual(new["fallback_providers"][-1]["key_env"], "STRATA_API_KEY")
        self.assertEqual(new["terminal"]["docker_forward_env"], [])
        self.assertFalse(new["terminal"]["docker_network"])
        self.assertEqual(new["memory"], {"memory_enabled": True})
        self.assertEqual(new["plugins"]["enabled"],
                         ["other", "claude-subscription-directsdk-experimental", "cockpit-cards"])
        self.assertEqual(new["plugins"]["entries"]["cockpit-cards"]["settings"]["chat_id"], 391230543)
        self.assertIs(new["platforms"]["telegram"]["enabled"], False)  # never left to the env token
        self.assertTrue(new["platforms"]["discord"]["enabled"])
        self.assertEqual(new["cron"], {"model": "opus", "model_provider": "claude-work"})
        self.assertEqual(new["auth"]["adopt_external_logins"], False)
        self.assertNotIn("private", json.dumps(new))
        self.assertEqual(old["model"]["provider"], "custom")  # the input is not mutated

    def test_telegram_switch(self):
        on = self.cfg.apply({}, 1, "on")
        self.assertIs(on["platforms"]["telegram"]["enabled"], True)
        self.assertIs(self.cfg.apply(on, 1, "keep")["platforms"]["telegram"]["enabled"], True)
        self.assertIs(self.cfg.apply(on, 1, "off")["platforms"]["telegram"]["enabled"], False)

    def test_env_rewrite_touches_terminal_lines_only(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, ".env")
            with open(p, "w") as f:
                f.write("TELEGRAM_BOT_TOKEN=keep-me\nTERMINAL_DOCKER_FORWARD_ENV=[\"OBSIDIAN_APPROVAL_SECRET\"]\n"
                        "TERMINAL_MODAL_IMAGE=x\nSTRATA_API_KEY=keep-me-too\n")
            self.cfg.rewrite_env(p, {"TERMINAL_ENV": "docker", "TERMINAL_DOCKER_FORWARD_ENV": "[]"})
            with open(p) as f:
                lines = f.read().splitlines()
            self.assertEqual(oct(os.stat(p).st_mode & 0o777), "0o600")
        self.assertEqual(lines, ["TELEGRAM_BOT_TOKEN=keep-me", "STRATA_API_KEY=keep-me-too",
                                 "TERMINAL_DOCKER_FORWARD_ENV=[]", "TERMINAL_ENV=docker"])


if __name__ == "__main__":
    unittest.main()
