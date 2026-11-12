---
name: skill-feedback
description: Use when the owner corrects or confirms an output that a skill, agent, or config file produced ("no, do X", "always Y", "not urgent"). Folds the lesson into the right file with approval.
---

# skill-feedback

Turns a correction into a durable rule in the file that caused the behavior.

## Steps
1. Identify the source: which skill (`skills/<name>/SKILL.md`), agent (`agents/<name>.md`), or config (`config/urgency.md`, `config/people.md`) produced the output being corrected. If unsure, ask one question.
2. Write the lesson as one line: `- YYYY-MM-DD: <rule>. Why: <the owner's words, short>.`
3. Append it under a `## Lessons` heading at the bottom of that file (create the heading if missing). If the lesson contradicts an existing step, edit the step too.
4. Show the diff and wait for approval before saving. Never save silently.
5. Log one line in `log/YYYY-MM.md`.

## Rules
- One lesson per correction. Do not generalize beyond what the owner said.
- If the same lesson is corrected twice, move it from Lessons into the main steps.
- Do not touch files outside this repo.
