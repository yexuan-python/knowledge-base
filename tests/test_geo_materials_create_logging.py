from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from scripts import test_geo_materials_create as script


def test_auto_image_progress_log_escapes_hidden_path_characters(capsys):
    image_path = Path("/tmp/images/\n_1.jpg")

    script._print_auto_image_progress(
        index=0,
        total=2,
        original_path=image_path,
    )

    captured = capsys.readouterr()
    assert "自动识图中（第 1/2 张）" in captured.err
    assert "\\n_1.jpg" in captured.err


def test_auto_batches_skip_preprocess_failure_and_continue(tmp_path, monkeypatch):
    bad_path = tmp_path / "bad.jpg"
    good_path = tmp_path / "good.jpg"
    bad_path.write_bytes(b"bad")
    good_path.write_bytes(b"good")

    args = SimpleNamespace(
        endpoint="http://127.0.0.1:9067/api/assets/manual-upload",
        dry_run=True,
        timeout_seconds=60.0,
        delete_success_files=False,
    )

    async def fake_prepare_auto_uploads(args, *, file_paths, settings):
        original_path = file_paths[0]
        if original_path == bad_path:
            raise Exception("image inspection failed")
        return [
            script.PreparedUpload(
                original_path=original_path,
                upload_path=original_path,
                upload_filename=original_path.name,
                mime_type="image/jpeg",
                field_name="file_0",
                item={
                    "asset_type": "image",
                    "title": original_path.name,
                    "description": "ok",
                    "note": "ok",
                    "final_tags": [],
                    "file_field": "file_0",
                },
                cleanup_upload_path=False,
            )
        ]

    monkeypatch.setattr(script, "_prepare_auto_uploads", fake_prepare_auto_uploads)
    monkeypatch.setattr("knowledge_base.infrastructure.settings.get_settings", lambda: object())

    exit_code, results = script._run_auto_batches(
        args=args,
        requests_module=object(),
        headers={},
        file_paths=[bad_path, good_path],
    )

    assert exit_code == 2
    assert len(results) == 2
    assert results[0].ok is False
    assert results[0].failed_files[0]["filename"] == "bad.jpg"
    assert results[1].ok is True
    assert results[1].success_files[0]["filename"] == "good.jpg"


def test_batch_tags_are_appended_to_auto_final_tags():
    final_tags = script._build_final_tags(
        ["厨房", "橱柜", "统一标签"],
        dimension_code="scene",
    )

    names = [tag["name"] for tag in final_tags[0]["create_tags"]]

    assert names == ["厨房", "橱柜", "统一标签"]


def test_manual_final_tags_merge_batch_tags_without_duplicates(tmp_path):
    file_path = tmp_path / "image.jpg"
    file_path.write_bytes(b"image")
    args = SimpleNamespace(
        items_json=None,
        file_field="file_0",
        title=None,
        description=None,
        note=None,
        asset_type="image",
        final_tags_json=(
            '[{"dimension_code":"scene","create_tags":'
            '[{"code":"kitchen","name":"厨房","synopsis":"","parent_id":null,"aliases":[]}]}]'
        ),
        batch_tag=["厨房"],
        batch_tags="统一标签,新品",
        final_tags_dimension="scene",
    )

    items = script.json.loads(script._build_manual_items_json(args, file_paths=[file_path]))
    names = [tag["name"] for tag in items[0]["final_tags"][0]["create_tags"]]

    assert names == ["厨房", "统一标签", "新品"]
