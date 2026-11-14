"""Turns the model's ``[n]`` markers into trustworthy references.

The model only ever sees numbered passages we chose, so a marker is valid exactly when that
number was in the prompt. Anything else (a number it invented, a ``[2024]`` copied from a
document) is removed from the text instead of being shown as a source.
"""

import re

_MARKER = re.compile(r"\s?\[(\d+(?:\s*[,;]\s*\d+)*)\]")


def resolve_citations(text: str, valid_numbers: set[int]) -> tuple[str, list[int]]:
    """Return the text with invalid markers removed, and the cited numbers in order of first use."""
    cited: list[int] = []

    def replace(match: re.Match[str]) -> str:
        numbers = [int(n) for n in re.split(r"[,;]", match.group(1))]
        kept = [n for n in numbers if n in valid_numbers]
        for n in kept:
            if n not in cited:
                cited.append(n)
        if not kept:
            return ""
        lead = " " if match.group(0).startswith(" ") else ""
        return f"{lead}[{', '.join(str(n) for n in kept)}]"

    return _MARKER.sub(replace, text).strip(), cited
