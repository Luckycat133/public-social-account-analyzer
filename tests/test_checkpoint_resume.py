"""Crash-recovery checkpoint contracts for public collection tasks."""

from __future__ import annotations

import hashlib
import json

import pytest

import collect
from collectors.base import BaseCollector


BILIBILI_URL = "https://space.bilibili.com/123"
CHECKPOINT_FORMAT = "public-social-account-analyzer/collection-checkpoint-v1"
CHECKPOINT_ARTIFACTS = frozenset({"checkpoint.json", "source/posts.jsonl"})


def _post(post_id: str, views: int) -> dict:
    return {
        "platform": "bilibili",
        "post_id": post_id,
        "bvid": post_id,
        "post_url": f"https://www.bilibili.com/video/{post_id}",
        "source_url": f"https://www.bilibili.com/video/{post_id}",
        "published_at": "2026-07-27T10:00:00+08:00",
        "views": views,
        "collection_status": "SUCCESS",
    }


def _parameters(*, limit: int = 2) -> dict:
    return {
        "requested_limit": limit,
        "date_from": None,
        "date_to": None,
        "include_comments": False,
        "enrich_details": False,
        "collect_all": False,
        "max_items": None,
        "max_seconds": None,
        "max_scrolls": None,
        "analysis_goal": None,
        "browser_fallback": None,
    }


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _seal_checkpoint(path, *, posts=None, parameters=None) -> None:
    posts = list(posts or [_post("BV1", 1), _post("BV2", 2)])
    parameters = dict(parameters or _parameters())
    posts_payload = b"".join(
        _canonical_json_bytes(post) + b"\n" for post in posts
    )
    metadata = {
        "format": CHECKPOINT_FORMAT,
        "stage": "POST_LIST_COLLECTED",
        "platform": "bilibili",
        "profile_url": BILIBILI_URL,
        "parameters": parameters,
        "parameters_sha256": hashlib.sha256(
            _canonical_json_bytes(parameters)
        ).hexdigest(),
        "posts": {
            "path": "source/posts.jsonl",
            "digest_algorithm": "sha256",
            "digest": hashlib.sha256(posts_payload).hexdigest(),
            "count": len(posts),
        },
        "collected_at": "2026-07-27T10:00:00+08:00",
        "stop_reason": None,
        "diagnostic_code": None,
        "collection_coverage": {},
        "errors": [],
    }
    reservation = collect.ImmutableWorkspace.reserve(
        str(path), allowed_artifacts=CHECKPOINT_ARTIFACTS
    )
    try:
        with reservation.open_binary("source/posts.jsonl") as handle:
            handle.write(posts_payload)
        with reservation.open_binary("checkpoint.json") as handle:
            handle.write(_canonical_json_bytes(metadata) + b"\n")
        reservation.commit()
    finally:
        reservation.close()


class _InterruptedAdapter(BaseCollector):
    platform = "bilibili"

    def supports(self, url):
        return True

    def check_access(self, url):
        return {"accessible": True}

    def collect_post_list(self, url, limit=30, date_range=None):
        return [
            _post("BV1", 1),
            _post("BV1", 999),
            _post("BV2", 2),
        ]

    def collect_profile(self, url):
        raise KeyboardInterrupt("INTERRUPTED_AFTER_CHECKPOINT")

    def collect_post_detail(self, post_url):
        raise NotImplementedError


class _RecoveryAdapter(BaseCollector):
    platform = "bilibili"

    def supports(self, url):
        return True

    def check_access(self, url):
        raise AssertionError("checkpoint recovery must not repeat access")

    def collect_post_list(self, url, limit=30, date_range=None):
        raise AssertionError("checkpoint recovery must not repeat post collection")

    def collect_profile(self, url):
        return {
            "platform": "bilibili",
            "profile_url": BILIBILI_URL,
            "account_name": "恢复账号",
            "field_visibility": {"account_name": "visible"},
        }

    def collect_post_detail(self, post_url):
        raise NotImplementedError


def test_interrupted_task_resumes_from_sealed_checkpoint_without_duplicate_posts(
    monkeypatch, tmp_path
):
    first_output = tmp_path / "interrupted-output"
    checkpoint = tmp_path / "checkpoint"
    recovered_output = tmp_path / "recovered-output"
    monkeypatch.setattr(collect, "_load_adapters", lambda: [_InterruptedAdapter()])

    with pytest.raises(KeyboardInterrupt, match="INTERRUPTED_AFTER_CHECKPOINT"):
        collect.run(
            BILIBILI_URL,
            limit=2,
            out_dir=str(first_output),
            checkpoint_out=str(checkpoint),
        )

    assert checkpoint.joinpath(".complete").is_file()
    assert not first_output.joinpath(".complete").exists()

    monkeypatch.setattr(collect, "_load_adapters", lambda: [_RecoveryAdapter()])
    assert collect.run(
        BILIBILI_URL,
        limit=2,
        out_dir=str(recovered_output),
        resume_checkpoint=str(checkpoint),
    ) == 0

    posts = [
        json.loads(line)
        for line in recovered_output.joinpath("source/posts.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert [post["post_id"] for post in posts] == ["BV1", "BV2"]
    task = json.loads(
        recovered_output.joinpath("task.json").read_text(encoding="utf-8")
    )
    checkpoint_digest = checkpoint.joinpath(".complete").read_text(
        encoding="ascii"
    ).split("=", 1)[1].strip()
    assert task["checkpoint_source"] == {
        "format": CHECKPOINT_FORMAT,
        "digest_algorithm": "sha256",
        "digest": checkpoint_digest,
    }
    assert recovered_output.joinpath(".complete").is_file()


def test_checkpoint_parameter_mismatch_is_rejected_before_adapter_or_output(
    monkeypatch, tmp_path
):
    checkpoint = tmp_path / "checkpoint"
    output = tmp_path / "output"
    _seal_checkpoint(checkpoint)
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda: pytest.fail("adapter must not load for mismatched checkpoint"),
    )

    assert collect.run(
        BILIBILI_URL,
        limit=3,
        out_dir=str(output),
        resume_checkpoint=str(checkpoint),
    ) == 2
    assert not output.exists()


def test_tampered_checkpoint_is_rejected_before_adapter_or_output(
    monkeypatch, tmp_path
):
    checkpoint = tmp_path / "checkpoint"
    output = tmp_path / "output"
    _seal_checkpoint(checkpoint)
    checkpoint.joinpath("source/posts.jsonl").write_text(
        json.dumps(_post("BV-TAMPERED", 9)) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda: pytest.fail("adapter must not load for tampered checkpoint"),
    )

    assert collect.run(
        BILIBILI_URL,
        limit=2,
        out_dir=str(output),
        resume_checkpoint=str(checkpoint),
    ) == 2
    assert not output.exists()


def test_unsealed_checkpoint_directory_is_never_silently_resumed(
    monkeypatch, tmp_path
):
    checkpoint = tmp_path / "unsealed"
    output = tmp_path / "output"
    checkpoint.joinpath("source").mkdir(parents=True)
    checkpoint.joinpath("source/posts.jsonl").write_text(
        json.dumps(_post("BV1", 1)) + "\n",
        encoding="utf-8",
    )
    checkpoint.joinpath("checkpoint.json").write_text(
        json.dumps({"format": CHECKPOINT_FORMAT}),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda: pytest.fail("adapter must not load for unsealed checkpoint"),
    )

    assert collect.run(
        BILIBILI_URL,
        limit=2,
        out_dir=str(output),
        resume_checkpoint=str(checkpoint),
    ) == 2
    assert not output.exists()
