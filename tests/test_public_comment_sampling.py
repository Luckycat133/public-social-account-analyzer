"""Exercise collect -> immutable source -> analysis -> both rendered reports offline."""
from pathlib import Path
import json
import socket

import pytest

import collect
from collectors.douyin import DouyinError
from immutable_workspace import ANALYSIS_ARTIFACTS, verify_committed_workspace
from run_pipeline import COLLECTION_ARTIFACTS, run_pipeline
from test_analysis_pipeline import _minimal_template, _sample_post, _sample_profile

FIXTURES = json.loads((Path(__file__).with_name("fixtures") / "public-comment-sampling-v1.json").read_text())
RATE_RESPONSE_SENTINEL = "private-response-must-not-be-persisted"


@pytest.mark.parametrize("name", list(FIXTURES))
def test_offline_public_comment_failure_preserves_only_verified_partial_evidence(name, tmp_path, monkeypatch):
    case = FIXTURES[name]

    def blocked_socket(*args, **kwargs):
        pytest.fail("offline fixture attempted a real network connection")

    class FixtureAdapter:
        platform = "douyin"
        calls = []

        def supports(self, url):
            return True

        def check_access(self, url):
            return {"accessible": True}

        def collect_profile(self, url):
            return _sample_profile()

        def collect_post_list(self, url, limit=30, date_range=None):
            return [_sample_post(str(i)) for i in range(1, 4)]

        def collect_comments(self, url, limit=20):
            assert limit == 20
            self.calls.append(url)
            reply = case["responses"][len(self.calls) - 1]
            if reply == "rate":
                raise DouyinError("RATE_LIMITED", RATE_RESPONSE_SENTINEL)
            assert reply != "unused", "collector failed to stop on platform protection"
            return reply

    monkeypatch.setattr(socket, "create_connection", blocked_socket)
    adapter = FixtureAdapter()
    monkeypatch.setattr(collect, "_load_adapters", lambda: [adapter])
    source, output = tmp_path / "collection", tmp_path / "analysis"
    assert collect.run("https://www.douyin.com/user/example", out_dir=str(source),
                       include_comments=True, limit=3) == 0
    assert len(adapter.calls) == case["called"]
    verify_committed_workspace(str(source), allowed_artifacts=COLLECTION_ARTIFACTS)
    result = run_pipeline(str(source), str(output), template_text=_minimal_template())
    verify_committed_workspace(str(output), allowed_artifacts=ANALYSIS_ARTIFACTS)
    analysis = json.loads((output / "analysis.json").read_text())
    task = json.loads((output / "task.json").read_text())
    comments = analysis["comment_analysis"]
    assert comments["sampling_state"] == case["state"]
    assert comments["sampled_comment_count"] == case["count"]
    ledger = comments["collection_ledger"]
    assert (ledger["failures"], ledger["stop_reason"]) == (case["failures"], case["stop"])
    assert analysis["sample_boundary"]["valid"] == 3
    assert comments["semantic"]["insights"] is None
    if case["count"]:
        retained = (source / "source/comments.jsonl").read_bytes()
        assert retained == (output / "source/comments.jsonl").read_bytes()
        record = json.loads(retained)
        assert record["likes"] == 0
        assert record["parent_post_url"] == adapter.calls[0]
        if name == "half_rows":
            assert record["text"] is None
            assert comments["field_coverage"]["text"]["present"] == 0
            assert not comments["representative_comments"]
    if case["state"] in {"partial", "unavailable"}:
        assert result.task_status == "PARTIAL"
        assert f"COMMENT_SAMPLE_{case['state'].upper()}" in task["partial_reasons"]
    else:
        assert not any(reason.startswith("COMMENT_SAMPLE_") for reason in task["partial_reasons"])
    for path in (output / "account-analysis-report.md", output / "dashboard.html"):
        rendered = path.read_text()
        assert "sampling_state" in rendered
        assert case["state"] in rendered
        assert RATE_RESPONSE_SENTINEL not in rendered
        assert "nonmatching parent sentinel" not in rendered
