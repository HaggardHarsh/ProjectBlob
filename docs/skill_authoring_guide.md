# 📖 Skill Authoring Guide

> How to create custom Skill Pills for Project Blob

---

## Overview

Skill Pills are `.skill.yaml` files that teach Blob new capabilities. When you drag a skill file onto Blob, it "eats" the pill, registers the new tools, and can use them in conversations.

## Skill File Format

Every skill pill is a YAML file with the following structure:

```yaml
skill:
  # ─── Required Fields ───
  name: "My Custom Skill"                  # Human-readable name
  version: "1.0.0"                          # Semantic version
  description: "What this skill does"       # One-line description
  
  # ─── Optional Metadata ───
  author: "YourName"                        # Skill author
  color: "#FF5722"                          # Hex color (Blob tints this color)
  icon: "wrench"                            # Icon identifier
  
  # ─── Permissions ───
  permissions:                              # What the skill can access
    - filesystem.read                       # Read files
    - filesystem.write                      # Write files
    - shell.execute                         # Run shell commands
    - network.http                          # Make HTTP requests
  
  # ─── Trigger Phrases ───
  triggers:                                 # Natural language triggers
    - "do the thing"
    - "run my tool"
  
  # ─── Tools ───
  tools:
    - name: "tool_name"                     # Unique tool identifier
      description: "What this tool does"    # For LLM tool selection
      command: "echo 'hello {name}'"        # Shell command to execute
      args:                                 # Command arguments
        - name: "name"
          description: "Your name"
          required: true
          default: "World"
  
  # ─── Response Template ───
  response_template: |                      # How Blob formats the output
    Here's the result: {result}
  
  # ─── Emote Mapping ───
  emote_on_success: "HAPPY"                 # Emote when skill succeeds
  emote_on_failure: "CONFUSED"              # Emote when skill fails
```

## Permissions

Skills run inside the OpenShell sandbox. You must declare all required permissions:

| Permission | Description | Risk Level |
|-----------|-------------|-----------|
| `filesystem.read` | Read files from disk | Low |
| `filesystem.write` | Write/create/delete files | Medium |
| `shell.execute` | Execute shell commands | High |
| `network.http` | Make outbound HTTP requests | Medium |

> ⚠️ **Security Note**: Skills with `shell.execute` or `filesystem.write` permissions require user confirmation before first use.

## Tool Arguments

Arguments use `{name}` syntax in commands. They're replaced at runtime:

```yaml
tools:
  - name: "greet"
    command: "echo 'Hello, {name}! Today is {day}.'"
    args:
      - name: "name"
        description: "Person to greet"
        required: true
      - name: "day"
        description: "Day of the week"
        required: false
        default: "today"
```

## Available Emotes

Your skill can suggest emotes for Blob to display:

| Emote | When to Use |
|-------|-------------|
| `IDLE` | Default state |
| `HAPPY` | Successful result |
| `TIRED` | Long-running task |
| `EXCITED` | Great result |
| `THINKING` | Processing |
| `OFFER_COFFEE` | User needs a break |
| `CELEBRATE` | Major achievement |
| `SHY` | Offering suggestion |
| `SLEEPING` | Nothing happening |
| `EATING` | Ingesting new skill |
| `CONFUSED` | Error or unknown |
| `PROUD` | Completed complex task |
| `WORRIED` | Detected issue |
| `PLAYFUL` | Fun interaction |

## Examples

### System Monitor Skill

```yaml
skill:
  name: "System Monitor"
  version: "1.0.0"
  description: "Check CPU, memory, and disk usage"
  color: "#4CAF50"
  permissions:
    - shell.execute
  triggers:
    - "system status"
    - "how's my computer"
    - "cpu usage"
    - "memory usage"
  tools:
    - name: "cpu_usage"
      description: "Get current CPU usage"
      command: "top -bn1 | grep 'Cpu(s)' | awk '{print $2}'"
    - name: "memory_usage"
      description: "Get memory usage"
      command: "free -h | grep Mem"
    - name: "disk_usage"
      description: "Get disk usage"
      command: "df -h / | tail -1"
  emote_on_success: "HAPPY"
```

### Note Taker Skill

```yaml
skill:
  name: "Quick Notes"
  version: "1.0.0"
  description: "Save and retrieve quick notes"
  color: "#FFC107"
  permissions:
    - filesystem.read
    - filesystem.write
  triggers:
    - "take a note"
    - "save this"
    - "show my notes"
    - "remember this"
  tools:
    - name: "save_note"
      description: "Save a quick note"
      command: "echo '[{timestamp}] {note}' >> ~/.blob_notes.txt"
      args:
        - name: "note"
          description: "The note to save"
          required: true
        - name: "timestamp"
          description: "Current timestamp"
          required: false
          default: "$(date +%Y-%m-%d_%H:%M)"
    - name: "show_notes"
      description: "Show recent notes"
      command: "tail -10 ~/.blob_notes.txt 2>/dev/null || echo 'No notes yet!'"
  emote_on_success: "PROUD"
```

## Installing a Skill

1. **Drag & Drop**: Drag the `.skill.yaml` file onto the Blob overlay
2. **CLI**: `blob-backend --install-skill path/to/skill.yaml`
3. **Skills Directory**: Place in the `skills/` folder (auto-detected on startup)

## Troubleshooting

- **Skill not loading**: Check YAML syntax with `python -c "import yaml; yaml.safe_load(open('skill.yaml'))"`
- **Permission denied**: Ensure required permissions are declared in the skill file
- **Command fails**: Test the command manually in a terminal first
- **Blob doesn't react**: Check if the skill triggers match your natural language input
