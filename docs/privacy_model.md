# 🔒 Privacy Model

> How Project Blob protects your data

---

## Core Principles

1. **Zero Telemetry**: Blob never sends data to any external server. All processing happens locally on your machine.
2. **Ephemeral Screen Data**: Screen captures are processed in-memory and immediately discarded. They are never written to disk.
3. **Configurable Blind Spots**: The Privacy Shield automatically detects and blocks sensitive applications.
4. **Local-Only Memory**: All memories are stored in a local ChromaDB database under `~/.blob/memory/`.
5. **Opt-In Cloud Burst**: Nebius Serverless is disabled by default. Users must explicitly enable it and accept the data routing policy.

---

## Privacy Shield

### How It Works

The Privacy Shield continuously monitors your active window (every 500ms) and compares it against a configurable blacklist of sensitive applications:

```
┌──────────┐     ┌───────────┐     ┌──────────────┐     ┌─────────────┐
│ Window   │────►│ Blacklist │────►│ Match Found? │──Y──►│ SHIELD ON   │
│ Monitor  │     │ Matcher   │     │              │      │ • Stop OCR  │
│ (500ms)  │     │           │     │              │      │ • Blindfold │
│          │     │           │     │              │──N──►│ • Pause Mem │
└──────────┘     └───────────┘     └──────────────┘      └─────────────┘
```

### Default Blacklist

The following patterns are blocked out-of-the-box:

**Window Title Patterns** (regex):
- `.*[Bb]ank.*` — Banking websites
- `.*[Pp]ay[Pp]al.*` — PayPal
- `.*1[Pp]assword.*` — 1Password
- `.*[Bb]itwarden.*` — Bitwarden
- `.*[Kk]ee[Pp]ass.*` — KeePass
- `.*[Ii]ncognito.*` — Incognito/Private browsing
- `.*[Pp]rivate [Bb]rowsing.*` — Firefox private browsing

**Process Names** (exact match):
- `1password`
- `bitwarden`
- `keepassxc`

### Customizing the Blacklist

Edit `backend_python/data/blacklist.yaml`:

```yaml
privacy_shield:
  window_title_patterns:
    - ".*[Mm]y[Ss]ecret[Aa]pp.*"
  process_names:
    - "my_secret_app"
  custom_patterns:
    - ".*HIPAA.*"
    - ".*medical.*records.*"
```

### What Happens When Shield Activates

1. **Screen Sampler**: Immediately stops capturing screenshots
2. **OCR Processor**: Halts all text extraction
3. **Memory Engine**: Pauses episodic memory capture
4. **Frontend Animation**: Blob puts on a sleeping mask (blindfold)
5. **Audit Log**: Event is logged locally (timestamp + trigger reason, not content)

### Debouncing

Rapid window switches (e.g., Alt-Tab through a banking app) are debounced with a 300ms delay to prevent flicker while ensuring protection activates reliably.

---

## Screen Capture Policy

### What Gets Captured
- Active window screenshot at low resolution (480p)
- Capture frequency: every 30-60 seconds
- Only when Privacy Shield is **inactive**

### What Happens to Captures
1. Screenshot is taken in-memory (PIL/mss)
2. Downscaled to 480p
3. Passed to local OCR (EasyOCR)
4. Text is extracted
5. **Screenshot is immediately deleted from memory**
6. Extracted text is analyzed for workflow patterns
7. Text is then discarded (not stored)

### What Is Never Captured
- Pixel data is never written to disk
- Raw OCR text is never stored long-term
- Only high-level workflow summaries enter memory (e.g., "user was coding in Python for 2 hours")

---

## Memory Privacy

### What Gets Stored
- Summarized interaction history (e.g., "Discussed Python memory leak debugging")
- User preferences inferred from conversations
- Project context (e.g., "Working on ProjectBlob with C++ and Python")
- Skill usage patterns

### What Is Never Stored
- Raw screen captures
- Raw OCR text
- Passwords, tokens, or credentials
- Content from blacklisted applications
- Financial information

### Memory Location
All memory data lives in:
```
~/.blob/memory/chromadb/      # Vector embeddings
~/.blob/memory/episodes/      # Episodic buffer (last N interactions)
```

### Deleting Memories
```bash
# Delete all memories
rm -rf ~/.blob/memory/

# Delete specific memories (future CLI feature)
blob-backend --forget "topic_name"
```

---

## Nebius Cloud Burst (Opt-In)

### Default: Disabled

By default, all LLM inference runs locally on your NVIDIA GPU using Nemotron-3-Nano. No data ever leaves your machine.

### Enabling Cloud Burst

If your local GPU is insufficient for complex tasks, you can opt in to Nebius Serverless:

```yaml
# In config.yaml or environment
BLOB_LLM_BACKEND: "nebius"
BLOB_NEBIUS_API_KEY: "your-api-key"
```

### What Happens When Enabled
1. NemoClaw's Privacy Router scrubs PII from outgoing prompts
2. Request is sent via HTTPS to Nebius Serverless (`api.studio.nebius.ai`)
3. Inference runs on Nebius GPU cluster
4. Response is streamed back and processed locally
5. No data is stored on Nebius servers

### Privacy Guarantees with Cloud Burst
- PII scrubbing before transmission
- HTTPS encryption in transit
- No server-side storage or logging by Nebius
- User can revoke access anytime by removing API key

---

## Threat Model

| Threat | Mitigation |
|--------|-----------|
| Screen data exfiltration | All capture is in-memory, never persisted. Privacy Shield blocks sensitive apps. |
| Memory theft (physical access) | ChromaDB can be encrypted at rest (future feature). |
| Malicious skill pills | Skills run in OpenShell sandbox with declared permissions only. |
| Prompt injection via screen text | NemoClaw input guardrails filter injected prompts. |
| Network exfiltration | Default: no network access. Nebius is opt-in with PII scrubbing. |
| Process monitoring | Window monitor only reads titles, never window content. |

---

## Audit Trail

All privacy-relevant events are logged locally:

```
~/.blob/logs/privacy.log
```

Log entries include:
- Privacy Shield activations/deactivations
- Skill permission grants
- Nebius cloud burst requests (sanitized)
- Configuration changes

Logs never contain sensitive content — only event types and timestamps.
