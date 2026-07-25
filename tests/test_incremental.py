"""增量续采(collect.py --resume)离线测试:不依赖网络。

通过 monkeypatch _load_adapters/_pick 注入一个 FakeAdapter,验证:
  1) 既有 posts.jsonl 被正确读取并以 post_id/bvid 去重合并(新覆盖旧);
  2) task.json 记录 incremental / existing_count / new_count;
  3) 无 --out 时 --resume 直接报错退出(rc=2);
  4) 既有数据为空时退化为全量采集(incremental=False)。
"""
import json
import hashlib
import os
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_REPO_ROOT, "skill", "scripts"), os.path.join(_REPO_ROOT, "scripts")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

import collect  # noqa: E402
from collectors.base import BaseCollector  # noqa: E402


class FakeAdapter(BaseCollector):
    platform = "bilibili"

    def supports(self, url):
        return True

    def check_access(self, url):
        return {"accessible": True}

    def collect_profile(self, url):
        return {"platform": "bilibili", "account_name": "acct",
                "field_visibility": {"followers": "visible"}}

    def collect_post_list(self, url, limit=30, date_range=None):
        # 两条:一条与既有重叠(BV_OLD1,发布时间晚于 since 故通过本地日期过滤),
        # 一条全新(BV_NEW1)
        return [
            {"post_id": "BV_NEW1", "bvid": "BV_NEW1",
             "published_at": "2026-07-20T10:00:00+08:00", "views": 100},
            {"post_id": "BV_OLD1", "bvid": "BV_OLD1",
             "published_at": "2026-07-18T10:00:00+08:00", "views": 999},
        ]

    def collect_post_detail(self, post_url):
        return {}


def _setup_existing(out_dir, posts):
    src = os.path.join(out_dir, "source")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "posts.jsonl"), "w", encoding="utf-8") as f:
        for p in posts:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")


def test_merge_incremental():
    existing = [
        {"post_id": "BV_OLD1", "views": 5},
        {"post_id": "BV_KEEP", "views": 7},
    ]
    new = [
        {"post_id": "BV_OLD1", "views": 999},   # 覆盖旧
        {"post_id": "BV_NEW1", "views": 11},     # 全新
        {"bvid": "NOKEY1"},                       # 无主键,直接追加
    ]
    merged, new_count = collect._merge_incremental(existing, new)
    keys = sorted(collect._post_key(p) for p in merged)
    assert keys == ["BV_KEEP", "BV_NEW1", "BV_OLD1", "NOKEY1"], keys
    by_key = {collect._post_key(p): p for p in merged}
    assert by_key["BV_OLD1"]["views"] == 999       # 新覆盖旧
    assert new_count == 2                           # BV_NEW1 + NOKEY1


def test_latest_published_at():
    posts = [
        {"published_at": "2026-07-01T00:00:00+08:00"},
        {"published_at": "2026-07-20T00:00:00+08:00"},
        {"published_at": "bad"},
    ]
    assert collect._latest_published_at(posts) == "2026-07-20T00:00:00+08:00"


def test_resume_end_to_end_creates_distinct_outputs_and_never_mutates_old(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])
    old = tmp_path / "existing"
    # 既有数据:3 条,最新为 2026-07-15
    _setup_existing(str(old), [
        {"post_id": "BV_OLD1", "bvid": "BV_OLD1", "published_at": "2026-07-12T10:00:00+08:00", "views": 5},
        {"post_id": "BV_KEEP", "bvid": "BV_KEEP", "published_at": "2026-07-14T10:00:00+08:00", "views": 7},
        {"post_id": "BV_PRE", "bvid": "BV_PRE", "published_at": "2026-07-15T10:00:00+08:00", "views": 3},
    ])
    old_hashes = {
        path.relative_to(old).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in old.rglob("*")
        if path.is_file()
    }

    results = [
        collect.run(
            "https://space.bilibili.com/123",
            limit=30,
            out_dir=str(old),
            resume=True,
        )
        for _ in range(2)
    ]
    assert results == [0, 0]
    outputs = sorted(tmp_path.glob("existing-resume-*"))
    assert len(outputs) == 2
    assert outputs[0] != outputs[1]
    new = outputs[0]
    # 合并后:既有3 + 新增1(BV_NEW1) = 4;BV_OLD1 被覆盖
    with open(new / "source" / "posts.jsonl", encoding="utf-8") as f:
        merged = [json.loads(l) for l in f if l.strip()]
    keys = sorted(collect._post_key(p) for p in merged)
    assert keys == ["BV_KEEP", "BV_NEW1", "BV_OLD1", "BV_PRE"], keys
    by_key = {collect._post_key(p): p for p in merged}
    assert by_key["BV_OLD1"]["views"] == 999        # 新覆盖旧
    task = json.loads((new / "task.json").read_text(encoding="utf-8"))
    assert task["incremental"] is True
    assert task["existing_count"] == 3
    assert task["new_count"] == 1
    assert task["collected_count"] == 4
    assert task["resume_source"]["format"] == "legacy-read-only"
    assert len(task["resume_source"]["digest"]) == 64
    assert all((output / ".complete").is_file() for output in outputs)
    assert {
        path.relative_to(old).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in old.rglob("*")
        if path.is_file()
    } == old_hashes


def test_resume_without_out_returns_error_before_adapter_or_workspace(
    monkeypatch, tmp_path
):
    # 无 --out 时 --resume 必须在加载适配器和创建默认目录前报错(rc=2)
    monkeypatch.setattr(collect, "_HERE", str(tmp_path / "skill" / "scripts"))
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("adapter loading must not happen")
        ),
    )

    rc = collect.run("https://space.bilibili.com/123", out_dir=None, resume=True)

    assert rc == 2
    assert not (tmp_path / "skill" / "workspace").exists()


def test_resume_effective_since_after_date_to_rejects_without_mutation(
    monkeypatch, tmp_path
):
    out = tmp_path / "existing"
    original = {
        "post_id": "BV_KEEP",
        "bvid": "BV_KEEP",
        "published_at": "2026-07-20T10:00:00+08:00",
    }
    _setup_existing(str(out), [original])
    before = (out / "source" / "posts.jsonl").read_bytes()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])

    rc = collect.run(
        "https://space.bilibili.com/123",
        out_dir=str(out),
        resume=True,
        since="2026-07-25",
        date_to="2026-07-24",
    )

    assert rc == 2
    assert (out / "source" / "posts.jsonl").read_bytes() == before
    assert sorted(path.relative_to(out).as_posix() for path in out.rglob("*")) == [
        "source",
        "source/posts.jsonl",
    ]


def test_resume_degrade_when_empty_writes_new_workspace(monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])
    old = tmp_path / "legacy-empty"
    (old / "source").mkdir(parents=True)
    rc = collect.run(
        "https://space.bilibili.com/123",
        limit=30,
        out_dir=str(old),
        resume=True,
    )
    assert rc == 0
    outputs = list(tmp_path.glob("legacy-empty-resume-*"))
    assert len(outputs) == 1
    task = json.loads((outputs[0] / "task.json").read_text(encoding="utf-8"))
    assert task["incremental"] is False
    assert task["existing_count"] == 0
    assert task["collected_count"] == 2
    assert list(old.iterdir()) == [old / "source"]


def test_resume_from_committed_workspace_records_exact_commit_digest(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])
    old = tmp_path / "committed"
    new = tmp_path / "resumed"

    assert collect.run(
        "https://space.bilibili.com/123", out_dir=str(old)
    ) == 0
    before = {
        path.relative_to(old).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in old.rglob("*")
        if path.is_file()
    }
    commit_digest = json.loads(
        (old / "manifest.json").read_text(encoding="utf-8")
    )
    assert commit_digest["format"].endswith("immutable-workspace-v1")

    assert collect.run(
        "https://space.bilibili.com/123",
        out_dir=str(old),
        resume=True,
        resume_out=str(new),
    ) == 0

    task = json.loads((new / "task.json").read_text(encoding="utf-8"))
    marker_digest = (old / ".complete").read_text(encoding="ascii").split("=", 1)[1].strip()
    assert task["resume_source"] == {
        "format": collect.IMMUTABLE_WORKSPACE_FORMAT,
        "digest_algorithm": "sha256",
        "digest": marker_digest,
    }
    assert {
        path.relative_to(old).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in old.rglob("*")
        if path.is_file()
    } == before


def test_corrupt_committed_resume_source_is_rejected_before_adapters(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])
    old = tmp_path / "committed"
    assert collect.run(
        "https://space.bilibili.com/123", out_dir=str(old)
    ) == 0
    payload = (old / "source" / "posts.jsonl").read_bytes()
    (old / "source" / "posts.jsonl").write_bytes(payload[:-1])
    monkeypatch.setattr(
        collect,
        "_load_adapters",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("adapters must not load for corrupt resume input")
        ),
    )

    assert collect.run(
        "https://space.bilibili.com/123",
        out_dir=str(old),
        resume=True,
    ) == 2
    assert list(tmp_path.glob("committed-resume-*")) == []
