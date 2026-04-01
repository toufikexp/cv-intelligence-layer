from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import HTTPException, UploadFile

from app.config import get_settings

ALLOWED_MIMES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


async def validate_and_persist_upload(file: UploadFile) -> tuple[Path, str]:
    """Validate uploaded file and persist to disk.

    Returns:
        (path, sha256_hex)
    """

    settings = get_settings()
    if file.content_type not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=400,
            detail={"detail": "Invalid file type", "code": "INVALID_FILE_TYPE"},
        )

    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    max_bytes = settings.max_file_size_mb * 1024 * 1024

    h = hashlib.sha256()
    total = 0

    suffix = ".pdf" if file.content_type == "application/pdf" else ".docx"
    tmp_path = settings.upload_dir / f"upload_{hashlib.md5(file.filename.encode('utf-8')).hexdigest()}{suffix}"

    with tmp_path.open("wb") as f:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise HTTPException(
                    status_code=400,
                    detail={"detail": "File too large", "code": "FILE_TOO_LARGE"},
                )
            h.update(chunk)
            f.write(chunk)

    return tmp_path, h.hexdigest()

