#!/usr/bin/env bash
# The checks in test_harness.py bite: each mutant is a copy of deploy/ with one rule broken, and the
# named test must fail on it (and pass on the real tree, which the main run shows).
#   deploy/harness/tests/mutants.sh
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
T=$(mktemp -d)
trap 'rm -rf "$T"' EXIT
pass=0 fail=0

# mut ID TEST FILE OLD NEW: FILE (relative to deploy/) with the literal OLD replaced by NEW
mut() {
  local id=$1 test=$2 file=$3 old=$4 new=$5 d=$T/$1
  cp -r "$ROOT" "$d"
  python3 - "$d/$file" "$old" "$new" <<'PY' || { echo "FAIL $id: the mutation does not apply"; fail=$((fail + 1)); return; }
import sys
p, old, new = sys.argv[1:]
s = open(p).read()
if old not in s:
    sys.exit(1)
open(p, "w").write(s.replace(old, new, 1))
PY
  # the copy's tests import the copy's files (paths are relative to the test file)
  if (cd "$d/harness/tests" && python3 -m unittest -q "test_harness.$test" >"$d.log" 2>&1); then
    echo "FAIL $id: $test still passes with $file broken"
    fail=$((fail + 1))
  else
    echo "PASS $id: $test bites"
    pass=$((pass + 1))
  fi
}

mut M1 ClaudeAccounts.test_one_provider_per_account_running_the_wrapper \
  harness/plugins/model-providers/claude-accounts/__init__.py \
  'client_kwargs["command"], client_kwargs["args"] = wrapper, [account]' 'pass'
mut M2 ClaudeAccounts.test_one_provider_per_account_running_the_wrapper \
  harness/plugins/model-providers/claude-accounts/__init__.py 'profile.process_command_env_vars = ()' 'pass'
mut M3 ClaudeAs.test_token_goes_by_env_never_argv_and_each_account_has_its_own_config_dir \
  harness/bin/claude-as 'unset ANTHROPIC_API_KEY ANTHROPIC_AUTH_TOKEN' ':'
mut M4 ClaudeAs.test_refuses_bad_names_missing_tokens_and_self_hosted_sources \
  harness/bin/claude-as "  '{')" "  'never')"
mut M5 CockpitCards.test_a_closed_or_later_card_is_edited_without_buttons \
  harness/plugins/cockpit-cards/__init__.py '+ "</b>", []' '+ "</b>", [[("x", "nvc:x:1")]]'
mut M6 CockpitCards.test_never_sends_what_closed_before_delivery_nor_a_first_run_backlog \
  harness/plugins/cockpit-cards/__init__.py 'if card.get("state") != "open":' 'if False:'
mut M7 CockpitCards.test_nothing_is_relayed_unless_the_cockpit_hands_cards_to_hermes \
  harness/plugins/cockpit-cards/__init__.py 'if result.get("via") != "hermes":' 'if False:'
mut M8 KeepAlive.test_a_dead_claude_is_revived_once_then_nudged_once_at_its_prompt \
  harness/scripts/keep_alive.py 'state_now in ("done", "idle", "failed") and not s.get("need")' \
  'state_now in ("done", "idle", "failed", "needs-you")'
mut M9 KeepAlive.test_a_session_stuck_at_its_limit_moves_after_the_grace_to_the_best_allowed_account \
  harness/scripts/keep_alive.py 'if a.get("reserved") or ' 'if '
mut M10 KeepAlive.test_a_working_or_asking_session_is_left_alone \
  harness/scripts/keep_alive.py '        if state_now == "failed":' '        if state_now in ("failed", "needs-you"):'
mut M11 KeepAlive.test_silent_at_night harness/scripts/keep_alive.py 'if lines and not night(' 'if lines or night('
mut M12 HermesOps.test_github_is_get_only_and_the_token_never_follows_a_redirect \
  harness/bin/hermes_ops_mcp.py 'with urllib.request.urlopen(e.headers["Location"], timeout=60) as r:' \
  'with urllib.request.urlopen(urllib.request.Request(e.headers["Location"], headers=req.headers), timeout=60) as r:'
mut M13 HermesOps.test_memory_is_read_only_confined_and_redacted harness/bin/hermes_ops_mcp.py \
  'if not path.startswith(os.path.realpath(root) + os.sep):' 'if False:'
mut M14 HermesOps.test_redaction_covers_the_token_shapes harness/bin/hermes_ops_mcp.py \
  'r"github_pat_[A-Za-z0-9_]{20,}",' ''
mut M15 VaultGate.test_a_down_api_wakes_once_in_six_hours_never_reads_as_empty \
  harness/scripts/vault_commands_gate.py 'if time.time() - last < ALERT_EVERY_S:' 'if True:'
mut M16 Configure.test_managed_keys_replace_whole_sections_and_leave_the_rest harness/configure.py \
  'set_path(cfg, "platforms.telegram.enabled", False)' 'set_path(cfg, "platforms.telegram.enabled", True)'
mut M17 HermesMcpAgentMode.test_agent_mode_has_the_vault_and_the_log_to_read_only claude/bin/hermes_mcp.py \
  '"agent": {"telegram_send", "remember", "log_exchange"},' '"agent": {"log_exchange"},'

mut M18 CockpitCards.test_nothing_is_relayed_unless_the_cockpit_hands_cards_to_hermes \
  harness/plugins/cockpit-cards/__init__.py 'return min(BACKOFF_MAX_S, poll_s * 2 ** min(self.failures, 10))' 'return poll_s'

echo "== $pass passed, $fail failed"
[ "$fail" = 0 ]
