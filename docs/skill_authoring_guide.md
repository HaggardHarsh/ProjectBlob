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

## Inspect and execute

`/skills` lists built-in and installed tools. `/skills <tool>` shows its argument
contract and declared permissions. `/skills run <tool> <JSON object>` executes
it directly without a model request; for example:

```text
/skills system_monitor.disk_usage
/skills run system_monitor.disk_usage {"path":"/"}
/skills history
```

The model sees these same argument contracts. Built-ins and YAML tools share
validation, deadlines, bounded observations, and a 30-run session history.
Unknown arguments and incorrect types fail before execution. Camera operations
require explicit terminal commands and are excluded from model tool discovery.

## Typed arguments

Arguments default to `type: string`, keeping existing pills compatible. You can
declare `string`, `integer`, `number`, or `boolean`, add a description and enum,
and restrict numeric values with `minimum` and `maximum`:

```yaml
- name: minutes
  description: Files modified within this many minutes
  type: integer
  required: false
  default: 60
  minimum: 1
  maximum: 10080
```

Use the corresponding JSON type when calling a tool: `{"minutes":60}` is a
number; `{"minutes":"60"}` is a string. Boolean flags and nonfinite numbers
cannot stand in for numeric values. Defaults and enum choices are validated at
installation. Command executables must be fixed, and declared permissions must
allow the command before the pill can be installed.

## Command and permission rules

Commands are split into argument tokens before substitutions are applied and
run without a shell. This means a user supplied argument cannot add another
command. Pipelines, redirections, command separators, and `filesystem.write`
are unsupported.

| Permission | Supported commands |
|------------|--------------------|
| `filesystem.read` | `find`, `grep`, `ls`, `cat`, `head`, `tail` |
| `shell.execute` | `git status/log/diff/stash list`, branch listing, `echo`, date display, `df`, `free`, `uname`, Python version |
| `network.http` | `curl -s https://…` |

Commands have a 10 second deadline and retain at most 8,000 bytes of output;
an omission marker identifies truncated results. Git optional index writes,
external diff/text conversion helpers, signature helpers, and pagers are
disabled or rejected. Branch modifications, output-file arguments, unsafe find
actions, and clock setting are rejected. Curl ignores `.curlrc` configuration
and uses HTTPS. These rules apply to both YAML and built-in command tools.

Other tools default to a 15 second deadline; screen capture allows 120 seconds
for the desktop portal, and camera operations allow 45 seconds. Cancelling
an asynchronous tool cancels its awaited work. A Python function already
running in a worker thread may finish afterward; command processes have their
own deadline and are killed on timeout. Screen OCR keeps ownership of its
captured image until the worker finishes and rechecks privacy before returning
text. Completed outputs are limited to 8,000 UTF-8 bytes before model use.

Blob validates files before loading them and rejects unsupported permissions,
duplicate tool names, malformed templates, and files over 64 KiB. The runner
restricts commands but is not an operating system sandbox. Install only files
you trust, since allowed read and network commands can still access data.

To try a bundled example, ask Blob for a repository status after startup, or
inspect the `skills/` directory for valid file search, Git, and weather pills.
