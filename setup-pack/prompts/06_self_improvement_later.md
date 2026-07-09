# Prompt 06: Controlled self-improvement later

Do not implement this until the core system has been running safely.

The agent may propose improvements but may not apply them automatically.

Allowed self-improvement outputs:

- new prompt suggestions
- new skill drafts
- proposed taxonomy changes
- proposed briefing template changes
- weekly failure analysis
- repeated correction analysis

Write proposals under:

```text
80_Agent/Suggestions/Self Improvement/
```

Never automatically change:

- production prompts
- container permissions
- backup settings
- vault write scope
- secrets handling
- systemd timers
- Docker Compose security options

Generate a weekly review:

```text
80_Agent/Briefings/Weekly Agent Review/YYYY-Www.md
```

Include:

- what worked
- what failed
- bad suggestions
- notes that could not be classified
- repeated user corrections
- proposed skill improvements
- proposed taxonomy changes
- changes waiting for approval
