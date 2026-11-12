# Agent registry

Types CoS may spawn through the Agent tool. Built-ins first, then custom files in this folder.

| Type | Use for |
|---|---|
| `general-purpose` (built-in) | research, multi-step work, anything with no better fit |
| `Explore` (built-in) | find files or facts across the workspaces without editing |
| `Plan` (built-in) | design an implementation before building it |
| `skill-writer` | turn a recurring task into a skill folder under `skills/` |

## Adding a type
Write `agents/<name>.md` with frontmatter `name`, `description`, `tools`. Keep the prompt to the procedure and output format. Add a row above. Symlink into `~/.claude/agents/` so every workspace sees it.
