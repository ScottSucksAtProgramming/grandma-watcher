"""Dataset archiver for vigil."""

from __future__ import annotations

import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from config import AppConfig, load_config
from dataset import read_log, rewrite_log

logger = logging.getLogger(__name__)

_FILENAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})\.jpg$")
_TIMESTAMP_FMT = "%Y-%m-%d_%H-%M-%S"


def _parse_filename_age_seconds(filename: str, now: datetime) -> float | None:
    """Return age in seconds derived from the filename timestamp."""
    match = _FILENAME_RE.match(filename)
    if match is None:
        return None
    try:
        captured_at = datetime.strptime(match.group(1), _TIMESTAMP_FMT).replace(tzinfo=UTC)
    except ValueError:
        return None
    return (now - captured_at).total_seconds()


def run_archive_cycle(config: AppConfig, *, _run: Callable = subprocess.run) -> None:
    """Encrypt labeled JPEG frames older than the archival threshold."""
    if not config.security.age_public_key:
        logger.warning("archiver: age_public_key not configured; skipping")
        return
    if shutil.which("age") is None:
        logger.error("archiver: age binary not found; skipping")
        return

    label_map: dict[str, str] = {}
    for row in read_log(config):
        image_path = str(row.get("image_path", "") or "")
        if not image_path:
            continue
        label_map[Path(image_path).name] = str(row.get("label", "") or "")

    images_dir = Path(config.dataset.images_dir)
    if not images_dir.exists():
        return

    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(tz=UTC)
    threshold_seconds = config.security.archive_after_hours * 3600
    archived_filenames: list[str] = []

    for jpg_path in sorted(images_dir.glob("*.jpg")):
        age_seconds = _parse_filename_age_seconds(jpg_path.name, now)
        if age_seconds is None:
            logger.warning("archiver: skipping file with unparseable timestamp: %s", jpg_path.name)
            continue
        if age_seconds < threshold_seconds:
            continue
        if not label_map.get(jpg_path.name, ""):
            continue

        encrypted_path = archive_dir / f"{jpg_path.name}.age"
        result = _run(
            [
                "age",
                "-r",
                config.security.age_public_key,
                "-o",
                str(encrypted_path),
                str(jpg_path),
            ],
            capture_output=True,
        )
        if (
            result.returncode != 0
            or not encrypted_path.exists()
            or encrypted_path.stat().st_size == 0
        ):
            logger.error(
                "archiver: encryption failed for %s (returncode=%s)",
                jpg_path.name,
                result.returncode,
            )
            encrypted_path.unlink(missing_ok=True)
            continue

        jpg_path.unlink()
        archived_filenames.append(jpg_path.name)

    if not archived_filenames:
        return

    archived_set = set(archived_filenames)

    def _mark_archived(rows: list[dict]) -> list[dict]:
        for row in rows:
            if Path(str(row.get("image_path", ""))).name in archived_set:
                row["image_archived"] = True
        return rows

    rewrite_log(config, _mark_archived)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_archive_cycle(load_config())
