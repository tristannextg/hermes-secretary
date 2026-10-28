---
name: ci-status
description: Say whether a PR of Arnold-NextG/nxguide is green, why its checks are pending or stuck, what failed and where, read-only. Use for "is #4781 green", "why is CI red on my PR", "did the e2e pass", or before telling Tristan anything passed CI.
version: 1.0.0
metadata:
  hermes:
    tags: [github, ci]
    related_skills: [worklog, hand-off]
---

# CI status (read-only)

Your GitHub access is the `gh_*` tools (GET only, a read-only token). You never comment, label,
re-run, approve or merge (P1, P4). Naive answers are wrong on this repo; these rules come from
Tristan's check-pr-ci skill.

## Procedure

1. `gh_pr {number}`: base branch, head sha, draft, `mergeable_state`, auto-merge.
2. `gh_runs {number}`: which workflows ran on the head sha, their jobs and failed steps.
3. Which CI is real depends on the base:
   - base **main**: the gate is `Build Test Deploy` (bake.yaml: build/test/e2e), `gdscript-lint`,
     `go-fmt`, `db_test`, plus the four unfiltered workflows;
   - any other base: only the four unfiltered ones run (`FMIS: npm lint`, `FMIS: Build & Test`,
     `Protobuf: Breaking Changes`, `PR: suggest matching issue`). Never call that "CI green":
     name which workflows ran.
   - A Markdown-only PR never reports the required checks (bake.yaml ignores `**/*.md`): it waits
     forever; that is expected.
4. Read counts, not conclusions: for a test job, `gh_job_log {job_id, grep: "passed|failed|error"}`
   and report "N failed, M passed". A job that exits 0 can have skipped most tests.
5. `cancelled` usually means a later push superseded the run (every push cancels the one in
   flight): not a failure. Look at the newest sha's runs.
6. A job queued for a long time on `[self-hosted, Linux, X64, hp-laptop]` waits for runner VMs on a
   laptop that may be asleep: queued, not broken.
7. Answer: green / red / pending, then the evidence (workflow, job, counts, the failing step's
   lines, the run URL). If a test failed, say whether the same step failed on an earlier sha
   (`gh_runs {sha}` of the previous commit) before blaming the change.

## Limits

- The token cannot read check runs or commit statuses (the required-context view of ruleset
  19962109). When the question is "why is it blocked although everything ran", say that this view
  is not readable to you and that `mergeable_state: blocked` is all you can see; until Tristan
  extends the token (deploy/harness/README.md, "Tristan's steps").
- Logs are redacted before you see them; never paste a line that still looks like a secret.
