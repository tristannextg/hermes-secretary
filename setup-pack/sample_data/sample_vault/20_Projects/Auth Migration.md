---
type: project
status: active
project: Auth Migration
topics:
  - authentication
  - security
tags:
  - project/auth
agent:
  indexed_at:
  last_summary:
  suggested_tags: []
---

# Auth Migration

Current focus: migrate legacy login paths to the new OAuth-based system without breaking existing sessions.

## Open questions

- How do we rollback safely?
- Which services cache tokens?
- What is the production monitoring story?

## Tasks

- [ ] Review PR for session invalidation #task #work 📅 2026-07-09
- [ ] Write a concept note about auth invariants #task #learning

[@hermes remind me to follow up on auth monitoring next week]
