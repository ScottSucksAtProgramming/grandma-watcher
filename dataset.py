"""Dataset persistence helpers for vigil.

Phase 1 scope: save frame JPEGs and append DatasetEntry JSONL rows.
"""

from __future__ import annotations

import dataclasses
import fcntl
import json
import logging
import tempfile
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable

from config import AppConfig
from models import DatasetEntry

logger = logging.getLogger(__name__)


def build_image_filename(timestamp: str) -> str:
    """Convert an ISO 8601 UTC timestamp into the dataset JPEG filename."""
    try:
        parsed = datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ValueError(f"Invalid timestamp for dataset image filename: {timestamp!r}") from exc
    return parsed.strftime("%Y-%m-%d_%H-%M-%S.jpg")


def save_frame_image(config: AppConfig, timestamp: str, frame_bytes: bytes) -> str:
    """Save one frame JPEG and return its relative dataset path."""
    filename = build_image_filename(timestamp)
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True, exist_ok=True)
    (images_dir / filename).write_bytes(frame_bytes)
    return Path("images", filename).as_posix()


def append_log_entry(config: AppConfig, entry: DatasetEntry) -> None:
    """Append one DatasetEntry as a single JSON object line."""
    log_path = Path(config.dataset.log_file)
    lock_path = Path(f"{config.dataset.log_file}.lock")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _json_safe(dataclasses.asdict(entry))
    with lock_path.open("a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload))
                handle.write("\n")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def read_log(config: AppConfig) -> list[dict[str, Any]]:
    """Read log.jsonl rows under the shared flock."""
    log_path = Path(config.dataset.log_file)
    lock_path = Path(f"{config.dataset.log_file}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_SH)
        try:
            return _read_log_rows(log_path, warning_prefix="read_log")
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def rewrite_log(
    config: AppConfig, transform: Callable[[list[dict[str, Any]]], list[dict[str, Any]]]
) -> None:
    """Atomically rewrite log.jsonl via temp-file rename under the shared lock."""
    log_path = Path(config.dataset.log_file)
    lock_path = Path(f"{config.dataset.log_file}.lock")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    with lock_path.open("a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        tmp_path: Path | None = None
        try:
            rows = transform(_read_log_rows(log_path, warning_prefix="rewrite_log"))
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=log_path.parent,
                delete=False,
                suffix=".tmp",
            ) as tmp:
                tmp_path = Path(tmp.name)
                for row in rows:
                    tmp.write(json.dumps(row))
                    tmp.write("\n")
            tmp_path.rename(log_path)
        except Exception:
            if tmp_path is not None:
                tmp_path.unlink(missing_ok=True)
            raise
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)


def patch_log_entry(config: AppConfig, timestamp: str, updates: dict[str, Any]) -> None:
    """Patch the log row matching timestamp."""
    found = False

    def _transform(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        nonlocal found
        for row in rows:
            if row.get("timestamp") == timestamp:
                row.update(updates)
                found = True
        return rows

    rewrite_log(config, _transform)

    if not found:
        logger.warning("patch_log_entry: no row found with timestamp %r", timestamp)


def record_dataset_entry(
    config: AppConfig,
    timestamp: str,
    frame_bytes: bytes,
    entry: DatasetEntry,
    *,
    save_image: bool = True,
) -> DatasetEntry:
    """Append the log row and optionally save the frame image.

    When save_image=False the JSONL entry is written with image_path="" so
    the assessment is always logged, but no JPEG is written to disk.
    """
    if save_image:
        image_path = save_frame_image(config=config, timestamp=timestamp, frame_bytes=frame_bytes)
        entry = dataclasses.replace(entry, image_path=image_path)
    append_log_entry(config, entry)
    return entry


def _json_safe(value: Any) -> Any:
    """Recursively convert enums and nested structures into JSON-safe values."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _read_log_rows(log_path: Path, *, warning_prefix: str) -> list[dict[str, Any]]:
    """Read JSONL rows from disk, tolerating missing or malformed lines."""
    if not log_path.exists() or log_path.stat().st_size == 0:
        return []

    rows: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError:
            logger.warning("%s: skipping malformed line", warning_prefix)
    return rows
