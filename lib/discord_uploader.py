from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Dict

try:
    import requests
except Exception:  # pragma: no cover
    requests = None


class DiscordUploadError(RuntimeError):
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[1]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_WEBHOOK_FILE = WORKSPACE_ROOT / "webhook" / "Orderheatmap"


def _load_webhook_url() -> str:
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if webhook_url:
        return webhook_url

    webhook_file = Path(os.getenv("DISCORD_WEBHOOK_URL_FILE", str(DEFAULT_WEBHOOK_FILE)))
    if not webhook_file.exists():
        return ""

    text = webhook_file.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    return _fallback_webhook_text(text)


def _payload_json(content: str) -> str:
    return json.dumps(
        {
            "content": content,
            "flags": 4096,
            "allowed_mentions": {"parse": []},
        },
        ensure_ascii=False,
    )


def _upload_with_requests(webhook_url: str, file_path: Path, content: str) -> Dict[str, Any]:
    if requests is None:
        raise DiscordUploadError("requests is not available")
    with file_path.open("rb") as f:
        resp = requests.post(
            webhook_url,
            params={"wait": "true"},
            data={"payload_json": _payload_json(content)},
            files={"files[0]": (file_path.name, f, "image/png")},
            timeout=30,
        )
    if not resp.ok:
        raise DiscordUploadError(f"webhook upload failed: {resp.status_code} {resp.text[:300]}")
    try:
        return resp.json()
    except Exception:
        return {"status_code": resp.status_code}


def _upload_with_curl(webhook_url: str, file_path: Path, content: str) -> Dict[str, Any]:
    payload = _payload_json(content)
    cmd = [
        "curl",
        "-sS",
        "-X",
        "POST",
        webhook_url,
        "-F",
        f"payload_json={payload}",
        "-F",
        f"files[0]=@{file_path}",
        "-G",
        "--data-urlencode",
        "wait=true",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise DiscordUploadError(f"curl failed rc={res.returncode}: {res.stderr.strip()[-400:]}")
    body = (res.stdout or "").strip()
    if not body:
        raise DiscordUploadError("Discord API returned empty response")
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        raise DiscordUploadError(f"Non-JSON Discord response: {body[-400:]}") from exc
    if isinstance(data, dict) and data.get("id"):
        return data
    api_message = data.get("message") if isinstance(data, dict) else None
    raise DiscordUploadError(f"Discord API error: {api_message or body[-400:]}")


def upload_via_webhook(webhook_url: str, file_path: str | Path, content: str = "") -> Dict[str, Any]:
    file_path = Path(file_path)
    if not webhook_url:
        raise DiscordUploadError("DISCORD_WEBHOOK_URL is empty")
    if not file_path.exists():
        raise DiscordUploadError(f"file not found: {file_path}")

    last_error: Exception | None = None
    for attempt in range(2):
        try:
            return _upload_with_requests(webhook_url, file_path, content)
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                continue
    try:
        return _upload_with_curl(webhook_url, file_path, content)
    except Exception as exc:
        raise DiscordUploadError(f"webhook upload failed: {last_error or exc}") from exc


def _fallback_webhook_text(text: str) -> str:
    """Parse webhook URL from file text (URL directly or key=value format)."""
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        return text
    if "=" in text:
        return text.split("=", 1)[1].strip()
    return text


def _load_webhook_url_for_channel(channel_id: str) -> str:
    """Resolve webhook URL for a given channel_id.

    1. DISCORD_WEBHOOK_URL env var (checked first for zero-config setups).
    2. If a channel-specific file at ``WORKSPACE_ROOT / "webhook" / channel_id``
       exists, use it.
    3. Otherwise fall back to ``_load_webhook_url()`` (default).

    Security: channel_id is validated as a Discord snowflake (17-19 digit
    string) to prevent path traversal.
    """
    if not channel_id or not channel_id.strip():
        return _load_webhook_url()

    env_url = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
    if env_url:
        return env_url

    if not re.fullmatch(r"\d{17,19}", channel_id):
        raise DiscordUploadError(f"invalid channel_id format: {channel_id[:20]}")

    channel_file = WORKSPACE_ROOT / "webhook" / channel_id
    if channel_file.exists():
        text = channel_file.read_text(encoding="utf-8").strip()
        return _fallback_webhook_text(text) if text else ""

    # Channel-specific file not found; try fallback file from env / default
    return _load_webhook_url()


def upload_file(channel_id: str, file_path: str | Path, content: str = "") -> Dict[str, Any]:
    webhook_url = _load_webhook_url_for_channel(channel_id)
    return upload_via_webhook(webhook_url, file_path, content=content)
