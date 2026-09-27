# Skill authoring guide

Blob loads declarative `.skill.yaml` files from the bundled `skills/` directory
and `~/.blob/skills/` at startup. You can also drag one onto the overlay or run
`blob-backend --install-skill path/to/example.skill.yaml`. Dragged and CLI
installed files are copied to `~/.blob/skills/` so they survive a restart.
Set `BLOB_SKILLS_DIR_PATH` to use another installed skill directory.

Each tool is registered as `<skill_slug>.<tool_name>`. For example, the skill
below exposes `system_monitor.disk_usage` to Blob's tool loop:

```yaml
skill:
  name: System Monitor
  description: Show local system information
  version: "1.0.0"
  permissions:
    - shell.execute
  triggers:
    - system status
  tools:
    - name: disk_usage
      description: Show disk usage for a path
      command: "df -h {path}"
      args:
        - name: path
          required: false
          default: "/"
  response_template: "Disk usage: {result}"
  emote_on_success: HAPPY
  emote_on_failure: CONFUSED
```

The `skill` mapping needs a name, description, and nonempty `tools` list.
Each tool needs a lowercase identifier and a command. Declare every `{name}`
placeholder in `args`; `required` arguments must be provided when Blob calls
the tool. `response_template` can use `{result}` and arguments shared by all
tools in the pill. Optional `triggers`, `version`, `author`, `color`, and `icon`
fields can be included. Color and icon metadata are currently informational.

## Command and permission rules

Commands are split into argument tokens before substitutions are applied and
run without a shell. This means a user supplied argument cannot add another
command. Pipelines, redirections, command separators, and `filesystem.write`
are unsupported.

| Permission | Supported commands |
|------------|--------------------|
| `filesystem.read` | `find`, `grep`, `ls`, `cat`, `head`, `tail` |
| `shell.execute` | `git status/log/branch/diff/stash list`, `echo`, `date`, `df`, `free`, `uname` |
| `network.http` | `curl -s https://…` |

Commands have a 10 second timeout and output is capped at 4,000 characters.
Blob validates files before loading them and rejects unsupported permissions,
duplicate tool names, malformed templates, and files over 64 KiB. The runner
restricts commands but is not an operating system sandbox. Install only files
you trust, since allowed read and network commands can still access data.

To try a bundled example, ask Blob for a repository status after startup, or
inspect the `skills/` directory for valid file search, Git, and weather pills.
