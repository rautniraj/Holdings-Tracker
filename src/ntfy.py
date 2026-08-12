from __future__ import annotations

import sys
from typing import TYPE_CHECKING

import requests

if TYPE_CHECKING:
    from src.config import Settings

DEFAULT_NTFY_SERVER = "https://ntfy.sh"


def send_notification(
    settings: Settings,
    *,
    title: str,
    message: str,
    priority: str = "default",
    tags: str | None = None,
) -> bool:
    """Send NTFY notification. Returns True if sent, False if topic not configured."""
    if not settings.ntfy_topic:
        return False

    url = f"{settings.ntfy_server.rstrip('/')}/{settings.ntfy_topic.strip('/')}"
    headers = {"Title": title}
    if priority:
        headers["Priority"] = priority
    if tags:
        headers["Tags"] = tags

    try:
        response = requests.post(url, data=message.encode("utf-8"), headers=headers, timeout=15)
        response.raise_for_status()
        return True
    except requests.RequestException as exc:
        print(f"WARNING: NTFY notification failed: {exc}", file=sys.stderr)
        return False
