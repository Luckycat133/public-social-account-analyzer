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
import stat
import sys
import csv

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _d in (os.path.join(_REPO_ROOT, "skill", "scripts"), os.path.join(_REPO_ROOT, "scripts")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

import collect  # noqa: E402
import analyze  # noqa: E402
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


def _exact_tree_digest(root):
    root = os.path.abspath(root)
    entries = [root]
    for current, directories, files in os.walk(root, followlinks=False):
        directories.sort()
        files.sort()
        entries.extend(os.path.join(current, name) for name in directories + files)
    digest = hashlib.sha256()
    for path in sorted(entries):
        metadata = os.lstat(path)
        relative = os.path.relpath(path, root)
        digest.update(relative.encode("utf-8", errors="surrogateescape"))
        digest.update(b"\0")
        digest.update(str(stat.S_IFMT(metadata.st_mode)).encode("ascii"))
        digest.update(b"\0")
        digest.update(str(metadata.st_dev).encode("ascii"))
        digest.update(b":")
        digest.update(str(metadata.st_ino).encode("ascii"))
        digest.update(b"\0")
        if stat.S_ISLNK(metadata.st_mode):
            digest.update(os.readlink(path).encode("utf-8", errors="surrogateescape"))
        elif stat.S_ISREG(metadata.st_mode):
            with open(path, "rb") as handle:
                digest.update(handle.read())
        digest.update(b"\0")
    return digest.hexdigest()


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


def test_collection_csv_round_trips_structured_fields_and_nullable_booleans(
    tmp_path,
):
    path = tmp_path / "normalized-posts.csv"
    collect._write_csv(
        [
            {
                "platform": "bilibili",
                "post_id": "BVcsv",
                "hashtags": ["中文", "tag"],
                "is_pinned": False,
                "is_repost": None,
                "platform_metrics": {"z": 2, "a": True},
                "field_visibility": {"views": "visible"},
                "collection_status": "SUCCESS",
                "collection_status_source": "declared",
            }
        ],
        str(path),
    )

    with path.open(newline="", encoding="utf-8") as handle:
        row = next(csv.DictReader(handle))
    assert row["hashtags"] == '["中文","tag"]'
    assert row["platform_metrics"] == '{"a":true,"z":2}'
    assert row["field_visibility"] == '{"views":"visible"}'
    assert row["is_pinned"] == "false"
    assert row["is_repost"] == ""

    post = analyze.build_posts([row])[0]
    assert post["hashtags"] == ["中文", "tag"]
    assert post["platform_metrics"] == {"a": True, "z": 2}
    assert post["field_visibility"] == {"views": "visible"}
    assert post["is_pinned"] is False
    assert post["is_repost"] is None


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
    assert all(p["collection_status"] == "PARTIAL" for p in merged)
    assert all(
        p["collection_status_source"] == "inferred_missing" for p in merged
    )
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


@pytest.mark.parametrize("historical_repr", [False, True])
def test_csv_only_resume_restores_cell_types_in_new_jsonl(
    monkeypatch, tmp_path, historical_repr
):
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])
    old = tmp_path / "csv-only"
    old.mkdir()
    (old / "source").mkdir()
    row = {
        "platform": "bilibili",
        "post_id": "BV_CSV",
        "bvid": "BV_CSV",
        "published_at": "2026-07-15T10:00:00+08:00",
        "hashtags": ["中文", "tag"],
        "is_pinned": False,
        "is_repost": None,
        "is_promoted": True,
        "views": 7,
        "platform_metrics": {"nested": {"ok": True}},
        "field_visibility": {"views": "visible"},
        "collection_status": "SUCCESS",
        "collection_status_source": "declared",
    }
    csv_path = old / "normalized-posts.csv"
    if historical_repr:
        with csv_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(row))
            writer.writeheader()
            writer.writerow(row)
    else:
        collect._write_csv([row], str(csv_path))

    assert collect.run(
        "https://space.bilibili.com/123",
        limit=30,
        out_dir=str(old),
        resume=True,
    ) == 0

    output = next(tmp_path.glob("csv-only-resume-*"))
    with (output / "source" / "posts.jsonl").open(encoding="utf-8") as handle:
        posts = [json.loads(line) for line in handle if line.strip()]
    resumed = next(post for post in posts if post["post_id"] == "BV_CSV")
    assert resumed["hashtags"] == ["中文", "tag"]
    assert resumed["is_pinned"] is False
    assert resumed["is_repost"] is None
    assert resumed["is_promoted"] is True
    assert resumed["views"] == 7
    assert resumed["platform_metrics"] == {"nested": {"ok": True}}
    assert resumed["field_visibility"] == {"views": "visible"}
    assert resumed["collection_status"] == "SUCCESS"
    assert resumed["collection_status_source"] == "declared"


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


@pytest.mark.parametrize("destination_kind", ["direct", "symlinked-ancestor"])
def test_resume_rejects_destination_inside_old_and_preserves_exact_tree(
    monkeypatch, tmp_path, destination_kind
):
    monkeypatch.setattr(collect, "_load_adapters", lambda: [FakeAdapter()])
    monkeypatch.setattr(collect, "_pick", lambda adapters, url: adapters[0])
    old = tmp_path / "committed"
    assert collect.run(
        "https://space.bilibili.com/123", out_dir=str(old)
    ) == 0
    before = _exact_tree_digest(old)

    if destination_kind == "direct":
        new = old / "nested"
    else:
        alias = tmp_path / "alias"
        try:
            alias.symlink_to(old, target_is_directory=True)
        except OSError:
            pytest.skip("directory symlinks are unavailable")
        new = alias / "source" / "nested"

    adapter_loads = 0

    def load_adapters():
        nonlocal adapter_loads
        adapter_loads += 1
        return [FakeAdapter()]

    monkeypatch.setattr(collect, "_load_adapters", load_adapters)
    rc = collect.run(
        "https://space.bilibili.com/123",
        out_dir=str(old),
        resume=True,
        resume_out=str(new),
    )

    assert rc == 2
    assert adapter_loads == 0
    assert _exact_tree_digest(old) == before
    assert not new.exists()
