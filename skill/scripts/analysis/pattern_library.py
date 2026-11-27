"""Aggregate public-sample content recipes from sealed analysis workspaces."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from contextlib import ExitStack
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.analyze import analyze_in_memory
from analysis.compare import ComparisonError, _encode, _object
from analysis.normalize import normalize_in_memory
from collectors.url_policy import canonical_item_url, canonical_profile_url
from immutable_workspace import (
    ANALYSIS_ARTIFACTS, ANALYSIS_REQUIRED_ARTIFACTS, FORMAT, ImmutableWorkspace,
    VerifiedWorkspaceReader, WorkspaceError, _parse_manifest,
    preflight_workspace_target, reject_workspace_overlap,
)
from run_pipeline import (
    COLLECTION_ARTIFACTS, COLLECTION_REQUIRED_ARTIFACTS, PipelineError,
    _business_insight_json, _classification_json,
)
from task_contract import ANALYZABLE_TASK_STATUSES

ARTIFACT = "content-pattern-library.json"
RAW_BUSINESS = "source/business-insight-results.json"
RAW_CLASSIFICATION = "source/classification-results.json"
SOURCE_COPIES = {
    "source/profile.json": "source/profile.json",
    "source/posts.jsonl": "source/posts.jsonl",
    "task.json": "source/collection-task.json",
    "source/comments.jsonl": "source/comments.jsonl",
    "source/index-evidence.json": "source/index-evidence.json",
}
MAX_SOURCES = 16


class PatternLibraryError(ValueError):
    """The pattern library cannot be supported by these inputs."""


def _digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _read_source(reader: VerifiedWorkspaceReader) -> tuple[dict, list[dict]]:
    paths = {item["path"] for item in reader.manifest["artifacts"]}
    if not ANALYSIS_REQUIRED_ARTIFACTS <= paths:
        raise PatternLibraryError("expected a complete sealed analysis workspace")

    def read(path: str) -> bytes:
        return reader.read(path).payload

    provenance = _object(read("source/collection-provenance.json"))
    if provenance.get("source_format") != FORMAT:
        raise PatternLibraryError("analysis collection provenance format is invalid")
    manifest_bytes = (json.dumps(
        {"format": FORMAT, "artifacts": provenance.get("source_manifest_artifacts")},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ) + "\n").encode("utf-8")
    collection_manifest = _parse_manifest(manifest_bytes, COLLECTION_ARTIFACTS)
    collection_digest = _digest(manifest_bytes)
    if provenance.get("collection_commit_sha256") != collection_digest:
        raise PatternLibraryError("analysis collection digest does not match its provenance")

    inventory = {item["path"]: item for item in collection_manifest["artifacts"]}
    if not COLLECTION_REQUIRED_ARTIFACTS <= inventory.keys():
        raise PatternLibraryError("provenance is missing collection evidence")
    sealed = {}
    for original, copy in SOURCE_COPIES.items():
        if (original in inventory) != (copy in paths):
            raise PatternLibraryError("analysis collection evidence presence does not match")
        if original not in inventory:
            continue
        data = read(copy)
        expected = inventory[original]
        if len(data) != expected["size"] or _digest(data) != expected["sha256"]:
            raise PatternLibraryError("analysis collection evidence digest does not match")
        sealed[original] = data

    profile = _object(sealed["source/profile.json"])
    source_task = _object(sealed["task.json"])
    platform = profile.get("platform") or source_task.get("platform")
    if not isinstance(platform, str) or source_task.get("platform") != platform:
        raise PatternLibraryError("analysis platform identity is inconsistent")
    homepage = canonical_profile_url(platform, profile.get("profile_url"))
    if homepage is None:
        raise PatternLibraryError("analysis does not bind a supported public profile")
    if (source_task.get("profile_url") is not None
            and canonical_profile_url(platform, source_task["profile_url"]) != homepage):
        raise PatternLibraryError("analysis public profile conflicts with collection task")
    source_id = source_task.get("task_id")
    source_status = source_task.get("task_status")
    if (not isinstance(source_id, str) or not source_id.strip()
            or provenance.get("source_task_id") != source_id
            or not isinstance(source_status, str) or source_status not in ANALYZABLE_TASK_STATUSES):
        raise PatternLibraryError("analysis collection task binding is invalid")

    analysis = _object(read("analysis.json"))
    business = analysis.get("business_insights")
    if not isinstance(business, dict):
        raise PatternLibraryError("analysis lacks its business result contract")
    status = business.get("status")
    if status in ("completed", "partial-model"):
        if RAW_BUSINESS not in paths or RAW_CLASSIFICATION not in paths:
            raise PatternLibraryError("analysis business/classification source is missing")
        classification_bytes = read(RAW_CLASSIFICATION)
        # Replay the production validator from copied raw posts and model inputs,
        # never promoting alleged modes directly out of a sealed analysis.json.
        normalized = normalize_in_memory(profile, sealed["source/posts.jsonl"])
        replay = analyze_in_memory(
            profile, normalized.rows, source_task,
            classification_results=_classification_json(classification_bytes),
            business_insight_results=_business_insight_json(read(RAW_BUSINESS)),
            collection_commit_sha256=collection_digest,
            classification_results_sha256=_digest(classification_bytes),
            comments_payload=sealed.get("source/comments.jsonl"),
        ).analysis["business_insights"]
        if _encode(business) != _encode(replay):
            raise PatternLibraryError("analysis business result differs from evidence replay")
        modes = replay["content_modes"]
    elif status in ("not-requested", "pending-model"):
        if RAW_BUSINESS in paths or business.get("content_modes") != []:
            raise PatternLibraryError("uncompleted analysis must not supply content modes")
        modes = []
    else:
        raise PatternLibraryError("analysis business status is invalid")
    return {
        "analysis_commit_sha256": reader.source_digest,
        "collection_commit_sha256": collection_digest,
        "platform": platform,
        "profile_url": homepage,
        "business_status": status,
        "mode_count": len(modes),
    }, modes


def _build(readers: list[VerifiedWorkspaceReader]) -> dict:
    sources = []
    patterns: dict[tuple[str, str, str], dict] = {}
    seen = set()
    for reader in sorted(readers, key=lambda item: item.source_digest):
        source, modes = _read_source(reader)
        digest = source["collection_commit_sha256"]
        if digest in seen:
            raise PatternLibraryError("provide only one analysis per collection snapshot")
        seen.add(digest)
        sources.append(source)
        for mode in modes:
            key = (source["platform"], mode["name"], mode["recipe"])
            pattern = patterns.setdefault(key, {
                "pattern_id": "pattern-" + _digest(_encode({"key": key})),
                "platform": key[0], "name": key[1], "recipe": key[2],
                "observations": [],
            })
            by_id = {}
            for item in mode["evidence"]:
                post_id = item["post_id"]
                candidate = (
                    canonical_item_url(key[0], item["url"], post_id)
                    if item["item_url_known"] is True and item["platform"] == key[0]
                    else None
                )
                if candidate is not None or post_id not in by_id:
                    by_id[post_id] = candidate
            pattern["observations"].append({
                "analysis_commit_sha256": source["analysis_commit_sha256"],
                "source_mode_id": mode["id"],
                "evidence_posts": [{"post_id": post_id, "item_url": by_id[post_id]}
                                   for post_id in sorted(by_id)],
                "evidence_state": "item_linked" if all(by_id.values()) else "partial",
            })
    entries = sorted(patterns.values(), key=lambda item: item["pattern_id"])
    for pattern in entries:
        observations = pattern["observations"]
        pattern["source_count"] = len({item["analysis_commit_sha256"] for item in observations})
        pattern["distinct_post_count"] = len({
            item["post_id"]
            for row in observations for item in row["evidence_posts"]
            if item["item_url"] is not None
        })
        pattern["partial_observation_count"] = sum(row["evidence_state"] == "partial" for row in observations)
    return {
        "schema_version": 1,
        "scope": "observed_public_samples_not_rankings",
        "sources": sources,
        "patterns": entries,
    }


def run(sources: list[str], output: str, *, verify: bool = False) -> str:
    """Write a new immutable library, or recompute from its input workspaces."""
    if not 1 <= len(sources) <= MAX_SOURCES:
        raise PatternLibraryError("provide 1–16 sealed analysis workspaces")
    if not verify:
        output = preflight_workspace_target(output)
    for source in sources:
        reject_workspace_overlap(source, output)
    with ExitStack() as stack:
        readers = [stack.enter_context(VerifiedWorkspaceReader.open(path, allowed_artifacts=ANALYSIS_ARTIFACTS))
                   for path in sources]
        expected = _encode(_build(readers))
        if verify:
            delivery = stack.enter_context(VerifiedWorkspaceReader.open(output, allowed_artifacts={ARTIFACT}))
            if _encode(_object(delivery.read(ARTIFACT).payload)) != expected:
                raise PatternLibraryError("pattern library schema/evidence mismatch")
            delivery.verify_unchanged()
            digest = delivery.source_digest
        else:
            delivery = stack.enter_context(ImmutableWorkspace.reserve(output, allowed_artifacts={ARTIFACT}))
            with delivery.open_binary(ARTIFACT) as stream:
                stream.write(expected)
        for reader in readers:
            reader.verify_unchanged()
        return digest if verify else delivery.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", action="append", required=True, help="sealed analysis workspace; repeat for multiple")
    parser.add_argument("--output", required=True, help="new directory, or sealed library when verifying")
    parser.add_argument("--verify", action="store_true", help="replay and compare the whole contract")
    args = parser.parse_args(argv)
    try:
        print(run(args.analysis, args.output, verify=args.verify))
    except (PatternLibraryError, ComparisonError, PipelineError, WorkspaceError) as exc:
        parser.exit(2, f"pattern library rejected: {exc}\n")
    except (ValueError, TypeError, OverflowError, KeyError):
        parser.exit(2, "pattern library rejected: invalid source values\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
