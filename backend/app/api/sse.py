"""Server-Sent Events framing.

An event is ``event: <name>`` and ``data: <one line of JSON>`` followed by a blank line.
JSON never contains a raw newline, so the data always fits on one line.
"""

import json
from typing import Any


def format_event(name: str, data: dict[str, Any]) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
