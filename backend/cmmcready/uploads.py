"""Validation of uploaded evidence files (collector JSON)."""

from __future__ import annotations

MAX_LINE_CHARS = 8192
EVIDENCE_MAX_LINE_CHARS = 65536  # pretty-printed collector JSON; some values are long
EVIDENCE_MAX_LINE_CHARS = 65536  # pretty-printed collector JSON; some values (policies) are long


class UploadError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def decode_json_upload(data: bytes, max_line: int = MAX_LINE_CHARS) -> str:
    """Return the text of an upload after the byte-level checks.

    NUL bytes and invalid UTF-8 give 415; a line over ``max_line`` characters gives 413
    (the collectors write pretty-printed JSON, so real files have short lines).
    """
    if b"\x00" in data:
        raise UploadError(415, "File looks binary, expected a JSON text file")
    try:
        text = data.decode("utf-8-sig")  # strips a leading BOM
    except UnicodeDecodeError:
        raise UploadError(415, "File is not UTF-8 text") from None
    for n, line in enumerate(text.splitlines(), 1):
        if len(line) > max_line:
            raise UploadError(413, f"Line {n} is longer than the limit of {max_line} characters ({len(line)} found)")
    return text
