import dataclasses
import json

import pytest

from config import AppConfig, DatasetConfig
from models import AssessmentResult, Confidence, DatasetEntry, PatientLocation, SensorSnapshot


def _dataset_config(tmp_path):
    base_dir = tmp_path / "dataset"
    return DatasetConfig(
        base_dir=str(base_dir),
        images_dir=str(base_dir / "images"),
        log_file=str(base_dir / "log.jsonl"),
        checkin_log_file=str(base_dir / "checkins.jsonl"),
    )


def _app_config(sample_config: AppConfig, tmp_path) -> AppConfig:
    return dataclasses.replace(sample_config, dataset=_dataset_config(tmp_path))


def _dataset_entry(**overrides) -> DatasetEntry:
    defaults = dict(
        timestamp="2026-04-09T03:00:00Z",
        image_path="",
        provider="nanogpt",
        model="Qwen3 VL 235B A22B Instruct",
        prompt_version="1.0",
        sensor_snapshot=SensorSnapshot(load_cells_enabled=False, vitals_enabled=False),
        response_raw='{"safe": true, "confidence": "high"}',
        assessment=AssessmentResult(
            safe=True,
            confidence=Confidence.HIGH,
            reason="Patient resting in bed.",
            patient_location=PatientLocation.IN_BED,
        ),
        alert_fired=False,
        api_latency_ms=2140.0,
    )
    return DatasetEntry(**{**defaults, **overrides})


def test_build_image_filename_formats_iso_utc_timestamp():
    from dataset import build_image_filename

    assert build_image_filename("2026-04-09T03:00:00Z") == "2026-04-09_03-00-00.jpg"


def test_build_image_filename_rejects_malformed_timestamp():
    from dataset import build_image_filename

    with pytest.raises(ValueError, match="timestamp"):
        build_image_filename("2026-04-09 03:00:00")


def test_save_frame_image_writes_exact_bytes(sample_config, tmp_path, fixture_frame_bytes):
    from dataset import save_frame_image

    config = _app_config(sample_config, tmp_path)

    relative_path = save_frame_image(
        config=config,
        timestamp="2026-04-09T03:00:00Z",
        frame_bytes=fixture_frame_bytes,
    )

    assert relative_path == "images/2026-04-09_03-00-00.jpg"
    image_path = tmp_path / "dataset" / relative_path
    assert image_path.exists()
    assert image_path.read_bytes() == fixture_frame_bytes


def test_append_log_entry_writes_single_json_line(sample_config, tmp_path):
    from dataset import append_log_entry

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry(image_path="images/2026-04-09_03-00-00.jpg")

    append_log_entry(config, entry)

    log_path = tmp_path / "dataset" / "log.jsonl"
    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1


def test_append_log_entry_serializes_nested_enums_to_strings(sample_config, tmp_path):
    from dataset import append_log_entry

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry(image_path="images/2026-04-09_03-00-00.jpg")

    append_log_entry(config, entry)

    payload = json.loads((tmp_path / "dataset" / "log.jsonl").read_text(encoding="utf-8"))
    assert payload["assessment"]["confidence"] == "high"
    assert payload["assessment"]["patient_location"] == "in_bed"
    assert payload["sensor_snapshot"]["load_cells_enabled"] is False
    assert payload["sensor_snapshot"]["vitals_enabled"] is False


def test_record_dataset_entry_writes_image_and_log_row(
    sample_config, tmp_path, fixture_frame_bytes
):
    from dataset import record_dataset_entry

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry()

    saved_entry = record_dataset_entry(
        config=config,
        timestamp="2026-04-09T03:00:00Z",
        frame_bytes=fixture_frame_bytes,
        entry=entry,
    )

    assert saved_entry.image_path == "images/2026-04-09_03-00-00.jpg"
    assert (tmp_path / "dataset" / "images" / "2026-04-09_03-00-00.jpg").exists()

    payload = json.loads((tmp_path / "dataset" / "log.jsonl").read_text(encoding="utf-8"))
    assert payload["image_path"] == "images/2026-04-09_03-00-00.jpg"
    assert payload["assessment"]["reason"] == "Patient resting in bed."


def test_record_dataset_entry_skip_image_writes_log_only(
    sample_config, tmp_path, fixture_frame_bytes
):
    from dataset import record_dataset_entry

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry()

    saved_entry = record_dataset_entry(
        config=config,
        timestamp="2026-04-09T03:00:00Z",
        frame_bytes=fixture_frame_bytes,
        entry=entry,
        save_image=False,
    )

    assert saved_entry.image_path == ""
    assert not (tmp_path / "dataset" / "images").exists()

    payload = json.loads((tmp_path / "dataset" / "log.jsonl").read_text(encoding="utf-8"))
    assert payload["image_path"] == ""
    assert payload["assessment"]["reason"] == "Patient resting in bed."


def test_read_log_returns_all_rows(sample_config, tmp_path):
    from dataset import append_log_entry, read_log

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry(
        image_path="images/2026-04-09_03-00-00.jpg",
        timestamp="2026-04-09T03:00:00Z",
    )
    append_log_entry(config, entry)

    rows = read_log(config)

    assert len(rows) == 1
    assert rows[0]["timestamp"] == "2026-04-09T03:00:00Z"


def test_read_log_returns_empty_list_for_missing_file(sample_config, tmp_path):
    from dataset import read_log

    config = _app_config(sample_config, tmp_path)

    assert read_log(config) == []


def test_rewrite_log_applies_transform_and_rewrites_file(sample_config, tmp_path):
    from dataset import append_log_entry, rewrite_log

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry(
        image_path="images/2026-04-09_03-00-00.jpg",
        timestamp="2026-04-09T03:00:00Z",
    )
    append_log_entry(config, entry)

    def _mark_all_archived(rows):
        for row in rows:
            row["image_archived"] = True
        return rows

    rewrite_log(config, _mark_all_archived)

    log_path = tmp_path / "dataset" / "log.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["image_archived"] is True


def test_rewrite_log_handles_missing_log_file(sample_config, tmp_path):
    from dataset import rewrite_log

    config = _app_config(sample_config, tmp_path)

    rewrite_log(config, lambda rows: rows)


def test_rewrite_log_handles_empty_log_file(sample_config, tmp_path):
    from dataset import rewrite_log

    config = _app_config(sample_config, tmp_path)
    log_path = tmp_path / "dataset" / "log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text("", encoding="utf-8")

    rewrite_log(config, lambda rows: rows)


def test_patch_log_entry_updates_matching_row_by_timestamp(sample_config, tmp_path):
    from dataset import append_log_entry, patch_log_entry

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry(
        image_path="images/2026-04-09_03-00-00.jpg",
        timestamp="2026-04-09T03:00:00Z",
    )
    append_log_entry(config, entry)

    patch_log_entry(config, "2026-04-09T03:00:00Z", {"image_archived": True})

    log_path = tmp_path / "dataset" / "log.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload["image_archived"] is True


def test_patch_log_entry_no_op_when_timestamp_not_found(sample_config, tmp_path):
    from dataset import append_log_entry, patch_log_entry

    config = _app_config(sample_config, tmp_path)
    entry = _dataset_entry(
        image_path="images/2026-04-09_03-00-00.jpg",
        timestamp="2026-04-09T03:00:00Z",
    )
    append_log_entry(config, entry)

    patch_log_entry(config, "1999-01-01T00:00:00Z", {"image_archived": True})

    log_path = tmp_path / "dataset" / "log.jsonl"
    payload = json.loads(log_path.read_text(encoding="utf-8"))
    assert payload.get("image_archived", False) is False


def test_patch_log_entry_preserves_other_rows(sample_config, tmp_path):
    from dataset import append_log_entry, patch_log_entry

    config = _app_config(sample_config, tmp_path)
    entry1 = _dataset_entry(
        image_path="images/2026-04-09_03-00-00.jpg",
        timestamp="2026-04-09T03:00:00Z",
    )
    entry2 = _dataset_entry(
        image_path="images/2026-04-09_03-00-30.jpg",
        timestamp="2026-04-09T03:00:30Z",
    )
    append_log_entry(config, entry1)
    append_log_entry(config, entry2)

    patch_log_entry(config, "2026-04-09T03:00:00Z", {"image_archived": True})

    log_path = tmp_path / "dataset" / "log.jsonl"
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    row2 = json.loads(lines[1])
    assert row2.get("image_archived", False) is False
