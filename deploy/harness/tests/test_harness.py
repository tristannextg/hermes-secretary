"""Run: python3 -m unittest discover -s deploy/harness/tests

Everything here runs without hermes-agent, Telegram, Claude or the cockpit: Hermes core modules
are stubbed in sys.modules, the Session API is a fake `call`, and Claude Code is a stub binary.
"""

import asyncio
import datetime
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
# A stand-in for the official client: each account answers as SCRIPT says ("ok", or an HTTP
# status it refuses with), and RUNS records which account each request ran on.
OFFICIAL_SDK = '''
SCRIPT, RUNS = {}, []
class ClaudeAPIError(RuntimeError):
    def __init__(self, message, status_code=None):
        super().__init__(message)
        self.status_code = status_code
class Chunk:
    def __init__(self, text, final=False):
        self.text = text
        if final:
            self._response = {"text": text}
class Stream:
    def __init__(self, gen):
        self.gen, self.closed = gen, False
    def __iter__(self):
        return self
    def __next__(self):
        return next(self.gen)
    def close(self):
        self.closed = True
        self.gen.close()
class AsyncStream:
    def __init__(self, stream):
        self.stream = stream
class Client:
    def __init__(self, command=None, args=None, timeout=180, **_):
        self.command = [command] + list(args or [])
    def _create(self, **kwargs):
        account = self.command[-1]
        def gen():
            RUNS.append(account)
            answer = SCRIPT.get(account, "ok")
            if answer == "ok":
                yield Chunk("hello from " + account)
                yield Chunk("", final=True)
                return
            if answer == "mid":
                yield Chunk("half")
            raise ClaudeAPIError("refused", answer if isinstance(answer, int) else 429)
        return Stream(gen())
    def cancel(self):
        pass
    def close(self):
        pass
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
        with open(os.path.join(official, "directsdk.py"), "w") as f:
            f.write(OFFICIAL_SDK)
        self.wrapper = os.path.join(home, "bin", "claude-as")
        os.makedirs(os.path.dirname(self.wrapper))
        with open(self.wrapper, "w") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.wrapper, 0o755)
        with open(os.path.join(home, "claude-accounts.json"), "w") as f:
            json.dump({"wrapper": self.wrapper, "accounts": [
                {"provider": "claude-work", "account": "work"},
                {"provider": "claude-dx1", "account": "Duxalpha1", "label": "Claude (dx1)"},
                {"provider": "claude-dx2", "account": "Duxalpha2"}],
                "auto": {"provider": "claude-auto", "usage_ttl_s": 60}}, f)
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
        self.emitted = []
        emitted = self.emitted

        class StatusOutputMixin:
            def _emit_diagnostic_status(self, message):
                emitted.append(message)

        status = types.ModuleType("agent.status_output")
        status.StatusOutputMixin = self.Mixin = StatusOutputMixin
        self.chain = ["claude-auto", "custom"]
        cfg = types.ModuleType("hermes_cli.config")
        cfg.load_config = lambda: {"model": {"provider": self.chain[0]},
                                   "fallback_providers": [{"provider": p} for p in self.chain[1:]]}
        self.mods = {"providers": providers, "hermes_constants": consts, "agent": agent,
                     "agent.account_usage": usage, "agent.status_output": status,
                     "hermes_cli": types.ModuleType("hermes_cli"), "hermes_cli.config": cfg}
        patcher = mock.patch.dict(sys.modules, self.mods)
        patcher.start()
        self.addCleanup(patcher.stop)

    def plugin(self):
        return load("claude_accounts_under_test",
                    os.path.join(HARNESS, "plugins", "model-providers", "claude-accounts", "__init__.py"))

    def test_one_provider_per_account_running_the_wrapper(self):
        self.plugin()
        self.assertEqual(sorted(self.registered),
                         ["claude-auto", "claude-dx1", "claude-dx2", "claude-subscription-directsdk-experimental",
                          "claude-work"])
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

    # ---- claude-auto: the first account with headroom
    NOW = 1_793_369_000

    def auto(self, usage=None, script=None):
        """The plugin, the official stub's SCRIPT/RUNS, and claude-auto's client, on `usage`."""
        mod = self.plugin()
        sdk = next(m for n, m in sys.modules.items() if n.endswith("experimental.directsdk"))
        sdk.SCRIPT.clear()
        sdk.SCRIPT.update(script or {})
        sdk.RUNS.clear()
        profile = self.registered["claude-auto"]
        # as Hermes's external-process branch calls it
        client = profile.create_client(api_key="external-process", base_url="process://claude-auto",
                                       command="claude", args=[], timeout=5)
        self.assertEqual(client.base_url, "process://claude-auto")
        h = client.headroom
        self.readings = 0

        def fetch():
            self.readings += 1
            if isinstance(usage, Exception):
                raise usage
            return usage or {}

        h.fetch, h.clock = fetch, lambda: self.now
        self.now = self.NOW
        return mod, sdk, client

    def full(self, window="seven_day", reset_in=3600):
        return {window: {"pct": 100, "resets_at": self.NOW + reset_in}}

    def ask(self, client):
        return [c.text for c in client.chat.completions.create(model="sonnet", messages=[], stream=True)]

    def test_auto_skips_a_full_account_without_trying_it(self):
        _, sdk, client = self.auto({"work": self.full(), "Duxalpha1": {"five_hour": {"pct": 40}}})
        self.assertEqual(self.ask(client), ["hello from Duxalpha1", ""])
        self.assertEqual(sdk.RUNS, ["Duxalpha1"])  # work was never started
        self.assertEqual(client.chat.completions.create(model="sonnet", messages=[]), {"text": ""})
        self.assertEqual(sdk.RUNS, ["Duxalpha1", "Duxalpha1"])
        self.assertEqual(self.readings, 1)  # cached for usage_ttl_s
        self.now += 61
        self.ask(client)
        self.assertEqual(self.readings, 2)

    def test_auto_takes_the_first_in_order_and_a_reset_window_counts_as_headroom(self):
        _, sdk, client = self.auto({"work": {"seven_day": {"pct": 100, "resets_at": self.NOW - 5}},
                                    "Duxalpha1": {}})
        self.ask(client)
        self.assertEqual(sdk.RUNS, ["work"])

    def test_a_refusal_marks_the_account_until_its_reset_and_the_next_one_serves(self):
        _, sdk, client = self.auto({"work": {"five_hour": {"pct": 97, "resets_at": self.NOW + 900}}},
                                   script={"work": 429})
        self.assertEqual(self.ask(client), ["hello from Duxalpha1", ""])
        self.assertEqual(sdk.RUNS, ["work", "Duxalpha1"])
        with open(os.path.join(self.dir.name, "state", "claude-headroom.json")) as f:
            marks = json.load(f)["marks"]
        self.assertEqual(marks["work"]["until"], self.NOW + 15 * 60)  # no window is full: limited_s
        self.ask(client)
        self.assertEqual(sdk.RUNS, ["work", "Duxalpha1", "Duxalpha1"])  # not tried again per turn
        # another process (cron, the CLI) reads the same marks
        other = self.registered["claude-auto"].create_client(timeout=5)
        self.assertEqual(other.headroom.pick()[0], "Duxalpha1")
        self.now += 15 * 60 + 1
        sdk.SCRIPT.clear()
        self.ask(client)
        self.assertEqual(sdk.RUNS[-1], "work")
        self.assertNotIn("work", client.headroom.marks)

    def test_only_a_limit_or_a_login_moves_on_and_never_after_output(self):
        _, sdk, client = self.auto({}, script={"work": 529})
        with self.assertRaises(sdk.ClaudeAPIError) as e:
            self.ask(client)
        self.assertEqual(e.exception.status_code, 529)
        self.assertEqual(sdk.RUNS, ["work"])
        sdk.SCRIPT.update(work="mid")
        sdk.RUNS.clear()
        with self.assertRaises(sdk.ClaudeAPIError):
            self.ask(client)
        self.assertEqual(sdk.RUNS, ["work"])  # output went out: no second account repeats it
        sdk.SCRIPT.update(work=401)
        sdk.RUNS.clear()
        self.ask(client)
        self.assertEqual(sdk.RUNS, ["work", "Duxalpha1"])
        self.assertEqual(client.headroom.marks["work"]["until"], self.NOW + 1800)

    def test_all_out_is_one_429_with_the_earliest_reset_and_no_request(self):
        _, sdk, client = self.auto({"work": self.full(reset_in=7200), "Duxalpha1": self.full("five_hour", 1800),
                                    "Duxalpha2": self.full(reset_in=86400 * 2)},
                                   script={"work": 429, "Duxalpha1": 429, "Duxalpha2": 429})
        with self.assertRaises(sdk.ClaudeAPIError) as e:
            self.ask(client)
        # readings can be behind: each full account is tried once, and its refusal marks it
        self.assertEqual(sdk.RUNS, ["work", "Duxalpha1", "Duxalpha2"])
        self.assertEqual(e.exception.status_code, 429)
        self.assertEqual(e.exception.body["error"]["resets_at"], self.NOW + 1800)
        self.assertIn("rate limit", str(e.exception))
        self.assertIn("resets in 1800 seconds", str(e.exception))
        with self.assertRaises(sdk.ClaudeAPIError):
            self.ask(client)
        self.assertEqual(len(sdk.RUNS), 3)  # the next turn starts no claude at all

    def test_without_readings_it_goes_by_its_own_refusals(self):
        _, sdk, client = self.auto(RuntimeError("laptop asleep"), script={"work": 429})
        self.ask(client)
        self.ask(client)
        self.assertEqual(sdk.RUNS, ["work", "Duxalpha1", "Duxalpha1"])

    def test_planned_switch_notices_are_kept_out_and_everything_else_shown(self):
        self.plugin()
        agent = self.Mixin()
        planned = [
            ("⚠️ Model fallback: sonnet via claude-auto unavailable (rate limit); using "
             "qwen3.8-flash-next-iq3_s via custom. Primary retry eligible in ~60 s; recovery is not guaranteed."),
            ("✅ Primary model restored: sonnet via claude-auto; fallback qwen3.8-flash-next-iq3_s via custom "
             "is no longer active."),
            "⚠️ Model fallback: sonnet via claude-work unavailable (rate limit); using sonnet via claude-dx1.",
            "⚠️ Provider fallback: claude-auto/sonnet unavailable; using custom/qwen for this response.",
        ]
        shown = [
            "⚠️ Model fallback: sonnet via claude-auto unavailable (auth); using gpt via openrouter.",
            "🚫 This account is not entitled to opus via claude-auto; it will be skipped until restart.",
            "Context compaction failed: summary model unavailable",
        ]
        for m in planned + shown:
            agent._emit_diagnostic_status(m)
        self.assertEqual(self.emitted, shown)
        self.plugin()  # a second import does not wrap twice
        agent._emit_diagnostic_status(shown[0])
        self.assertEqual(self.emitted, shown + shown[:1])


# ------------------------------------------------------------ cockpit-cards
cards = load("cockpit_cards_under_test", os.path.join(HARNESS, "plugins", "cockpit-cards", "__init__.py"))
with mock.patch.dict(sys.modules, {"hermes_yaml": types.ModuleType("hermes_yaml")}):
    # the rule as install.sh configures it: the one place it lives
    RELAY_RULE = load("configure_for_rule", os.path.join(HARNESS, "configure.py")).RELAY
with open(os.path.join(HERE, "fixtures", "notify-pending.json")) as _f:
    RECORDED = json.load(_f)


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
        if method == "session.get" and "session.get" not in self.answers:
            failure = self.failures.get(args["id"]) if hasattr(self, "failures") else None
            return {"ok": True, "result": {"id": args["id"], "state": "failed", "failure": failure, "prs": []}}
        return self.answers.get(method, {"ok": True, "result": {"ok": True, "message": "Sent to x: Allow once"}})


class CockpitCards(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.api = FakeApi()
        self.sent, self.edits, self.next = [], [], 100
        self.relay = self.make()

    def make(self, rule="configured"):
        rule = RELAY_RULE if rule == "configured" else rule
        relay = cards.Relay(391230543, os.path.join(self.dir.name, "state", "cards.json"), call=self.api, rule=rule)

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

    # ---- the rule: only what needs Tristan now
    def write_state(self, name, data):
        os.makedirs(os.path.join(self.dir.name, "state"), exist_ok=True)
        with open(os.path.join(self.dir.name, "state", name), "w") as f:
            json.dump(data, f)

    def test_recorded_cards_only_questions_and_unfixable_failures_reach_the_phone(self):
        recorded = RECORDED[-1]["result"]["cards"]
        now = time.time()
        # replayed as they first arrived (open, rev 1), then as the cockpit closed them
        arrived = [dict(c, state="open", rev=1, closed=None, at=now) for c in recorded]
        failures = [c for c in recorded if c["kind"] == "failure"]
        # what session.get said of the failed chats: half stuck at a limit, one watched by keep-alive
        self.api.failures = {c["id"]: {"type": "rate_limit" if i % 2 else "process_exit"}
                             for i, c in enumerate(failures)}
        kept = next(c for i, c in enumerate(failures) if i % 2 == 0)
        self.write_state("keep-alive.json", {"watches": [{"vm": kept["vm"], "id": kept["id"]}]})
        self.relay.first_run = False
        self.api.pending = {"ok": True, "result": {"via": "hermes", "night": False, "cards": arrived}}
        self.poll()
        unfixable = {c["id"] for c in failures if self.api.failures[c["id"]]["type"] != "rate_limit"} - {kept["id"]}
        # cards from before the cockpit named their item are each their own message
        def episode(c):
            return c["item"] or (f"{c['vm']}/{c['id']}#e{c['episode']}" if c["episode"] is not None else c["card"])
        items = {episode(c) for c in recorded if c["kind"] == "blocking"}
        items |= {episode(c) for c in failures if c["id"] in unfixable}
        self.assertEqual(len(self.sent), len(items))  # one message per chat and episode
        silent = {c["card"]: c["silent"] for c in recorded}
        self.assertEqual([m[3] for m in self.sent], [silent[self.relay.card_of_message(m[0])] for m in self.sent])
        self.assertIn(True, silent.values())  # the record has night cards
        held = self.relay.state["held"]
        self.assertEqual(sorted({h["why"] for h in held}),
                         ["a rate_limit failure the cockpit's account rules handle",
                          "a usage limit the cockpit handles", "keep-alive revives it"])
        self.assertEqual(sum(h["kind"] == "limit" for h in held), sum(c["kind"] == "limit" for c in recorded))
        self.assertFalse(any("stuck at its usage limit" in s[1] for s in self.sent))
        # the cockpit closes them: only delivered messages are edited, a held card stays held
        self.api.pending["result"]["cards"] = [dict(c, rev=2, at=now) for c in recorded]
        self.poll()
        self.assertEqual(len(self.sent), len(items))
        self.assertEqual(len(self.edits), sum(1 for c in recorded if c["kind"] != "limit" and c["state"] == "closed"
                                              and self.relay.state["cards"][c["card"]].get("thread")
                                              and self.relay.state["threads"][self.relay.state["cards"][c["card"]]
                                                                              ["thread"]]["card"] == c["card"]))

    def test_messages_reviews_and_limits_are_held_with_why(self):
        self.api.pending["result"]["cards"] = [
            card("m1", kind="message", vm="dev-cloud", id="d441d8b2", html="<b>Secretary</b>\nall green", buttons=[]),
            card("r1", kind="review", item="dev-2/aaaa0002/review#t4"),
            card("l1", kind="limit", html="<b>x</b> is stuck at its usage limit"),
            card("b1", item="dev-1/3d76bde7/blocking#e4")]
        self.poll()
        self.assertEqual([s[1] for s in self.sent], ["<b>x</b> needs you"])
        self.assertEqual([(h["card"], h["why"]) for h in self.relay.state["held"]],
                         [("m1", "a message, nothing to decide"), ("r1", "a result to review, nothing blocks"),
                          ("l1", "a usage limit the cockpit handles")])

    def test_one_message_per_chat_and_episode_edited_in_place(self):
        item = "dev-1/3d76bde7/blocking#e4"
        self.api.pending["result"]["cards"] = [card("c1", item=item)]
        self.poll()
        # "later", then it comes back as a new card of the same item, the old one "sent again below"
        self.api.pending["result"]["cards"] = [card("c1", item=item, state="later", rev=2, until=time.time())]
        self.poll()
        self.api.pending["result"]["cards"] = [card("c1", item=item, state="closed", rev=3, closed="sent again below"),
                                               card("c2", item=item, html="<b>x</b> needs you (again)")]
        self.poll()
        self.assertEqual(len(self.sent), 1)
        mid = self.sent[0][0]
        self.assertEqual(self.edits[-1], (mid, "<b>x</b> needs you (again)", [
            [("1. Allow once", "nvc:c2:1"), ("2. Deny", "nvc:c2:2")],
            [("open in the cockpit", "nvc:c2:o"), ("later", "nvc:c2:l")]]))
        self.assertEqual(self.relay.card_of_message(mid), "c2")  # a reply answers the live card
        n = len(self.edits)
        self.poll()
        self.assertEqual(len(self.edits), n)
        # the next episode of the same chat is a new message
        self.api.pending["result"]["cards"] = [card("c3", item="dev-1/3d76bde7/blocking#e5")]
        self.poll()
        self.assertEqual(len(self.sent), 2)

    def test_a_chat_tristan_asked_about_gets_every_card_through(self):
        self.write_state("tell-me.json", {"watches": [
            {"vm": "dev-2", "id": "aaaa0002", "until": time.time() + 3600, "why": "Tristan: tell me about it"}]})
        self.api.pending["result"]["cards"] = [card("r1", kind="review", vm="dev-2", id="aaaa0002"),
                                               card("r2", kind="review", vm="dev-2", id="bbbb0002"),
                                               card("l1", kind="limit", vm="dev-2", id="aaaa0002")]
        self.poll()
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.relay.card_of_message(self.sent[0][0]), "r1")

    def test_a_watched_pr_is_told_once_when_ready_then_the_watch_ends(self):
        self.write_state("tell-me.json", {"watches": [
            {"pr": 4781, "repo": "Arnold-NextG/nxguide", "until": time.time() + 3600, "why": "Tristan", "added": 1},
            {"pr": 4782, "until": time.time() - 1, "why": "Tristan", "added": 2}]})
        pr = {"number": 4781, "repo": "Arnold-NextG/nxguide", "state": "OPEN", "draft": False,
              "ci": {"pass": 20, "fail": 0, "pending": 1, "total": 21}, "review": "APPROVED"}
        sessions = {"ok": True, "result": {"sessions": [{"id": "a87437ff", "vm": "dev-1", "name": "flaky test",
                                                         "prs": [pr]}]}}
        self.api.answers["sessions.list"] = sessions
        self.api.pending["result"]["night"] = True
        self.poll()
        self.assertEqual(self.sent, [])  # CI still running
        self.relay.told_at -= 61
        pr["ci"] = {"pass": 21, "fail": 0, "pending": 0, "total": 21}
        self.poll()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("#4781 is ready to merge", self.sent[0][1])
        self.assertTrue(self.sent[0][3])  # silent: the cockpit's night
        with open(os.path.join(self.dir.name, "state", "tell-me.json")) as f:
            self.assertEqual(json.load(f), {"watches": []})
        self.relay.told_at -= 61
        self.poll()
        self.assertEqual(len(self.sent), 1)
        # clean without a review: only session.get's merge state can tell
        self.assertEqual(cards.pr_verdict(dict(pr, review=None)), "clean?")
        self.assertEqual(cards.pr_verdict(dict(pr, review=None, merge_state="CLEAN")), "ready")
        self.assertIsNone(cards.pr_verdict(dict(pr, review=None, merge_state="BLOCKED")))
        self.assertEqual(cards.pr_verdict(dict(pr, state="MERGED")), "merged")
        self.assertIsNone(cards.pr_verdict(dict(pr, review="CHANGES_REQUESTED")))

    def test_without_a_rule_only_questions_go_out_and_it_says_so(self):
        with self.assertLogs(cards.logger, "ERROR"):
            self.relay = self.make(rule=None)
        self.api.pending["result"]["cards"] = [card("f1", kind="failure"), card("b1")]
        self.poll()
        self.assertEqual([self.relay.card_of_message(s[0]) for s in self.sent], ["b1"])

    def test_a_delivery_state_from_before_threads_keeps_its_messages(self):
        self.write_state("cards.json", {"cards": {"c9": {"msg": 77, "rev": 1, "state": "open", "at": time.time()},
                                                  "c8": {"msg": None, "rev": 1, "state": "skipped", "at": 1}}})
        self.relay = self.make()
        self.assertEqual(self.relay.card_of_message(77), "c9")
        self.api.pending["result"]["cards"] = [card("c9", state="closed", rev=2, closed="answered elsewhere")]
        self.poll()
        self.assertEqual(self.edits[-1][0], 77)
        self.assertEqual(self.sent, [])


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
        self.ops.TELL_ME = os.path.join(d, "state", "tell-me.json")
        self.ops.CARDS = os.path.join(d, "state", "cockpit-cards.json")
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

    def test_tell_me_watches_name_a_pr_or_a_chat_and_say_who_asked(self):
        r = json.loads(self.ops.tellme_add({"pr": 4781, "why": "Tristan: tell me when it can merge"}))
        self.assertEqual((r["watch"]["pr"], r["watch"]["repo"]), (4781, "Arnold-NextG/nxguide"))
        self.assertGreater(r["watch"]["until"], time.time() + 71 * 3600)
        self.ops.tellme_add({"pr": "4781", "why": "again"})
        self.ops.tellme_add({"vm": "dev-2", "id": "aaaa0002", "until": "4h", "why": "Tristan: watch it"})
        self.assertEqual(len(self.ops.load_tell_me()), 2)
        self.assertEqual(oct(os.stat(self.ops.TELL_ME).st_mode & 0o777), "0o600")
        for bad in ({"why": "x"}, {"pr": 1, "why": " "}, {"pr": -3, "why": "x"}, {"pr": 1, "repo": "evil/repo", "why": "x"},
                    {"vm": "dev-2", "id": "zz", "why": "x"}, {"pr": 1, "until": "400h", "why": "x"}):
            with self.assertRaises(ValueError):
                self.ops.tellme_add(bad)
        self.ops.tellme_remove({"pr": 4781})
        self.assertEqual([w.get("vm") for w in self.ops.load_tell_me()], ["dev-2"])
        writes = {t["name"] for t in self._tools() if not t["annotations"]["readOnlyHint"]}
        self.assertEqual(writes, {"keepalive_add", "keepalive_remove", "tellme_add", "tellme_remove"})

    def _tools(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            self.ops.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        return json.loads(out.getvalue())["result"]["tools"]

    def test_held_cards_are_listed_since_a_time_and_redacted(self):
        now = time.time()
        os.makedirs(os.path.dirname(self.ops.CARDS))
        with open(self.ops.CARDS, "w") as f:
            json.dump({"cards": {}, "held": [
                {"card": "c1", "kind": "limit", "text": "old", "at": now - 3 * 86400, "why": "a usage limit"},
                {"card": "c2", "kind": "message", "text": "token=abcdefghijkl here", "at": now - 60, "why": "a message"}]}, f)
        held = json.loads(self.ops.cards_held({}))["held"]
        self.assertEqual([h["card"] for h in held], ["c2"])
        self.assertNotIn("abcdefghijkl", held[0]["text"])
        self.assertEqual(len(json.loads(self.ops.cards_held({"since_h": 96}))["held"]), 2)

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


# ------------------------------------------------------------ the Neovim docs: build and search
WINDOWS_TXT = """\
==============================================================================
3. Closing a window\t\t\t\t\t*window-close*

CTRL-W o\t\t\t\t\t\t*CTRL-W_o* *E445*
CTRL-W CTRL-O\t\t\t\t\t*CTRL-W_CTRL-O* *:on* *:only*
\t\tMake the current window the only one on the screen. All other
\t\twindows are closed.

\t\tWhen the 'hidden' option is set, all buffers in closed windows
\t\tbecome hidden.

\t\t\t\t\t\t\t*:fc* *:fclose*
:[count]fc[lose][!]
\t\tClose [count] floating windows with the highest zindex values.

==============================================================================
4. Moving cursor to other windows\t\t\t*window-move-cursor*
"""
PICKER_TXT = """\
*snacks-picker*  snacks.nvim-picker

          win = {
            input = {
              keys = {
                ["<c-q>"] = { "qflist", mode = { "i", "n" } },
"""
README_MD = """\
# cockpit

## Keys

| `Alt-i` | the inbox |

```bash
# not a heading
```

### Inbox

Answers go to the chat, in its window.
"""


class NeovimDocs(unittest.TestCase):
    """scripts/neovim_docs.py builds the tree from stand-in nvim / nvc-vm binaries; the ops tools
    search what it built."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        d = self.dir.name
        self.runtime = os.path.join(d, "runtime")
        self.lazy = os.path.join(d, "lazy")
        self.src = os.path.join(d, "nvc-src")
        self.out = os.path.join(d, "docs", "neovim")
        for p in (os.path.join(self.runtime, "doc"), os.path.join(self.lazy, "snacks.nvim", "doc"),
                  os.path.join(self.lazy, "nvim-lint", "doc"), os.path.join(self.src, "nvim")):
            os.makedirs(p)
        write = self._write
        write(os.path.join(self.runtime, "doc", "windows.txt"), WINDOWS_TXT)
        write(os.path.join(self.runtime, "doc", "tags"), "not a doc\n")
        write(os.path.join(self.lazy, "snacks.nvim", "doc", "snacks.nvim-picker.txt"), PICKER_TXT)
        write(os.path.join(self.lazy, "snacks.nvim", "README.md"), "# snacks\n\n## Picker\n\nThe picker.\n")
        write(os.path.join(self.lazy, "nvim-lint", "doc", "lint.txt"), "*lint-window* only window lint\n")
        write(os.path.join(self.lazy, "unlocked", "README.md"), "# not in the lock\n")
        write(os.path.join(self.src, "README.md"), README_MD)
        write(os.path.join(self.src, "API.md"), "# API\n\n### `guide.get`\n\nThe guide.\n")
        write(os.path.join(self.src, ".nvc-sha"), "2c1af9b0ccc7\n")
        write(os.path.join(self.src, "install-vm.sh"), "NVIM_VERSION=0.12.5\n")
        write(os.path.join(self.src, "nvim", "lazy-lock.json"), json.dumps(
            {"snacks.nvim": {"commit": "882c996aaaa"}, "nvim-lint": {"commit": "1111111"}}))
        guide = {"v": 1, "sha": "2c1af9b0ccc7", "at_text": "today", "places": [
            {"name": "chat", "groups": [{"label": "Cockpit", "entries": [
                {"key": "Alt-i", "desc": "inbox (what needs you, all VMs)"}]}]}],
            "keys": [{"key": "Alt-a", "text": "agent sessions"}], "sections": [], "tips": [], "marks": []}
        maps = {"v": 1, "leader": " ", "maps": [
            {"mode": "n", "lhs": " wd", "desc": "Delete Window", "rhs": ""},
            {"mode": "n", "lhs": "<C-W>o", "desc": "", "rhs": ":only<CR>"},
            {"mode": "n", "lhs": "<Plug>(x)", "desc": "hidden", "rhs": ""}]}
        self.nvim = self._stub("nvim", f"""
case "$*" in
  --version) echo "NVIM v0.12.5" ;;
  *--clean*) printf %s '{self.runtime}' ;;
  *luafile*) echo noise; echo '{json.dumps(maps)}' ;;
  *) exit 9 ;;
esac""")
        self.nvc_vm = self._stub("nvc-vm", f"echo '{json.dumps(guide)}'")
        self.build = load("neovim_docs_under_test", os.path.join(HARNESS, "scripts", "neovim_docs.py"))
        b = self.build
        b.OUT, b.NVIM, b.NVC_VM, b.LAZY, b.COCKPIT = self.out, self.nvim, self.nvc_vm, self.lazy, self.src
        b.MIN_RUNTIME_FILES, b.MIN_TAGS, b.MIN_KEYMAPS = 1, 5, 1
        self.ops = load("hermes_ops_nvim_under_test", os.path.join(HARNESS, "bin", "hermes_ops_mcp.py"))
        self.ops.NVIM_DOCS = self.out

    def _write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(text)

    def _stub(self, name, body):
        path = os.path.join(self.dir.name, "bin", name)
        self._write(path, "#!/bin/sh\n" + body + "\n")
        os.chmod(path, 0o755)
        return path

    def _build(self):
        out = io.StringIO()
        with mock.patch.object(sys, "stdout", out):
            rc = self.build.main()
        return rc, out.getvalue()

    def test_the_build_writes_the_tree_its_index_and_what_does_not_match_a_pin(self):
        self.assertEqual(self._build(), (0, ""))  # silent when it worked: the cron job says nothing
        files = sorted(os.path.relpath(os.path.join(d, f), self.out)
                       for d, _, fs in os.walk(self.out) for f in fs)
        self.assertEqual(files, [
            "MANIFEST.json", "cockpit/API.md", "cockpit/README.md", "cockpit/guide.json", "cockpit/guide.md",
            "keymaps.md", "nvim/windows.txt", "plugins/nvim-lint/doc/lint.txt",
            "plugins/snacks.nvim/README.md", "plugins/snacks.nvim/doc/snacks.nvim-picker.txt", "tags.tsv"])
        with open(os.path.join(self.out, "tags.tsv")) as f:
            tags = f.read().splitlines()
        for row in ("CTRL-W_o\tnvim/windows.txt\t4", ":only\tnvim/windows.txt\t5", "E445\tnvim/windows.txt\t4",
                    "snacks-picker\tplugins/snacks.nvim/doc/snacks.nvim-picker.txt\t1",
                    "Inbox\tcockpit/README.md\t11", "guide.get\tcockpit/API.md\t3"):
            self.assertIn(row, tags)
        self.assertFalse([t for t in tags if t.startswith("not a heading")])  # a comment in a code block
        with open(os.path.join(self.out, "keymaps.md")) as f:
            maps = f.read()
        self.assertIn("normal           <leader>wd           Delete Window", maps)
        self.assertIn("<C-W>o               :only<CR>", maps)
        self.assertNotIn("<Plug>", maps)
        with open(os.path.join(self.out, "cockpit", "guide.md")) as f:
            self.assertIn("- `Alt-i` (chat, Cockpit): inbox (what needs you, all VMs)", f.read())
        with open(os.path.join(self.out, "MANIFEST.json")) as f:
            m = json.load(f)
        self.assertEqual((m["nvim"], m["nvim_pinned"], m["cockpit"]), ("0.12.5", "0.12.5", "2c1af9b0ccc7"))
        # the stand-in plugin dirs are no git checkouts: neither is at its locked commit
        self.assertEqual(m["drift"], ["nvim-lint at missing, lazy-lock.json says 1111111",
                                      "snacks.nvim at missing, lazy-lock.json says 882c996"])

    def test_a_failed_build_keeps_the_last_good_tree_and_says_why(self):
        self.assertEqual(self._build()[0], 0)
        with open(os.path.join(self.out, "MANIFEST.json")) as f:
            before = f.read()
        self._stub("nvc-vm", "echo 'guide failed' >&2; exit 1")
        rc, out = self._build()
        self.assertEqual(rc, 1)
        self.assertIn("Neovim docs NOT refreshed, the last good copy stays", out)
        self.assertIn("guide failed", out)
        with open(os.path.join(self.out, "MANIFEST.json")) as f:
            self.assertEqual(f.read(), before)
        self.assertEqual(sorted(os.listdir(os.path.dirname(self.out))), ["neovim"])  # no temp tree left

    def test_a_tag_gives_its_entry_up_to_the_next_one_then_near_tags_and_lines(self):
        self._build()
        out = self.ops.nvim_help({"query": ":only"})
        self.assertIn("Neovim docs: nvim 0.12.5, cockpit 2c1af9b0ccc7, built ", out)
        self.assertIn("--- nvim/windows.txt:4\nCTRL-W o\t\t\t\t\t\t*CTRL-W_o* *E445*\nCTRL-W CTRL-O", out)
        self.assertIn("Make the current window the only one on the screen.", out)
        self.assertIn("become hidden.", out)  # the entry's second paragraph
        self.assertNotIn("floating windows", out)  # the next entry
        self.assertIn("Other tags containing it: CTRL-W_o", self.ops.nvim_help({"query": "ctrl-w"}))
        self.assertIn("--- plugins/snacks.nvim/README.md:3\n## Picker\n\nThe picker.",
                      self.ops.nvim_help({"query": "Picker"}))

    def test_words_find_lines_where_the_file_name_counts_and_the_setup_comes_first(self):
        self._build()
        out = self.ops.nvim_help({"query": "snacks picker <c-q>"})
        self.assertIn('Lines, 1 of 1:\nplugins/snacks.nvim/doc/snacks.nvim-picker.txt:6: ["<c-q>"] = { "qflist"', out)
        out = self.ops.nvim_help({"query": "window"})
        lines = out.split("Lines, ")[1].splitlines()[1:]
        self.assertEqual(lines[0], "keymaps.md:6: normal           <leader>wd           Delete Window")
        self.assertEqual(lines[1], "cockpit/README.md:13: Answers go to the chat, in its window.")
        self.assertEqual(self.ops.nvim_help({"query": "inbox", "in": "cockpit"}).split("Lines, ")[1].splitlines()[1],
                         "cockpit/guide.md:9: - `Alt-i` (chat, Cockpit): inbox (what needs you, all VMs)")
        self.assertTrue(lines[-1].startswith("plugins/"), lines)
        # `in` is a directory, not a prefix: nvim is not nvim-lint
        out = self.ops.nvim_help({"query": "window", "in": "nvim"})
        self.assertIn("Other tags containing it: window-close  window-move-cursor", out)
        self.assertNotIn("lint-window", out)
        self.assertNotIn("plugins/nvim-lint", out)
        self.assertIn("plugins/nvim-lint/doc/lint.txt:1:", self.ops.nvim_help({"query": "window", "in": "nvim-lint"}))
        with self.assertRaisesRegex(ValueError, r"nvim-lint, snacks.nvim"):
            self.ops.nvim_help({"query": "x", "in": "telescope"})

    def test_reading_is_confined_and_stale_or_missing_docs_say_so(self):
        self._build()
        out = self.ops.nvim_help_read({"file": "nvim/windows.txt", "line": 4, "lines": 2})
        self.assertIn("--- nvim/windows.txt (17 lines)\n4: CTRL-W o", out)
        self.assertTrue(out.rstrip().endswith("5: CTRL-W CTRL-O\t\t\t\t\t*CTRL-W_CTRL-O* *:on* *:only*"))
        self.assertIn("Close [count] floating", self.ops.nvim_help_read({"tag": ":fclose"}))
        for bad in ({"file": "../../etc/passwd"}, {"tag": "no-such-tag"}):
            with self.assertRaises(ValueError):
                self.ops.nvim_help_read(bad)
        with self.assertRaisesRegex(ValueError, "outside"):
            self.ops.nvim_help({"query": "x", "in": "../.."})
        path = os.path.join(self.out, "MANIFEST.json")
        with open(path) as f:
            m = json.load(f)
        m["built"] = (datetime.datetime.now().astimezone() - datetime.timedelta(days=4)).isoformat()
        with open(path, "w") as f:
            json.dump(m, f)
        self.assertIn("(STALE: the daily neovim-docs job", self.ops.nvim_help({"query": ":only"}))
        self.ops.NVIM_DOCS = os.path.join(self.dir.name, "nowhere")
        with self.assertRaisesRegex(ValueError, "has not built them"):
            self.ops.nvim_help({"query": ":only"})


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
        self.assertEqual(new["model"], {"provider": "claude-auto", "default": "sonnet"})
        self.assertEqual([e["provider"] for e in new["fallback_providers"]], ["custom"])
        self.assertEqual(new["fallback_providers"][-1]["key_env"], "STRATA_API_KEY")
        self.assertEqual(new["terminal"]["docker_forward_env"], [])
        self.assertFalse(new["terminal"]["docker_network"])
        self.assertEqual(new["memory"], {"memory_enabled": True, "memory_char_limit": 6000})
        self.assertEqual(new["plugins"]["enabled"],
                         ["other", "claude-subscription-directsdk-experimental", "cockpit-cards"])
        self.assertEqual(new["plugins"]["entries"]["cockpit-cards"]["settings"]["chat_id"], 391230543)
        self.assertIs(new["platforms"]["telegram"]["enabled"], False)  # never left to the env token
        self.assertTrue(new["platforms"]["discord"]["enabled"])
        self.assertEqual(new["cron"], {"model": "opus", "model_provider": "claude-auto"})
        self.assertEqual(new["plugins"]["entries"]["cockpit-cards"]["settings"]["relay"]["send"],
                         ["blocking", "failure"])
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
