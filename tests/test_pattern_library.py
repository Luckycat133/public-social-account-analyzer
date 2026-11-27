"""Replay the real sealed business pipeline before compiling its public recipes."""
from pathlib import Path
import hashlib
import json
import socket
import subprocess
import sys

import pytest

from analysis.pattern_library import ARTIFACT, PatternLibraryError, run
from immutable_workspace import ANALYSIS_ARTIFACTS, ImmutableWorkspace, WorkspaceError
from run_pipeline import COLLECTION_ARTIFACTS, run_pipeline
from test_business_insights import (
    _business_result, _classification_payload, _minimal_template, _posts, _profile,
)

ROOT = Path(__file__).resolve().parents[1]


def _seal(path: Path, allowed, data: dict):
    with ImmutableWorkspace.reserve(path, allowed_artifacts=allowed) as workspace:
        for name, value in data.items():
            with workspace.open_binary(name) as stream:
                stream.write(value if isinstance(value, bytes) else json.dumps(value).encode())
        return workspace.commit()


def _analysis(tmp: Path, name: str, *, linkless=False, draft=False, new_recipe=False) -> Path:
    posts = _posts()
    profile = _profile()
    if linkless:
        posts[10]["post_url"] = None
        posts[10]["source_url"] = profile["profile_url"]
    collection = tmp / f"collection-{name}"
    digest = _seal(collection, COLLECTION_ARTIFACTS, {
        "source/profile.json": profile,
        "task.json": {"task_id": f"source-{name}", "platform": "douyin",
                      "profile_url": profile["profile_url"], "task_status": "COMPLETED",
                      "analysis_goal": "分析公开内容策略", "collected_count": 15,
                      "requested_limit": 15},
        "source/posts.jsonl": "".join(json.dumps(post) + "\n" for post in posts).encode(),
    })
    output = tmp / f"analysis-{name}"
    if draft:
        run_pipeline(str(collection), str(output), template_text=_minimal_template(), with_taxonomy_prompt=True)
        return output
    classification_payload = _classification_payload()
    classification = tmp / f"classification-{name}.json"
    classification.write_bytes(classification_payload)
    business = _business_result(digest, hashlib.sha256(classification_payload).hexdigest())
    if new_recipe:
        business["content_modes"][1]["recipe"] = "换用公开问答结构"
    business_file = tmp / f"business-{name}.json"
    business_file.write_text(json.dumps(business), encoding="utf-8")
    run_pipeline(str(collection), str(output), template_text=_minimal_template(),
                 with_taxonomy_prompt=True, classification_results_path=str(classification),
                 with_business_insights=True, business_insight_results_path=str(business_file))
    return output


def test_aggregation_replays_real_sources_keeps_partial_and_deduplicates(tmp_path, monkeypatch):
    def network(*args, **kwargs):
        pytest.fail("offline library opened a network connection")
    monkeypatch.setattr(socket, "create_connection", network)
    first = _analysis(tmp_path, "complete")
    second = _analysis(tmp_path, "half", linkless=True, new_recipe=True)
    draft = _analysis(tmp_path, "draft", draft=True)
    a, b = tmp_path / "a", tmp_path / "b"
    inputs = [str(first), str(second), str(draft)]
    digest = run(inputs, str(a))
    assert run(inputs[::-1], str(b)) == digest
    payload = (a / ARTIFACT).read_bytes()
    assert payload == (b / ARTIFACT).read_bytes()
    assert run(inputs, str(a), verify=True) == digest
    library = json.loads(payload)
    assert library["scope"] == "observed_public_samples_not_rankings"
    assert len(library["sources"]) == 3
    assert len(library["patterns"]) == 6
    source_status = {row["analysis_commit_sha256"]: row["business_status"] for row in library["sources"]}
    assert set(source_status.values()) == {"completed", "partial-model", "not-requested"}
    pattern = next(row for row in library["patterns"] if row["name"] == "内容模式 01")
    assert pattern["source_count"] == 2
    assert pattern["distinct_post_count"] == 1
    assert pattern["partial_observation_count"] == 1
    half = next(row for row in pattern["observations"] if row["evidence_state"] == "partial")
    assert source_status[half["analysis_commit_sha256"]] == "partial-model"
    assert half["evidence_posts"] == [{"post_id": "11", "item_url": None}]
    assert "excerpt" not in payload.decode()


def test_cli_build_and_verify_work_with_one_analysis(tmp_path):
    analysis = _analysis(tmp_path, "analysis")
    command = [sys.executable, str(ROOT / "skill/scripts/analysis/pattern_library.py"),
               "--analysis", str(analysis), "--output", str(tmp_path / "library")]
    first = subprocess.run(command, check=True, capture_output=True, text=True)
    verified = subprocess.run(command + ["--verify"], check=True, capture_output=True, text=True)
    assert first.stdout == verified.stdout
    with pytest.raises(WorkspaceError):
        run([str(analysis)], str(analysis / "forbidden"))


@pytest.mark.parametrize("mutation", ["invented-recipe", "source-body", "provenance-digest"])
def test_resealed_analysis_tampering_is_rejected_before_output(tmp_path, mutation):
    analysis = _analysis(tmp_path, "source")
    files = {p.relative_to(analysis).as_posix(): p.read_bytes() for p in analysis.rglob("*")
             if p.is_file() and p.name not in {".complete", "manifest.json"}}
    if mutation == "invented-recipe":
        value = json.loads(files["analysis.json"])
        value["business_insights"]["content_modes"][0]["recipe"] = "篡改配方"
        files["analysis.json"] = json.dumps(value).encode()
    elif mutation == "source-body":
        files["source/posts.jsonl"] += b"\n"
    else:
        value = json.loads(files["source/collection-provenance.json"])
        value["collection_commit_sha256"] = "0" * 64
        files["source/collection-provenance.json"] = json.dumps(value).encode()
    fake, output = tmp_path / "fake", tmp_path / "out"
    _seal(fake, ANALYSIS_ARTIFACTS, files)
    with pytest.raises(PatternLibraryError, match="digest|evidence replay"):
        run([str(fake)], str(output))
    assert not output.exists()


def test_same_collection_cannot_count_twice_and_output_schema_is_exact(tmp_path):
    analysis = _analysis(tmp_path, "source")
    source = str(analysis)
    with pytest.raises(PatternLibraryError, match="one analysis per collection"):
        run([source, source], str(tmp_path / "reject"))
    output, forged = tmp_path / "out", tmp_path / "forged"
    run([source], str(output))
    library = json.loads((output / ARTIFACT).read_text())
    library["patterns"][0]["distinct_post_count"] += 1
    _seal(forged, {ARTIFACT}, {ARTIFACT: library})
    with pytest.raises(PatternLibraryError, match="schema/evidence mismatch"):
        run([source], str(forged), verify=True)
