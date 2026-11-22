"""What a person calls a game ("Pac-Man", not "Pac-Man (Midway)"), and what the nerds call a set."""

import re

from infiltrator.dat import DEFAULT_EMULATOR

TRAILING_PARENS = re.compile(r"(\s*\([^()]*\))+\s*$")


def title(description: str) -> str:
    return TRAILING_PARENS.sub("", description).strip() or description.strip()


def set_label(emulator: str, set_name: str) -> str:
    """A set by name: bare for MAME 2003-Plus, as it always was; `fbneo/hbarrelua` otherwise."""
    return set_name if emulator == DEFAULT_EMULATOR else f"{emulator}/{set_name}"
