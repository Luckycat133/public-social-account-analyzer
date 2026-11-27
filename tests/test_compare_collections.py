from pathlib import Path
from datetime import datetime
import json
import subprocess
import sys

import pytest

from analysis.compare import ARTIFACT, ComparisonError, run
from collectors.bilibili import _build_post_raw_from_medialist
from immutable_workspace import ImmutableWorkspace, WorkspaceError
from run_pipeline import COLLECTION_ARTIFACTS

DATA = Path(__file__).with_name("fixtures") / "comparison-collections-v1.json"
ROOT = Path(__file__).resolve().parents[1]
DATES = ["2026-10-01T00:00:00Z", "2026-10-03T00:00:00Z", "2026-10-05T00:00:00Z"]


def _seal(directory, allowed, files):
    with ImmutableWorkspace.reserve(directory, allowed_artifacts=allowed) as ws:
        for name, obj in files.items():
            with ws.open_binary(name) as stream:
                stream.write(obj if isinstance(obj, bytes) else json.dumps(obj).encode())
        return ws.commit()


def _collection(directory, spec, platform="bilibili", *, count=None):
    account, capture = spec["account"], spec["capture"]
    url = (f"https://space.bilibili.com/{account}" if platform == "bilibili" else
           f"https://weibo.com/u/{account}")
    rows = [
        {"platform": platform, "post_id": pid, "published_at": stamp,
         "likes": likes, "comments": comment, "shares": 0,
         "field_visibility": {"likes": visibility}, "collected_at": capture,
         "collection_status": "SUCCESS"}
        for pid, stamp, likes, comment, visibility in spec["sample"]
    ]
    if spec.get("extra"):
        rows += spec["extra"]
    return _seal(directory, COLLECTION_ARTIFACTS, {
        "source/profile.json": {"platform": platform, "account_id": account,
                                "profile_url": url, "collected_at": capture},
        "task.json": {"task_id": f"{platform}-{account}-{capture}",
                      "platform": platform, "profile_url": url, "task_status": "PARTIAL",
                      "collected_at": capture, "collected_count": len(rows) if count is None else count,
                      "requested_limit": 30},
        "source/posts.jsonl": "".join(json.dumps(row) + "\n" for row in rows).encode(),
    })


@pytest.fixture
def collections(tmp_path):
    fixture = json.loads(DATA.read_text())
    dirs = {key: str(tmp_path / key) for key in fixture}
    refs = {key: _collection(dirs[key], spec) for key, spec in fixture.items()}
    return fixture, dirs, refs


def _read(output):
    return json.loads((output / ARTIFACT).read_text())


def test_accounts_deterministic_and_bound(collections, tmp_path):
    _, dirs, refs = collections
    paths = [dirs["b_now"], dirs["a_now"]]
    first, second = tmp_path / "first", tmp_path / "second"
    d1 = run("accounts", DATES[1:], paths, str(first))
    d2 = run("accounts", DATES[1:], paths[::-1], str(second))
    assert (first / ARTIFACT).read_bytes() == (second / ARTIFACT).read_bytes()
    assert d1 == d2 == run("accounts", DATES[1:], paths, str(first), verify=True)
    report = _read(first)
    assert set(report) == {"schema_version", "mode", "platform", "scope", "window", "snapshot_span", "accounts"}
    assert report["scope"] == "observed_public_sample_only"
    assert report["snapshot_span"] == {"earliest": "2026-10-05T02:00:00+00:00",
                                      "latest": "2026-10-05T03:00:00+00:00"}
    a, b = report["accounts"]
    assert [a["account_id"], b["account_id"]] == ["101", "102"]
    assert a["collection_commit_sha256"] == refs["a_now"]
    assert b["collection_commit_sha256"] == refs["b_now"]
    assert a["coverage"]["sealed_posts"] == 4
    assert a["metrics"]["likes"] == {"observed": 1, "denominator": 1, "total": 4}
    assert b["metrics"]["likes"] == {"observed": 1, "denominator": 2, "total": None}
    assert b["metrics"]["shares"] == {"observed": 2, "denominator": 2, "total": 0}
    with pytest.raises(WorkspaceError):
        run("accounts", DATES[1:], paths, str(first))


def test_period_cohorts_separate_from_shared_post_metrics(collections, tmp_path):
    _, dirs, refs = collections
    paths = [dirs["a_prior"], dirs["a_now"]]
    output = tmp_path / "periods"
    run("periods", DATES, paths, str(output))
    report = _read(output)
    prior, current = report["previous"], report["current"]
    assert prior["collection_commit_sha256"] == refs["a_prior"]
    assert prior["coverage"]["unknown_publication_time"] == 1
    assert (prior["sample_post_count"], current["sample_post_count"]) == (2, 1)
    assert report["sample_count_delta"] == -1
    assert report["sample_total_deltas"] == {"likes": 1, "comments": None, "shares": 0}
    assert report["shared_post_metric_changes"] == [
        {"post_id": "BVprior1", "previous_observed_at": "2026-10-03T01:00:00+00:00",
         "current_observed_at": "2026-10-05T02:00:00+00:00", "metric_deltas": {"likes": 5, "comments": -1, "shares": 0}},
        {"post_id": "BVprior2", "previous_observed_at": "2026-10-03T01:00:00+00:00",
         "current_observed_at": "2026-10-05T02:00:00+00:00", "metric_deltas": {"likes": None, "comments": None, "shares": 0}},
    ]


@pytest.mark.parametrize("bad", ["extra", "wrong_type", "wrong_digest", "wrong_metric", "duplicate_key", "unknown_field"])
def test_verifier_rejects_bad_but_independently_sealed_delivery(collections, tmp_path, bad):
    _, dirs, _ = collections
    paths = [dirs["a_prior"], dirs["a_now"]]
    original, altered = tmp_path / "original", tmp_path / "altered"
    run("periods", DATES, paths, str(original))
    report = _read(original)
    if bad == "extra":
        report["lookalike"] = None
    if bad == "wrong_type":
        report["schema_version"] = True
    if bad == "wrong_digest":
        report["previous"]["collection_commit_sha256"] = "0" * 64
    if bad == "wrong_metric":
        report["shared_post_metric_changes"][0]["metric_deltas"]["likes"] = 0
    if bad == "unknown_field":
        del report["current"]["metrics"]["likes"]["observed"]
    payload = json.dumps(report)
    if bad == "duplicate_key":
        payload = payload[:-1] + ', "schema_version": 1}'
    _seal(altered, {ARTIFACT}, {ARTIFACT: payload.encode()})
    with pytest.raises(ComparisonError, match="schema/evidence mismatch|duplicate JSON key"):
        run("periods", DATES, paths, str(altered), verify=True)


@pytest.mark.parametrize("mode,keys,bounds,message", [
    ("accounts", ("a_prior", "a_now"), DATES[:2], "distinct"),
    ("periods", ("b_now", "a_now"), DATES, "same account"),
    ("periods", ("a_now", "a_prior"), DATES, "snapshot order"),
    ("periods", ("a_prior", "a_now"), [DATES[0], DATES[1], "2026-10-06T00:00:00Z"], "equal"),
    ("accounts", ("a_prior", "b_now"), DATES[1:], "after a collection"),
    ("accounts", ("a_now", "b_now"), ["2026-10-03T00:00:00", DATES[2]], "explicit timezone"),
])
def test_rejects_mismatched_scopes(collections, tmp_path, mode, keys, bounds, message):
    _, dirs, _ = collections
    out = tmp_path / "out"
    with pytest.raises(ComparisonError, match=message):
        run(mode, bounds, [dirs[k] for k in keys], str(out))
    assert not out.exists()


def test_rejects_cross_platform_and_modified_source(collections, tmp_path):
    fixture, dirs, _ = collections
    weibo = tmp_path / "weibo"
    _collection(weibo, fixture["b_now"], platform="weibo")
    output = tmp_path / "out"
    with pytest.raises(ComparisonError, match="cross-platform"):
        run("accounts", DATES[1:], [dirs["a_now"], str(weibo)], str(output))
    Path(dirs["a_now"], "source/posts.jsonl").write_text("tampered")
    with pytest.raises(WorkspaceError):
        run("accounts", DATES[1:], [dirs["a_now"], dirs["b_now"]], str(output))
    assert not output.exists()


def test_workbench_cli_build_and_verify(collections, tmp_path):
    _, dirs, _ = collections
    command = [sys.executable, str(ROOT / "skill/scripts/analysis/compare.py"), "accounts",
               "--boundary", DATES[1], "--boundary", DATES[2], "--collection", dirs["a_now"],
               "--collection", dirs["b_now"], "--output", str(tmp_path / "out")]
    created = subprocess.run(command, capture_output=True, text=True, check=True)
    verified = subprocess.run(command + ["--verify"], capture_output=True, text=True, check=True)
    assert created.stdout == verified.stdout

def test_real_adapter_normalization_offline_sealing_and_window(collections, tmp_path):
    fixture, dirs, _ = collections
    url = "https://space.bilibili.com/103"
    utc = datetime.fromisoformat("2026-10-03T00:00:00+00:00")
    record = _build_post_raw_from_medialist(
        {"bv_id": "BVvalid123", "pubtime": int(utc.timestamp()),
         "copy_right": 1, "cnt_info": {"thumb_up": 0, "reply": 1}},
        url,
    )
    assert record["published_at"] == "2026-10-03T08:00:00+08:00"
    source = tmp_path / "adapter-output"
    rejected = dict(record, post_id="BVremoved42", collection_status="DELETED")
    pinned = dict(record, post_id="BVsticky", is_pinned=True)
    unknown = dict(record, post_id="local:4", platform_metrics={"platform_post_id_known": False})
    _collection(source, {"account": "103", "capture": fixture["b_now"]["capture"],
                         "sample": [], "extra": [record, rejected, pinned, unknown]})
    output = tmp_path / "comparison"
    run("accounts", DATES[1:], [str(source), dirs["b_now"]], str(output))
    account = _read(output)["accounts"][1]
    assert account["sample_post_count"] == 1
    assert account["metrics"]["likes"] == {"denominator": 1, "observed": 1, "total": 0}
    assert account["coverage"]["excluded_post_type"] == 1
    assert account["coverage"]["unavailable_posts"] == 1
    assert account["coverage"]["unknown_identity_posts"] == 1


def test_duplicate_post_id_across_distinct_accounts_is_not_ranked(collections, tmp_path):
    fixture, dirs, _ = collections
    source = tmp_path / "duplicate"
    _collection(source, dict(fixture["a_now"], account="103"))
    with pytest.raises(ComparisonError, match="multiple accounts"):
        run("accounts", DATES[1:], [str(source), dirs["a_now"]], str(tmp_path / "out"))

def test_incremental_collection_reused_observation_is_not_an_observed_zero_delta(collections, tmp_path):
    fixture, dirs, _ = collections
    old_raw = [json.loads(line) for line in Path(dirs["a_prior"], "source/posts.jsonl").read_text().splitlines()]
    current = tmp_path / "incremental"
    _collection(current, dict(fixture["a_now"], sample=fixture["a_now"]["sample"][2:], extra=old_raw[:2]))
    out = tmp_path / "out"
    run("periods", DATES, [dirs["a_prior"], str(current)], str(out))
    changes = _read(out)["shared_post_metric_changes"]
    assert len(changes) == 2
    for post in changes:
        assert post["previous_observed_at"] == post["current_observed_at"]
        assert post["metric_deltas"] == {"likes": None, "comments": None, "shares": None}
