"""Local screen filtering. Ambient prompts use fixed vocabulary, never OCR excerpts."""

import re
import unicodedata


SENSITIVE_WINDOW = re.compile(
    r"1password|bitwarden|keepass|password|passkey|incognito|private browsing|"
    r"\bbank\b|banking|payment|checkout|credit card|\binbox\b|gmail|outlook|"
    r"whatsapp|telegram|signal\.desktop|discord|slack|medical|patient|"
    r"(?:^|[ /])\.env(?:\b|$)|credentials|secret keys", re.I)
SENSITIVE_CONTENT = re.compile(
    r"\b(?:password|passphrase|private key|api[_ -]?key|access[_ -]?token|"
    r"refresh[_ -]?token|client[_ -]?secret|one[- ]time (?:password|code)|"
    r"verification code|credit card|account balance|patient record|"
    r"direct messages?|recovery (?:phrase|code)|seed phrase)\b|"
    r"-----BEGIN .*PRIVATE KEY-----|\b(?:sk-[A-Za-z0-9_-]{12,}|AKIA[A-Z0-9]{16})\b", re.I)
PII = re.compile(
    r"https?://\S+|\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|"
    r"\b(?:\d[ -]?){9,19}\b|\b[0-9a-f]{8}-[0-9a-f-]{27,}\b|"
    r"\b(?:\d{1,3}\.){3}\d{1,3}\b", re.I)
PRIVATE_LABEL = re.compile(
    r"\b(?:full name|customer name|address|date of birth|dob|aadhaar|aadhar|"
    r"pan number|passport|ssn|phone|email|account number|iban)\s*[:=]", re.I)


def normalized(text):
    return re.sub(r"[\u200b-\u200f\u202a-\u202e\u2060-\u206f]", "", unicodedata.normalize("NFKC", text))


def sensitive_window(window):
    return bool(SENSITIVE_WINDOW.search(normalized(window.title + " " + window.process_name)))


def filter_screen_text(text):
    """Reject sensitive pages; redact identifiable patterns from remaining text.

    This is a conservative heuristic, not a universal PII detector. Ambient
    summaries therefore have an additional fixed-vocabulary boundary.
    """
    text = normalized(text)[:24000]
    if SENSITIVE_CONTENT.search(text):
        return ""
    lines = []
    omit_next = False
    for line in text.splitlines():
        if omit_next:
            omit_next = False
            continue
        if PRIVATE_LABEL.search(line):
            omit_next = True
            continue
        lines.append(PII.sub("[redacted]", line))
    return "\n".join(lines).strip()


def app_category(process):
    # Return constants, never arbitrary process names or document titles.
    if not isinstance(process, str):
        return "application"
    process = process.casefold()
    for pattern, label in (
        (r"firefox|chrome|chromium|brave|epiphany", "browser"),
        (r"code|codium|pycharm|idea|emacs|gedit|builder|sublime", "editor"),
        (r"terminal|ptyxis|kgx|konsole|kitty|alacritty|xterm|foot|wezterm", "terminal"),
        (r"evince|papers|okular|libreoffice", "document viewer"),
        (r"vlc|mpv|totem", "media player"),
    ):
        if re.search(pattern, process):
            return label
    return "application"


TOPICS = (
    "Ohm's law", "voltage divider", "resistance", "capacitance", "electric circuits",
    "digital electronics", "logic gates", "state machine", "HDL", "Verilog", "VHDL",
    "IoT", "Internet of Things", "probability", "conditional probability", "Bayes theorem",
    "statistics", "discrete mathematics", "linear algebra", "calculus", "derivatives",
    "signals", "Fourier transform", "sine wave", "analog electronics", "drone technology",
    "data structures", "algorithms", "machine learning", "neural networks",
    "Python", "JavaScript", "TypeScript", "C++", "Rust", "SQL", "HTML", "CSS", "Git",
)
TOPIC_PATTERNS = [(topic, re.compile(r"(?<!\w)" + re.escape(topic).replace(r"\ ", r"\s+") + r"(?!\w)", re.I))
                  for topic in TOPICS]


def activity_summary(text, process):
    """Only allowlisted category and topic names may leave the local observer."""
    clean = filter_screen_text(text)
    if not clean:
        return ""
    category = app_category(process)
    topics = [topic for topic, pattern in TOPIC_PATTERNS if pattern.search(clean)][:4]
    activity = ("Working with code" if category in {"editor", "terminal"} else
                "Reading or studying" if topics else
                "Watching media" if category == "media player" else "Using an application")
    return f"{activity} in a {category}." + (" Detected topics: " + ", ".join(topics) + "." if topics else "")
