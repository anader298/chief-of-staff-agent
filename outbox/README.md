# Outbox

Every draft to anyone other than the owner lands here as `YYYY-MM-DD/<slug>.md`:

```
to: name <address>
subject: ...
mailbox: <label it answers from>
based_on: path or message id
---
body
```

The owner approves by sending it from their own mail client, or by creating `outbox/APPROVED` (`touch outbox/APPROVED`), which unlocks `tools/mail.py send` and `send-draft` for one hour. CoS never sends from here on its own.

Sessions can also stage a draft in the mailbox's Drafts folder with `python3 tools/mail.py draft` (attachments included). Sending still needs the owner.

Real drafts are gitignored in this public repo. See `examples/outbox/` for the format.
