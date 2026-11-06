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

CA=harness/plugins/model-providers/claude-accounts/__init__.py
CC=harness/plugins/cockpit-cards/__init__.py
mut M19 ClaudeAccounts.test_auto_skips_a_full_account_without_trying_it $CA \
  '                if self.full_until(a, now):' '                if False:'
mut M20 ClaudeAccounts.test_auto_takes_the_first_in_order_and_a_reset_window_counts_as_headroom $CA \
  'and reset > now:' ':'
mut M21 ClaudeAccounts.test_a_refusal_marks_the_account_until_its_reset_and_the_next_one_serves $CA \
  'self.marks[account] = {"until": until,' 'self.marks[account + "-x"] = {"until": until,'
mut M22 ClaudeAccounts.test_only_a_limit_or_a_login_moves_on_and_never_after_output $CA \
  'if started or self.closed or status not in SWITCH_ON:' 'if self.closed or status not in SWITCH_ON:'
mut M23 ClaudeAccounts.test_only_a_limit_or_a_login_moves_on_and_never_after_output $CA \
  'SWITCH_ON = {429: "limit", 402: "limit", 401: "login"}' 'SWITCH_ON = {429: "limit", 402: "limit", 401: "login", 529: "limit"}'
mut M24 ClaudeAccounts.test_all_out_is_one_429_with_the_earliest_reset_and_no_request $CA \
  'return min(ends) if ends else None' 'return max(ends) if ends else None'
mut M25 ClaudeAccounts.test_all_out_is_one_429_with_the_earliest_reset_and_no_request $CA \
  '                if a in tried or self.marked_until(a, now):' '                if a in tried:'
mut M26 ClaudeAccounts.test_planned_switch_notices_are_kept_out_and_everything_else_shown $CA \
  'return m["old"].lower() in chain and m["new"].lower() in chain' 'return True'
mut M27 ClaudeAccounts.test_planned_switch_notices_are_kept_out_and_everything_else_shown $CA \
  '        if quiet:' '        if False:'
mut M28 CockpitCards.test_recorded_cards_only_questions_and_unfixable_failures_reach_the_phone $CC \
  '        if kind not in self.rule["send"]:' '        if False:'
mut M29 CockpitCards.test_recorded_cards_only_questions_and_unfixable_failures_reach_the_phone $CC \
  '            if ftype in self.rule["held_failures"]:' '            if False:'
mut M30 CockpitCards.test_recorded_cards_only_questions_and_unfixable_failures_reach_the_phone $CC \
  'if self.rule.get("held_when_kept_alive") and self.kept_alive(vm, sid):' 'if False:'
mut M31 CockpitCards.test_recorded_cards_only_questions_and_unfixable_failures_reach_the_phone harness/configure.py \
  '"send": ["blocking", "failure"],' '"send": ["blocking", "failure", "limit"],'
mut M32 CockpitCards.test_one_message_per_chat_and_episode_edited_in_place $CC \
  '            if t and t.get("msg") is not None:' '            if False:'
mut M33 CockpitCards.test_one_message_per_chat_and_episode_edited_in_place $CC \
  'if not t or t.get("card") != cid or t.get("msg") is None:' 'if not t or t.get("msg") is None:'
mut M34 CockpitCards.test_a_chat_tristan_asked_about_gets_every_card_through $CC \
  'and float(w.get("until") or 0) > now' 'and False'
mut M35 CockpitCards.test_a_watched_pr_is_told_once_when_ready_then_the_watch_ends $CC \
  'if pr.get("draft") or not ci.get("total") or ci.get("fail") or ci.get("pending"):' \
  'if pr.get("draft") or not ci.get("total") or ci.get("fail"):'
mut M36 CockpitCards.test_a_watched_pr_is_told_once_when_ready_then_the_watch_ends $CC \
  '            ended.append(w)
            done += 1' '            done += 1'
mut M37 CockpitCards.test_messages_reviews_and_limits_are_held_with_why $CC \
  '                self.hold(card, why, now)' '                pass'
mut M38 HermesOps.test_tell_me_watches_name_a_pr_or_a_chat_and_say_who_asked harness/bin/hermes_ops_mcp.py \
  '        if repo not in REPOS:' '        if False:'

OPS=harness/bin/hermes_ops_mcp.py
NVD=harness/scripts/neovim_docs.py
mut M39 NeovimDocs.test_a_tag_gives_its_entry_up_to_the_next_one_then_near_tags_and_lines $OPS \
  '                if text_seen:' '                if False:'
mut M40 NeovimDocs.test_words_find_lines_where_the_file_name_counts_and_the_setup_comes_first $OPS \
  'score = sum(w in low or w in where for w in words)' 'score = sum(w in low for w in words)'
mut M41 NeovimDocs.test_words_find_lines_where_the_file_name_counts_and_the_setup_comes_first $OPS \
  'NVIM_FIRST = ("keymaps.md", "cockpit/guide.md", "cockpit/README.md", "cockpit/", "nvim/", "plugins/", "")' \
  'NVIM_FIRST = ("",)'
mut M42 NeovimDocs.test_words_find_lines_where_the_file_name_counts_and_the_setup_comes_first $OPS \
  'r[1].startswith((scope + "/", f"plugins/{scope}/"))' 'r[1].startswith((scope, f"plugins/{scope}"))'
mut M43 NeovimDocs.test_reading_is_confined_and_stale_or_missing_docs_say_so $OPS \
  'if time.time() - built > NVIM_STALE_S:' 'if False:'
mut M44 NeovimDocs.test_a_failed_build_keeps_the_last_good_tree_and_says_why $NVD \
  '        return 1
    old = None' '    old = None'
mut M45 NeovimDocs.test_the_build_writes_the_tree_its_index_and_what_does_not_match_a_pin $NVD \
  '                            fence = not fence' '                            pass'
mut M46 NeovimDocs.test_the_build_writes_the_tree_its_index_and_what_does_not_match_a_pin $NVD \
  'for n, p in plugins.items() if p["commit"] != p["lock"]]' 'for n, p in plugins.items() if False]'
mut M47 NeovimDocs.test_a_tag_gives_its_entry_up_to_the_next_one_then_near_tags_and_lines $OPS \
  'while not md and start > 1' 'while False and start > 1'

echo "== $pass passed, $fail failed"
[ "$fail" = 0 ]
