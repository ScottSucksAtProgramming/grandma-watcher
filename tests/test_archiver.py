"""Tests for archiver.py - run_archive_cycle."""

import dataclasses
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from config import AppConfig


def _make_config(sample_config: AppConfig, tmp_path: Path, **security_overrides) -> AppConfig:
    dataset = dataclasses.replace(
        sample_config.dataset,
        base_dir=str(tmp_path / "dataset"),
        images_dir=str(tmp_path / "dataset" / "images"),
        archive_dir=str(tmp_path / "dataset" / "archive"),
        log_file=str(tmp_path / "dataset" / "log.jsonl"),
        checkin_log_file=str(tmp_path / "dataset" / "checkins.jsonl"),
    )
    security_defaults = {
        "age_public_key": "age1publickey",
        "archive_after_hours": 24.0,
    }
    security_defaults.update(security_overrides)
    security = dataclasses.replace(sample_config.security, **security_defaults)
    return dataclasses.replace(sample_config, dataset=dataset, security=security)


def _write_log(log_path: Path, entries: list[dict]) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")


def _old_filename() -> str:
    ts = datetime.now(tz=timezone.utc) - timedelta(hours=25)
    return ts.strftime("%Y-%m-%d_%H-%M-%S.jpg")


def _recent_filename() -> str:
    ts = datetime.now(tz=timezone.utc) - timedelta(hours=1)
    return ts.strftime("%Y-%m-%d_%H-%M-%S.jpg")


def _image_path_for(filename: str) -> str:
    return f"images/{filename}"


def test_archive_cycle_skips_when_age_public_key_empty(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path, age_public_key="")
    calls = []

    run_archive_cycle(config, _run=lambda *a, **kw: calls.append(a))

    assert calls == []


def test_archive_cycle_skips_when_age_binary_not_found(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)

    with patch("archiver.shutil.which", return_value=None):
        run_archive_cycle(config)


def test_archive_cycle_skips_files_younger_than_threshold(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _recent_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "real_issue",
                "image_archived": False,
            }
        ],
    )

    calls = []
    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=lambda *a, **kw: calls.append(a))

    assert calls == []
    assert (images_dir / filename).exists()


def test_archive_cycle_skips_unlabeled_files(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _old_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "",
                "image_archived": False,
            }
        ],
    )

    calls = []
    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=lambda *a, **kw: calls.append(a))

    assert calls == []
    assert (images_dir / filename).exists()


def test_archive_cycle_skips_log_entries_with_empty_image_path(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _old_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T02:00:00Z",
                "image_path": "",
                "label": "real_issue",
                "image_archived": False,
            },
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "",
                "image_archived": False,
            },
        ],
    )

    calls = []
    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=lambda *a, **kw: calls.append(a))

    assert calls == []
    assert (images_dir / filename).exists()


def test_archive_cycle_encrypts_labeled_old_file_verifies_and_deletes(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _old_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")
    archive_dir = Path(config.dataset.archive_dir)

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "real_issue",
                "image_archived": False,
            }
        ],
    )

    def fake_run(cmd, **kwargs):
        age_out = Path(cmd[cmd.index("-o") + 1])
        age_out.parent.mkdir(parents=True, exist_ok=True)
        age_out.write_bytes(b"encrypted data")
        return subprocess.CompletedProcess(cmd, 0)

    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=fake_run)

    assert not (images_dir / filename).exists()
    assert (archive_dir / f"{filename}.age").exists()

    log = json.loads(Path(config.dataset.log_file).read_text(encoding="utf-8"))
    assert log["image_archived"] is True


def test_archive_cycle_does_not_delete_original_when_age_file_missing(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _old_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "real_issue",
                "image_archived": False,
            }
        ],
    )

    def fake_run_fails(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr=b"key error")

    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=fake_run_fails)

    assert (images_dir / filename).exists()
    log = json.loads(Path(config.dataset.log_file).read_text(encoding="utf-8"))
    assert log["image_archived"] is False


def test_archive_cycle_does_not_delete_original_when_age_file_zero_bytes(
    sample_config, tmp_path
):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _old_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")
    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True)

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "real_issue",
                "image_archived": False,
            }
        ],
    )

    def fake_run_zero(cmd, **kwargs):
        age_out = Path(cmd[cmd.index("-o") + 1])
        age_out.write_bytes(b"")
        return subprocess.CompletedProcess(cmd, 0)

    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=fake_run_zero)

    assert (images_dir / filename).exists()


def test_archive_cycle_creates_archive_dir_if_missing(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    filename = _old_filename()
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)
    (images_dir / filename).write_bytes(b"fake jpeg")
    archive_dir = Path(config.dataset.archive_dir)
    assert not archive_dir.exists()

    _write_log(
        Path(config.dataset.log_file),
        [
            {
                "timestamp": "2026-04-09T03:00:00Z",
                "image_path": _image_path_for(filename),
                "label": "real_issue",
                "image_archived": False,
            }
        ],
    )

    def fake_run(cmd, **kwargs):
        age_out = Path(cmd[cmd.index("-o") + 1])
        age_out.parent.mkdir(parents=True, exist_ok=True)
        age_out.write_bytes(b"encrypted")
        return subprocess.CompletedProcess(cmd, 0)

    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        run_archive_cycle(config, _run=fake_run)

    assert archive_dir.exists()


def test_archive_cycle_batch_rewrites_log_once_for_multiple_files(sample_config, tmp_path):
    from archiver import run_archive_cycle

    config = _make_config(sample_config, tmp_path)
    images_dir = Path(config.dataset.images_dir)
    images_dir.mkdir(parents=True)

    filenames = [
        (datetime.now(tz=timezone.utc) - timedelta(hours=25 + i)).strftime(
            "%Y-%m-%d_%H-%M-%S.jpg"
        )
        for i in range(3)
    ]
    for filename in filenames:
        (images_dir / filename).write_bytes(b"fake jpeg")

    log_entries = [
        {
            "timestamp": f"2026-04-09T0{i}:00:00Z",
            "image_path": f"images/{filename}",
            "label": "real_issue",
            "image_archived": False,
        }
        for i, filename in enumerate(filenames)
    ]
    _write_log(Path(config.dataset.log_file), log_entries)

    def fake_run(cmd, **kwargs):
        age_out = Path(cmd[cmd.index("-o") + 1])
        age_out.parent.mkdir(parents=True, exist_ok=True)
        age_out.write_bytes(b"encrypted")
        return subprocess.CompletedProcess(cmd, 0)

    rewrite_call_count = [0]
    import dataset as _dataset

    original_rewrite_log = _dataset.rewrite_log

    def counting_rewrite(config, transform):
        rewrite_call_count[0] += 1
        return original_rewrite_log(config, transform)

    with patch("archiver.shutil.which", return_value="/usr/bin/age"):
        with patch("archiver.rewrite_log", side_effect=counting_rewrite):
            run_archive_cycle(config, _run=fake_run)

    assert rewrite_call_count[0] == 1
