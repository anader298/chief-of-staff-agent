Weekly optimizer, Wednesday 3am local time. Audit everything CoS does for speed, spend, and clutter, and propose changes. Never apply them.

Inputs: git history and repo size (`git count-objects -vH`, `du -sh` per top folder), briefs/ and log/ (how many runs, how many were quiet, how long the briefs are, repeated items), routines/ prompts (model choice, hours, overlap), outbox/ (drafts older than 7 days).

Produce briefs/<date>/optimizer.md with: (1) spend: which routines or models cost the most relative to what they produced, with a concrete downgrade or schedule change and the saving in plain words; (2) speed: prompts or steps that are slow or redundant; (3) GitHub: repo size, files that should be removed, branch and PR hygiene; (4) one change to make this week, with the exact edit.

Put proposed edits on branch optimizer/<date>, push, open a PR with `gh pr create` if available. Commit the brief to main. Email to the owner's own address only, subject "CoS optimizer: <one change>". Under 300 words.
