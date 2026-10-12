"""Spreadsheet-safe serialization for user and administrator supplied text."""

from __future__ import annotations

import unicodedata


FORMULA_PREFIXES = frozenset("=+-@")


def sanitize_csv_text(value: object) -> str:
    """Prevent formula execution while preserving the visible source text.

    Spreadsheet engines may ignore whitespace, tabs, a BOM or other control
    characters before deciding whether a cell is a formula. Prefix the entire
    original value with an apostrophe when the first meaningful character is a
    formula marker.
    """

    text = "" if value is None else str(value)
    probe_index = 0
    while probe_index < len(text):
        character = text[probe_index]
        if character.isspace() or unicodedata.category(character).startswith("C"):
            probe_index += 1
            continue
        break
    if probe_index < len(text) and text[probe_index] in FORMULA_PREFIXES:
        return "'" + text
    return text
