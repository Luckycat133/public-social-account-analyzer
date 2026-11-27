"""Build and validate same-platform comparisons using only sealed collections."""
from __future__ import annotations

import argparse
import json
import re
import sys
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from analysis.normalize import normalize_in_memory
from collectors.adapter_registry import ADAPTER_SPECS
from collectors.url_policy import canonical_profile_url
from immutable_workspace import (
    ImmutableWorkspace, VerifiedWorkspaceReader, WorkspaceError,
    preflight_workspace_target, reject_workspace_overlap,
)
from run_pipeline import COLLECTION_ARTIFACTS
from task_contract import ANALYZABLE_TASK_STATUSES

ARTIFACT = "comparison.json"
METRICS = ("likes", "comments", "shares")
PLATFORMS = frozenset(spec.platform for spec in ADAPTER_SPECS)
ISO = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})$")
PUBLIC_ID = re.compile(r"^[A-Za-z0-9_.-]{1,256}$")
MAX_COLLECTIONS = 16


class ComparisonError(ValueError):
    """The comparison cannot be supported by these inputs."""


def _object(payload: bytes) -> dict:
    def unique_keys(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ComparisonError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_):
        raise ComparisonError("non-finite JSON constant")

    try:
        value = json.loads(payload.decode("utf-8"), object_pairs_hook=unique_keys,
                           parse_constant=reject_constant)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ComparisonError("invalid JSON object") from exc
    if not isinstance(value, dict):
        raise ComparisonError("invalid JSON object")
    return value


def _utc(value: str) -> datetime:
    try:
        if not isinstance(value, str) or not ISO.fullmatch(value):
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ComparisonError("expected an ISO datetime with an explicit timezone") from exc


def _published(row: dict) -> datetime | None:
    # The source must supply a year (no wall clock/year-inferred dates), and
    # date-only observations cannot be assigned to an exact UTC interval.
    value = row.get("published_at")
    precision = row.get("platform_metrics")
    if isinstance(precision, dict) and precision.get("published_at_precision") in ("unknown", "date"):
        return None
    if not isinstance(value, str) or len(value) < 16:
        return None
    try:
        return _utc(value)
    except ComparisonError:
        return None


def _number(row: dict, metric: str) -> int | None:
    value = row.get(metric)
    if row["_visibility"].get(metric) == "visible" and type(value) is int and value >= 0:
        return value
    return None


def _read(reader: VerifiedWorkspaceReader) -> dict:
    profile = _object(reader.read("source/profile.json").payload)
    task = _object(reader.read("task.json").payload)
    profile_platform = profile.get("platform")
    if not isinstance(profile_platform, str) or profile_platform not in PLATFORMS or task.get("platform") != profile_platform:
        raise ComparisonError("collection platform identity mismatch")
    identity = profile.get("account_id")
    url = canonical_profile_url(profile_platform, profile.get("profile_url"))
    status = task.get("task_status")
    task_id = task.get("task_id")
    if (not isinstance(task_id, str) or not task_id.strip()
            or not isinstance(identity, str) or not PUBLIC_ID.fullmatch(identity)
            or url is None or url != canonical_profile_url(profile_platform, task.get("profile_url"))
            or not isinstance(status, str) or status not in ANALYZABLE_TASK_STATUSES):
        raise ComparisonError("verified account identity or analyzable collection is missing")
    start_capture = _utc(task.get("collected_at"))
    end_capture = _utc(task["ended_at"]) if task.get("ended_at") is not None else start_capture
    if end_capture < start_capture:
        raise ComparisonError("collection timing is out of order")
    raw = [_object(line) for line in reader.read("source/posts.jsonl").payload.splitlines() if line.strip()]
    count = task.get("collected_count")
    if type(count) is not int or count != len(raw):
        raise ComparisonError("collection count does not match the sealed posts")
    known = {}
    observation_times = {}
    candidates = []
    unknown_identity = 0
    for row in raw:
        if row.get("platform") != profile_platform:
            raise ComparisonError("post does not match collection platform")
        key = row.get("post_id")
        if not isinstance(key, str) or not key.strip():
            raise ComparisonError("sealed post ID is invalid")
        if key in known:
            raise ComparisonError("duplicate post in sealed collection")
        known[key] = _published(row)
        observation_times[key] = _observed(row)
        extra = row.get("platform_metrics")
        if isinstance(extra, dict) and (extra.get("platform_post_id_known") is False or extra.get("local_record_key") is True):
            unknown_identity += 1
        else:
            if not PUBLIC_ID.fullmatch(key):
                raise ComparisonError("known platform post ID is invalid")
            candidates.append(row)
    posts = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in candidates)
    try:
        normalized = normalize_in_memory(profile, posts)
    except (ValueError, OverflowError, TypeError) as exc:
        raise ComparisonError("sealed posts cannot be normalized") from exc
    valid = [row for row in normalized.rows if row["collection_status"] in {"SUCCESS", "PARTIAL"}]
    eligible = {
        row["post_id"]: (known[row["post_id"]], row)
        for row in valid
        if not any(row.get(flag) is True for flag in ("is_pinned", "is_repost", "is_promoted"))
    }
    if any(stamp is not None and stamp > end_capture for stamp, _ in eligible.values()):
        raise ComparisonError("post publication is later than the collection snapshot")
    coverage = {
        "task_status": status,
        "requested_limit": task.get("requested_limit") if type(task.get("requested_limit")) is int and task["requested_limit"] > 0 else None,
        "sealed_posts": len(raw),
        "unknown_identity_posts": unknown_identity,
        "excluded_post_type": len(valid) - len(eligible),
        "unavailable_posts": len(candidates) - len(valid),
        "unknown_publication_time": sum(stamp is None for stamp, _ in eligible.values()),
    }
    return {"platform": profile_platform, "account_id": identity, "profile_url": url, "capture": start_capture, "capture_end": end_capture,
            "commit_sha256": reader.source_digest, "coverage": coverage, "eligible": eligible, "observation_times": observation_times}


def _slice(source: dict, start: datetime, end: datetime) -> dict:
    if end > source["capture"]:
        raise ComparisonError("the period ends after a collection snapshot")
    return {pid: row for pid, (stamp, row) in source["eligible"].items()
            if stamp is not None and start <= stamp < end}


def _summarize(source: dict, sample: dict) -> dict:
    values = {}
    for metric in METRICS:
        known = [value for row in sample.values() if (value := _number(row, metric)) is not None]
        exact = bool(known) and len(known) == len(sample)
        values[metric] = {"denominator": len(sample), "observed": len(known),
                          "total": sum(known) if exact else None}
    return {
        "account_id": source["account_id"], "collection_commit_sha256": source["commit_sha256"],
        "snapshot_at": source["capture"].isoformat(), "coverage": source["coverage"],
        "sample_post_count": len(sample), "metrics": values,
    }


def _observed(row: dict) -> datetime | None:
    try:
        return _utc(row.get("collected_at"))
    except ComparisonError:
        return None


def _window(start: datetime, end: datetime) -> dict:
    return {"start_inclusive": start.isoformat(), "end_exclusive": end.isoformat()}


def _build(readers, mode: str, boundaries: list[str]) -> dict:
    expected = {"accounts": 2, "periods": 3}
    if mode not in expected or len(boundaries) != expected[mode]:
        raise ComparisonError("accounts requires 2 boundaries; periods requires 3 adjacent boundaries")
    if not 2 <= len(readers) <= MAX_COLLECTIONS or (mode == "periods" and len(readers) != 2):
        raise ComparisonError("accounts requires 2–16 collections; periods requires exactly 2")
    points = [_utc(value) for value in boundaries]
    if any(first >= second for first, second in zip(points, points[1:])):
        raise ComparisonError("window boundaries must increase")
    sources = [_read(reader) for reader in readers]
    platform = sources[0]["platform"]
    if any(source["platform"] != platform for source in sources):
        raise ComparisonError("cross-platform comparisons are not supported")
    result = {"schema_version": 1, "mode": mode, "platform": platform,
              "scope": "observed_public_sample_only"}
    if mode == "accounts":
        start, end = points
        if len({source["account_id"] for source in sources}) != len(sources) or len({source["profile_url"] for source in sources}) != len(sources):
            raise ComparisonError("accounts must be distinct")
        seen = set()
        for source in sources:
            if seen.intersection(source["eligible"]):
                raise ComparisonError("a platform post ID is attributed to multiple accounts")
            seen.update(source["eligible"])
        sources.sort(key=lambda source: source["account_id"])
        first_capture = min(source["capture"] for source in sources)
        last_capture = max(source["capture"] for source in sources)
        result.update(window=_window(start, end),
                      snapshot_span={"earliest": first_capture.isoformat(), "latest": last_capture.isoformat()},
                      accounts=[
            _summarize(source, _slice(source, start, end)) for source in sources
        ])
    else:
        start, middle, end = points
        if middle - start != end - middle:
            raise ComparisonError("periods must be adjacent and equal in duration")
        previous, current = sources
        if (previous["account_id"] != current["account_id"] or previous["profile_url"] != current["profile_url"]
                or previous["capture"] >= current["capture"]):
            raise ComparisonError("periods require the same account in snapshot order")
        old, new = _slice(previous, start, middle), _slice(current, middle, end)
        overlap = previous["eligible"].keys() & current["eligible"].keys()
        changes = []
        for pid in sorted(overlap):
            old_time, old_row = previous["eligible"][pid]
            new_time, new_row = current["eligible"][pid]
            if old_time is not None and new_time is not None and old_time != new_time:
                raise ComparisonError("shared post publication differs between snapshots")
            previous_observed = previous["observation_times"][pid]
            current_observed = current["observation_times"][pid]
            # Incremental collections may carry the same observation forward.
            # A later seal does not in itself prove a fresh post observation.
            distinct = (
                previous_observed is not None and current_observed is not None
                and previous_observed < current_observed
                and previous_observed <= previous["capture_end"]
                and current_observed <= current["capture_end"]
                and (old_time is None or old_time <= previous_observed)
                and (new_time is None or new_time <= current_observed)
            )
            delta = {}
            for metric in METRICS:
                before, after = _number(old_row, metric), _number(new_row, metric)
                delta[metric] = after - before if distinct and before is not None and after is not None else None
            changes.append({"post_id": pid,
                            "previous_observed_at": previous_observed.isoformat() if previous_observed else None,
                            "current_observed_at": current_observed.isoformat() if current_observed else None,
                            "metric_deltas": delta})
        prior = _summarize(previous, old)
        latest = _summarize(current, new)
        result.update(previous={"window": _window(start, middle), **prior},
                      current={"window": _window(middle, end), **latest},
                      sample_total_deltas={
                          key: latest["metrics"][key]["total"] - prior["metrics"][key]["total"]
                          if latest["metrics"][key]["total"] is not None and prior["metrics"][key]["total"] is not None
                          else None for key in METRICS
                      },
                      sample_count_delta=len(new)-len(old),
                      shared_post_metric_changes=changes)
    return result


def _encode(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def run(mode: str, boundaries: list[str], collections: list[str], output: str, *, verify: bool = False) -> str:
    """Emit an immutable structured delivery, or recompute its exact schema from evidence."""
    if len(collections) > MAX_COLLECTIONS:
        raise ComparisonError("too many input collections")
    if not verify:
        output = preflight_workspace_target(output)
    for path in collections:
        reject_workspace_overlap(path, output)
    with ExitStack() as stack:
        readers = [stack.enter_context(VerifiedWorkspaceReader.open(path, allowed_artifacts=COLLECTION_ARTIFACTS))
                   for path in collections]
        expected = _encode(_build(readers, mode, boundaries))
        if verify:
            delivery = stack.enter_context(VerifiedWorkspaceReader.open(output, allowed_artifacts={ARTIFACT}))
            actual = _object(delivery.read(ARTIFACT).payload)
            if _encode(actual) != expected:
                raise ComparisonError("comparison schema/evidence mismatch")
            delivery.verify_unchanged()
            result = delivery.source_digest
        else:
            delivery = stack.enter_context(ImmutableWorkspace.reserve(output, allowed_artifacts={ARTIFACT}))
            with delivery.open_binary(ARTIFACT) as stream:
                stream.write(expected)
        for reader in readers:
            reader.verify_unchanged()
        return result if verify else delivery.commit()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("accounts", "periods"))
    parser.add_argument("--boundary", action="append", required=True, help="ascending window boundaries with explicit timezone")
    parser.add_argument("--collection", action="append", required=True, help="sealed collection directory; older first in periods mode")
    parser.add_argument("--output", required=True, help="new output directory or sealed delivery in --verify mode")
    parser.add_argument("--verify", action="store_true", help="validate the delivery exactly against all original sealed collections")
    args = parser.parse_args(argv)
    try:
        print(run(args.mode, args.boundary, args.collection, args.output, verify=args.verify))
    except (ComparisonError, WorkspaceError) as exc:
        parser.exit(2, f"comparison rejected: {exc}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
