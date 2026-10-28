---
name: hand-off
description: Hand a piece of real work (code, a fix, a review, an investigation in a repository, infrastructure) to a new cockpit session with a proper brief, on the least busy VM and an account the policy allows, then tell Tristan where it runs. Use whenever Tristan asks for something that needs a repository, a shell or more than a few minutes of agent work.
version: 1.0.0
metadata:
  hermes:
    tags: [cockpit, delegation]
    related_skills: [keep-alive, cockpit-help]
---

# Hand-off: real work goes to a cockpit session

You never change code or infrastructure yourself (P10). You write the brief and start the session.

## Procedure

1. **Understand the ask.** If the goal, the repository or the scope is unclear, ask Tristan one
   question with numbered options first. A vague brief wastes a whole session.
2. **Gather what the session cannot know**: the issue or PR (`gh_pr`), what Tristan already said
   about it (`session_search`, `memory`), earlier sessions on it (`sessions_list`, their
   `summary`), relevant rulings in the shared memory (`memory_search`).
3. **Pick the VM**: `sessions_list`; among online VMs (dev-1 … dev-4, dev-cloud), the one with the
   fewest sessions in state `working`. Prefer the VM an earlier session on the same topic ran on
   when it is not busy (its worktree is there).
4. **Pick the account**: `policy_get` and `accounts_list`: an account held by that VM, enabled,
   not reserved, not capped, not full, highest priority, then the most headroom. Never `private`
   or another reserved account (P2). If none qualifies, tell Tristan instead of starting.
5. **Write the brief** (the session's first message):

       Goal: <one sentence: the outcome, not the method>
       Context: <issue/PR links, what Tristan said (quote), what is already known or ruled out>
       Scope: <what to touch, what not to>
       Done when: <observable result: tests through the repo's own entry points, CI, a screenshot>
       Rules: open a PR, stay on its branch; never merge; never request reviewers; report back
       with what you built, what ran and its counts, and what is left.
       Asked by Tristan via Hermes, <date time>.

6. **Start it**: `session_start` with `vm`, `account`, `name` (≤ 80 chars, says what it is for),
   `prompt` (the brief), `branch` when it continues a PR, `model` only when Tristan named one;
   `why`: "Tristan asked on Telegram: …".
7. **Report**: the session's name, VM and account in one line, and what you will tell them about
   (the cockpit's cards bring its questions; offer `keep-alive` when they want it to run unattended).

## Pitfalls

- P9: if the work is obviously long (a big refactor, a full test suite), say so and its rough cost
  before starting.
- A `refused` start names its reason (an excluded account, a missing token on that VM): pick
  another VM or account, or tell Tristan; never retry the same call.
