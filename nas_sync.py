"""NAS sync for vigil archives."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Callable

from config import AppConfig, load_config

logger = logging.getLogger(__name__)


def run_nas_sync(config: AppConfig, *, _run: Callable = subprocess.run) -> None:
    """Sync encrypted archive and metadata logs to the NAS."""
    if not config.security.nas_sync_enabled:
        logger.warning("nas_sync: nas_sync_enabled is False; skipping")
        return
    if not config.security.nas_rsync_target:
        logger.warning("nas_sync: nas_rsync_target is empty; skipping")
        return

    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = f"{config.security.nas_rsync_target}/"

    archive_result = _run(
        ["rsync", "-avz", f"{archive_dir}/", target],
        capture_output=True,
    )
    if archive_result.returncode != 0:
        logger.error(
            "nas_sync: archive rsync failed (exit %s)",
            archive_result.returncode,
        )
        return

    for age_file in archive_dir.glob("*.age"):
        age_file.unlink()

    for log_path in (Path(config.dataset.log_file), Path(config.dataset.checkin_log_file)):
        if not log_path.exists():
            continue
        result = _run(
            ["rsync", "-avz", str(log_path), target],
            capture_output=True,
        )
        if result.returncode != 0:
            logger.error("nas_sync: rsync failed for %s (exit %s)", log_path.name, result.returncode)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_nas_sync(load_config())
