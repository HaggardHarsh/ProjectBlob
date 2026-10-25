# Skill authoring guide

Blob skills add tools that the assistant can execute. Built-in Python tools and
installable YAML command tools share a registry, argument validation, privacy
controls, execution deadlines, and result history.

At startup Blob loads its packaged `blob/data/skills/` definitions and then
`~/.blob/skills/`. The repository's `skills/` directory contains matching examples.
Set `BLOB_SKILLS_DIR_PATH` to choose another installation directory. A custom
skill with the same slug overrides the packaged definition.

Drag a `.skill.yaml` file onto Blob, use `/skills install <file>` in chat, or run
`blob-backend --install-skill path/to/example.skill.yaml`. Installation validates
the definition and saves a private copy so it survives restart. Installation
feedback reports version and permission changes, and explains known runtime
blocks. A valid definition can be **installed but blocked**, for example when
Bubblewrap or an approved project is missing.

## Define a skill

Each YAML tool is registered as `<skill_slug>.<tool_name>`. This example exposes
`system_monitor.disk_usage`:

```yaml
skill:
  name: System Monitor
  description: Inspect disk capacity and local system information
  version: "1.0.0"
  author: Example Author
  color: "#4FC3F7"
  icon: hard-drive
  permissions:
    - shell.execute
  triggers:
    - disk usage
    - system status
  examples:
    - Show remaining storage
  tools:
    - name: disk_usage
      description: Show disk usage for a path
      command: "df -h {path}"
      args:
        - name: path
          required: false
          default: "."
  response_template: "Disk usage: {result}"
  emote_on_success: HAPPY
  emote_on_failure: CONFUSED
```

The `skill` mapping requires a name, description, and nonempty `tools` list.
Tool names use lowercase letters, numbers, and underscores. Declare every command
`{placeholder}` in `args`. The executable must be fixed. `response_template` can
use `{result}` and arguments shared by every tool in the skill.

Version defaults to `"0.0.0"` and must use `major.minor.patch`, optionally with a
prerelease/build suffix. Quote versions and hex colors in YAML. Author, icon,
color, version, examples, and triggers are retained for inspection; icon and color
are informational. Colors must use six hex digits after `#`.

## Discovery and explicit execution

Blob matches installed tools against the current user's request using skill/tool
names, trigger phrases, examples, and description keywords. `triggers` and
`examples` can be declared at skill or tool level. Each list supports up to 32
nonempty phrases of at most 500 characters. Prefer specific phrases such as
`recent commits` over generic phrases such as `search for`.

Explicit names match on word boundaries. Examples and triggers match whole
phrases; single-word phrases require an action request. Description matching
requires an action and at least two shared topic keywords. Explanation-only and
negated requests do not select installed tools. Matching supplies candidate tools
to the model; it does not run them. Argument validation, request authorization,
disabled-tool controls, and isolation still apply at execution. Retrieved memory,
webpages, and tool results cannot expand the current request's tool authority.

`/skills run` bypasses model selection and makes no model request:

```text
/skills
/skills system_monitor.disk_usage
/skills run system_monitor.disk_usage {"path":"."}
/skills history
```

The model sees the same argument contracts as direct execution. Unknown
arguments and incorrect types fail before execution. History retains the latest
30 runs in this session: tool name, success, duration, and invocation source.
It excludes raw arguments and outputs. Camera tools require explicit terminal
commands and are excluded from model discovery.

## Select a project

Commands run inside an approved folder. Approve a specific project, then select
it when more than one folder is approved:

```text
/privacy allow /path/to/project
/skills project /path/to/project
/skills project
/skills run git_status {}
/skills run git_status {"project":"/path/to/another/approved/project"}
/skills project clear
```

Quote paths containing spaces when using `/skills project`. Selection persists in
the local privacy settings. With one approved folder and no selection, that folder
is the default. With multiple approved folders, commands require a selection or an
explicit `project` argument. Revoking the selected folder clears the selection;
missing or unapproved project directories block execution.

Every YAML command tool and the built-in `git_status` and `shell_command` tools
accept the reserved optional string argument `project`. Do not declare it in YAML
`args` or use it as a command placeholder. It changes the working directory for
that invocation without changing the persistent selection. Model-supplied project
paths must come from the active selection or the current user request. Paths are
resolved and checked against approved folders, including symlink targets.

Relative command paths, including the bundled YAML file-search defaults, use the
selected project. The separate built-in `file_search` tool searches approved
folders and has its own `query` argument.

## Diagnose blocked tools

```text
/skills doctor
/skills doctor git_status
```

The tool list and individual inspection show basic `ready` or `blocked` status.
The doctor command also probes command isolation once with a harmless echo. It
reports missing commands, missing Bubblewrap, unavailable or ambiguous projects,
disabled tools, privacy/cloud blocks, and files that failed to load at startup.
It does not execute installed skill commands or contact a network service.
`ready` reports local prerequisites; the tool can still fail on its actual input.

## Inspect, update, roll back, and uninstall

```text
/skills packages
/skills info system_monitor
/skills preview /path/to/system_monitor.skill.yaml
/skills install /path/to/system_monitor.skill.yaml
/skills rollback system_monitor
/skills uninstall system_monitor
```

`packages` lists YAML skill IDs, versions, authors, and bundled/installed origin.
`info` shows retained metadata, commands, permissions, tool names, source path,
content hash, and rollback availability. Use the **skill ID** for these management
commands and the full **tool name** for execution.

Preview validates an update and shows its old/new version, added/removed
permissions, and added/removed/changed tools without changing files or the live
registry. Installation reports the same changes. Explicit installs can replace
the same version or install a lower version; versions identify updates rather
than imposing an upgrade-only policy.

Each changed installation retains one previous definition in the private
`<skills-directory>/.rollback/` directory. Snapshots survive restart and are not
loaded as active skills. Rollback revalidates the snapshot and exchanges it with
the current version, so a second rollback can undo the first. Reinstalling
identical content preserves the snapshot. Validation failures leave the active
definition intact.

Uninstall removes a custom definition, its active tools, and its rollback copy.
Removing a custom override restores the packaged skill. Packaged definitions and
definitions loaded from external directories cannot be uninstalled here; use
`/privacy disable <tool>` for those tools. Installation, rollback, and uninstall
are blocked during privacy pause. Inspection and preview remain available.

## Typed arguments

Arguments default to `type: string`. Supported types are `string`, `integer`,
`number`, and `boolean`; arguments can include descriptions, enum choices, and
numeric `minimum`/`maximum` bounds:

```yaml
- name: minutes
  description: Files modified within this many minutes
  type: integer
  required: false
  default: 60
  minimum: 1
  maximum: 10080
```

Use the corresponding JSON type: `{"minutes":60}` is numeric;
`{"minutes":"60"}` is a string. Booleans and nonfinite numbers cannot stand in
for numbers. Defaults and enum choices are validated at installation.

## Command policy and isolation

Command templates are split into argument tokens **before** substitution and run
without a shell. An argument containing shell syntax cannot add another command.
Pipelines, redirections, command separators, and `filesystem.write` are unsupported.

| Permission | Command policy |
|------------|----------------|
| `filesystem.read` | `find`, `grep`, `ls`, `cat`, `head`, `tail` |
| `shell.execute` | Git status/log/diff/stash list and branch listing; `echo`, date display, `df`, `free`, `uname`, Python version |
| `network.http` | HTTPS `curl` definitions validate for compatibility, but command isolation blocks their execution |

In the normal backend, commands require Linux Bubblewrap. It creates an isolated
namespace, mounts approved folders read-only, clears the environment, masks common
credential files, and disables network access. Commands fail closed when isolation
is unavailable. The built-in Python network tools use separate controlled paths.
The bundled YAML weather definitions are compatibility examples and report
`installed but blocked`; use the built-in `weather` tool for weather requests.

Commands have a 10-second deadline and retain at most 8,000 bytes of output,
including an omission marker when truncated. Git optional index writes, external
diff/text conversion helpers, signature helpers, and pagers are disabled or
rejected. Branch modifications, output-file arguments, unsafe find actions, and
clock setting are rejected. These rules apply to YAML and built-in command tools.

Other tools default to a 15-second deadline; screen capture allows 120 seconds
for the desktop portal, and camera operations allow 45 seconds. Cancelling an
asynchronous tool cancels awaited work. A Python function already running in a
worker thread may finish afterward; command processes have their own deadline
and are killed on timeout or a privacy-settings change. Completed tool outputs
are limited to 8,000 UTF-8 bytes before model use.

Files must be regular UTF-8 `.skill.yaml` files no larger than 64 KiB. Blob rejects
unsupported permissions, duplicate tool names, unsafe templates, and invalid
argument definitions before registration. Install trusted definitions: allowed
commands can read approved project data, and their results can enter cloud chat
when cloud assistance is enabled.
