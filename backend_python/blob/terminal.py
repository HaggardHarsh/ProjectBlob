"""Plain terminal text: external content cannot issue terminal control commands."""

import re


ESCAPE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def terminal_text(text):
    return CONTROL.sub("", ESCAPE.sub("", text))
