---
name: cockpit-help
description: Answer "how do I … in the cockpit", "what does key X do", "where is Y" and every other question about Tristan's nvim cockpit (keys, agent list, inbox, finish line, accounts, the Session API) from the cockpit's own guide, never from memory.
version: 1.0.0
metadata:
  hermes:
    tags: [cockpit, help]
    related_skills: [hand-off, keep-alive]
---

# Cockpit help

The cockpit changes every few days, so the answer comes from its documentation as deployed, not
from what you remember.

## Procedure

1. If the `cockpit` tools have `guide_get`, call it with the question's topic: it is the guide of
   the cockpit as deployed now. Otherwise use `cockpit_doc` (the `ops` tools): `doc: README` for
   keys and features, `doc: API` for the Session API, with a short `query` ("finish line",
   "switch account", "inbox dismiss"). Without a query it lists the headings: use that when the
   first query finds nothing.
2. Answer with the exact key or command as the doc writes it (`Alt-i`, `<leader>an`, `M`), and
   one sentence of what it does. Quote the doc's own words for anything subtle.
3. If the doc does not cover it, say so plainly ("the guide doesn't say how to …") and offer to
   find out by handing the question to a cockpit session (`hand-off`). Never invent a key.
4. If `cockpit_doc` says its copy was shipped long ago (more than a week) and the answer matters,
   say that it may be out of date.

## Pitfalls

- The secretary (`desk`) the README describes is retired: Hermes (you) replaced it. Its
  `desk-*` commands are not yours.
- "Accounts" in the cockpit are Claude logins (work, Duxalpha1/dx1, Duxalpha2/dx2, private/prv,
  bernd/brn, alienware/alw); the account policy decides which one a chat runs on.
