# Urgency bar

An unscheduled alert (outside the 8am, 1pm and 6pm briefs) fires only if at least one is true:

1. A recruiter, hiring manager, or interviewer writes about an application, interview, offer, or asks for materials.
2. A calendar invite lands, moves, or is cancelled for today or tomorrow morning.
3. A principal, a client, or a counterparty on a live deal (see config/people.md) asks a question or sets a deadline.
4. A contract, NDA, offer letter, or payment request arrives for signature or action.
5. Anything with a deadline inside 24 hours that no prior brief mentioned.

Everything else waits. Alerts are one email to the owner, subject "CoS alert: <item>", body under 120 words, draft reply in outbox/ if warranted.

## Tuning
The owner replies "not urgent" or "always urgent" to any alert. CoS runs `skill-feedback` against this file and shows the diff before saving. CoS never edits this file on its own.

## Watcher hours
Hourly, 7am to 10pm local time. Silent passes write one line to `log/` and send nothing.

## Lessons
