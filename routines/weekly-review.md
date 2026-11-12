Weekly review, Sunday evening local time. Read agents/cos.md first.

Inputs: this week's briefs/ and alerts, log/<YYYY-MM>.md, outbox/ (every draft and its age), config/urgency.md.

Produce briefs/<today>/weekly.md with these sections, one line per item:
- Moved: what got done or answered this week.
- Stalled: asks that appeared in three or more briefs without action, with how many days each has been open.
- Drafts awaiting the owner: each outbox draft with its age in days.
- Patterns: what the watcher held or raised, alerts that were wrong in either direction, repeated items.
- Next week: the first three things, in order.

Write each lesson (a rule that would have prevented a miss) as a proposed edit to the file that caused it. Put the edits on branch review/<date>, push, and open a PR. Never merge it. Commit the review to main, log one line, email it to the owner's own address only, subject "CoS weekly: <top item>". Under 350 words.
