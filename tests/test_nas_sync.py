"""Tests for nas_sync.py - run_nas_sync."""

import dataclasses
import subprocess
from pathlib import Path

from config import AppConfig


def _make_config(sample_config: AppConfig, tmp_path: Path, **security_overrides) -> AppConfig:
    dataset = dataclasses.replace(
        sample_config.dataset,
        base_dir=str(tmp_path / "dataset"),
        archive_dir=str(tmp_path / "dataset" / "archive"),
        log_file=str(tmp_path / "dataset" / "log.jsonl"),
        checkin_log_file=str(tmp_path / "dataset" / "checkins.jsonl"),
    )
    security_defaults = {
        "nas_sync_enabled": True,
        "nas_rsync_target": "vigil-sync@100.1.2.3:/mnt/pool/vigil-archive",
    }
    security_defaults.update(security_overrides)
    security = dataclasses.replace(sample_config.security, **security_defaults)
    return dataclasses.replace(sample_config, dataset=dataset, security=security)


def test_nas_sync_skips_when_disabled(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path, nas_sync_enabled=False)
    calls = []

    run_nas_sync(config, _run=lambda *a, **kw: calls.append(a))

    assert calls == []


def test_nas_sync_skips_when_target_empty(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path, nas_rsync_target="")
    calls = []

    run_nas_sync(config, _run=lambda *a, **kw: calls.append(a))

    assert calls == []


def test_nas_sync_calls_rsync_for_archive_dir(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path)
    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True)

    results = []

    def fake_run(cmd, **kwargs):
        results.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    run_nas_sync(config, _run=fake_run)

    archive_calls = [result for result in results if "archive" in " ".join(result)]
    assert len(archive_calls) >= 1
    archive_cmd = archive_calls[0]
    assert "rsync" in archive_cmd[0]
    assert "-avz" in archive_cmd
    assert str(archive_dir) + "/" in archive_cmd
    assert "vigil-sync@100.1.2.3:/mnt/pool/vigil-archive/" in archive_cmd


def test_nas_sync_deletes_age_files_after_successful_rsync(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path)
    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True)
    age_file = archive_dir / "frame.jpg.age"
    age_file.write_bytes(b"encrypted")

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0)

    run_nas_sync(config, _run=fake_run)

    assert not age_file.exists()


def test_nas_sync_does_not_delete_age_files_on_rsync_failure(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path)
    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True)
    age_file = archive_dir / "frame.jpg.age"
    age_file.write_bytes(b"encrypted")

    def fake_run_fails(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stderr=b"connection refused")

    run_nas_sync(config, _run=fake_run_fails)

    assert age_file.exists()


def test_nas_sync_rsyncs_log_and_checkin_files(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path)
    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True)
    log_file = Path(config.dataset.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("{}\n", encoding="utf-8")
    checkin_file = Path(config.dataset.checkin_log_file)
    checkin_file.write_text("{}\n", encoding="utf-8")

    results = []

    def fake_run(cmd, **kwargs):
        results.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    run_nas_sync(config, _run=fake_run)

    all_args = " ".join(" ".join(result) for result in results)
    assert "log.jsonl" in all_args
    assert "checkins.jsonl" in all_args


def test_nas_sync_does_not_use_remove_source_files_for_logs(sample_config, tmp_path):
    from nas_sync import run_nas_sync

    config = _make_config(sample_config, tmp_path)
    archive_dir = Path(config.dataset.archive_dir)
    archive_dir.mkdir(parents=True)
    log_file = Path(config.dataset.log_file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    log_file.write_text("{}\n", encoding="utf-8")
    checkin_file = Path(config.dataset.checkin_log_file)
    checkin_file.write_text("{}\n", encoding="utf-8")

    results = []

    def fake_run(cmd, **kwargs):
        results.append(cmd)
        return subprocess.CompletedProcess(cmd, 0)

    run_nas_sync(config, _run=fake_run)

    log_and_checkin_calls = [
        result
        for result in results
        if "log.jsonl" in " ".join(result) or "checkins.jsonl" in " ".join(result)
    ]
    for cmd in log_and_checkin_calls:
        assert "--remove-source-files" not in cmd
