"""Optional Telegram upload integration for web-uploaded files."""

import json
import mimetypes
import os
from pathlib import Path
from typing import Any
from urllib import request


def _multipart_body(path: Path, caption: str, chat_id: str) -> tuple[bytes, str]:
    boundary = "telegram-storage-boundary"
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    parts = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n".encode(),
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption[:1024]}\r\n".encode(),
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"document\"; "
            f"filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n"
        ).encode(),
        path.read_bytes(),
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def upload_to_telegram(path: str | Path, caption: str) -> dict[str, Any] | None:
    """Upload a file to a configured Telegram chat and return file metadata.

    Set BOT_TOKEN and TELEGRAM_STORAGE_CHAT_ID to enable this. The local
    encrypted copy is still kept so downloads do not depend on Telegram.
    """
    bot_token = os.getenv("BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_STORAGE_CHAT_ID")
    if not bot_token or not chat_id:
        return None

    file_path = Path(path)
    body, content_type = _multipart_body(file_path, caption, chat_id)
    telegram_request = request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendDocument",
        data=body,
        headers={"Content-Type": content_type},
        method="POST",
    )
    with request.urlopen(telegram_request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    document = payload.get("result", {}).get("document", {})
    return {
        "message_id": payload.get("result", {}).get("message_id"),
        "file_id": document.get("file_id"),
        "file_unique_id": document.get("file_unique_id"),
    }
