"""What a person calls a game: "Pac-Man", not "Pac-Man (Midway)"."""

import re

TRAILING_PARENS = re.compile(r"(\s*\([^()]*\))+\s*$")


def title(description: str) -> str:
    return TRAILING_PARENS.sub("", description).strip() or description.strip()
