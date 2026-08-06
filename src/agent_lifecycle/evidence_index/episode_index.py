"""Lightweight episode indexes over receipt and session summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_lifecycle.context.rendering import estimate_tokens
from agent_lifecycle.contracts import LifecycleError, canonical_digest
from agent_lifecycle.evidence_index.core import build_evidence_index, validate_evidence_index

EPISODE_INDEX_SCHEMA = "agent-episode-index.v1"
EPISODE_INDEX_VALIDATION_SCHEMA = "agent-episode-index-validation.v1"
EPISODE_RETRIEVAL_SCHEMA = "agent-episode-retrieval.v1"


def build_episode_index(
    project_root: Path,
    artifact_paths: list[str],
    *,
    hash_chain: dict[str, Any] | None = None,
    max_artifacts: int = 64,
    max_input_bytes: int = 65536,
    target_tokens: int = 2048,
) -> dict[str, Any]:
    """Build a compact, rebuildable episode index from explicit artifacts."""

    evidence_index = build_evidence_index(
        project_root,
        artifact_paths,
        max_artifacts=max_artifacts,
        max_input_bytes=max_input_bytes,
        target_tokens=target_tokens,
    )
    evidence_validation = validate_evidence_index(evidence_index)
    chain_entries = _chain_entries(hash_chain)
    episodes = [
        _episode_from_entry(entry, chain_entries=chain_entries)
        for entry in evidence_index.get("entries", [])
        if isinstance(entry, dict)
    ]
    blockers: list[dict[str, Any]] = []
    if evidence_validation["status"] != "PASS":
        blockers.append({"code": "episode-source-index-invalid", "validation": evidence_validation})
    body = {
        "schemaVersion": EPISODE_INDEX_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "rebuildable": True,
        "enabledByDefault": False,
        "resourceCaps": {
            "maxArtifacts": max_artifacts,
            "maxInputBytes": max_input_bytes,
            "targetTokens": target_tokens,
        },
        "episodeCount": len(episodes),
        "episodes": episodes,
        "sourceIndexDigest": evidence_index.get("indexDigest"),
        "hashChainDigest": hash_chain.get("chainDigest") if isinstance(hash_chain, dict) else None,
        "blockers": blockers,
    }
    body["estimatedTokens"] = estimate_tokens(body)
    if body["estimatedTokens"] > target_tokens:
        body["blockers"].append(
            {
                "code": "episode-index-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"]:
        body["status"] = "FAIL"
    return {**body, "indexDigest": canonical_digest(body)}


def validate_episode_index(index: dict[str, Any]) -> dict[str, Any]:
    blockers: list[dict[str, Any]] = []
    if not isinstance(index, dict):
        raise LifecycleError("invalid-episode-index", "episode index must be an object")
    if index.get("schemaVersion") != EPISODE_INDEX_SCHEMA:
        blockers.append({"code": "episode-index-schema-invalid"})
    if index.get("sourceOfTruth") is not False:
        blockers.append({"code": "episode-index-source-of-truth"})
    if index.get("rebuildable") is not True:
        blockers.append({"code": "episode-index-not-rebuildable"})
    if index.get("enabledByDefault") is not False:
        blockers.append({"code": "episode-index-default-enabled"})
    episodes = index.get("episodes")
    if not isinstance(episodes, list):
        blockers.append({"code": "episode-index-episodes-invalid"})
        episodes = []
    for item_index, episode in enumerate(episodes):
        _validate_episode(episode, item_index, blockers)
    if index.get("episodeCount") != len(episodes):
        blockers.append({"code": "episode-index-count-mismatch"})
    expected_digest = canonical_digest({key: value for key, value in index.items() if key != "indexDigest"})
    if index.get("indexDigest") != expected_digest:
        blockers.append({"code": "episode-index-digest-mismatch"})
    body = {
        "schemaVersion": EPISODE_INDEX_VALIDATION_SCHEMA,
        "status": "PASS" if not blockers else "FAIL",
        "episodeCount": len(episodes),
        "blockers": blockers,
        "indexDigest": index.get("indexDigest"),
    }
    return {**body, "validationDigest": canonical_digest(body)}


def retrieve_episodes(
    index: dict[str, Any],
    *,
    query: str = "",
    max_results: int = 8,
    external_context_hints: list[dict[str, Any]] | None = None,
    max_external_context_hints: int = 4,
    target_tokens: int = 2048,
) -> dict[str, Any]:
    """Return bounded episode retrieval results with chain provenance."""

    _positive_int(max_results, "maxResults")
    _positive_int(max_external_context_hints, "maxExternalContextHints")
    _positive_int(target_tokens, "targetTokens")
    validation = validate_episode_index(index)
    episodes = index.get("episodes") if isinstance(index.get("episodes"), list) else []
    ranked = _rank_episodes([item for item in episodes if isinstance(item, dict)], query)
    results = [_retrieval_projection(item) for item in ranked[:max_results]]
    external_hints = _project_external_context_hints(
        external_context_hints or [],
        query=query,
        max_hints=max_external_context_hints,
    )
    body = {
        "schemaVersion": EPISODE_RETRIEVAL_SCHEMA,
        "status": "PASS",
        "sourceOfTruth": False,
        "query": query,
        "resultCount": len(results),
        "maxResults": max_results,
        "results": results,
        "omittedResultCount": max(0, len(ranked) - len(results)),
        "externalContextPolicy": {
            "sourceOfTruth": False,
            "proof": False,
            "enabledByDefault": False,
            "role": "optional-context-hint",
        },
        "externalContextHintCount": len(external_hints),
        "externalContextHints": external_hints,
        "indexDigest": index.get("indexDigest"),
        "blockers": [] if validation["status"] == "PASS" else [{"code": "episode-index-invalid"}],
        "chainStateCounts": _chain_state_counts(results),
    }
    body["estimatedTokens"] = estimate_tokens(body)
    body["targetTokens"] = target_tokens
    if body["estimatedTokens"] > target_tokens:
        body["blockers"].append(
            {
                "code": "episode-retrieval-target-tokens-exceeded",
                "estimatedTokens": body["estimatedTokens"],
                "targetTokens": target_tokens,
            }
        )
    if body["blockers"]:
        body["status"] = "FAIL"
    return {**body, "retrievalDigest": canonical_digest(body)}


def require_episode_index_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("episode-index-failed", "episode index validation failed", {"index": payload})
    return payload


def require_episode_retrieval_pass(payload: dict[str, Any]) -> dict[str, Any]:
    if payload.get("status") != "PASS":
        raise LifecycleError("episode-retrieval-failed", "episode retrieval failed", {"retrieval": payload})
    return payload


def _episode_from_entry(entry: dict[str, Any], *, chain_entries: dict[tuple[str, str], str]) -> dict[str, Any]:
    path = str(entry.get("sourcePath"))
    digest = str(entry.get("artifactDigest"))
    chain_entry_hash = chain_entries.get((path, digest))
    chain_state = "chainVerified" if chain_entry_hash else "chainUnchecked"
    summary = entry.get("summary") if isinstance(entry.get("summary"), dict) else {}
    return {
        "episodeId": f"episode-{canonical_digest({'path': path, 'digest': digest})[:16]}",
        "sourcePath": path,
        "artifactDigest": digest,
        "artifactType": entry.get("artifactType"),
        "status": summary.get("status"),
        "summary": _compact_summary(summary),
        "provenance": {
            "sourceIndexEntryDigest": canonical_digest(entry),
            "chainState": chain_state,
            "chainUnchecked": chain_state != "chainVerified",
            "chainEntryHash": chain_entry_hash,
        },
    }


def _chain_entries(hash_chain: dict[str, Any] | None) -> dict[tuple[str, str], str]:
    if not isinstance(hash_chain, dict):
        return {}
    entries = hash_chain.get("entries")
    if not isinstance(entries, list):
        return {}
    result: dict[tuple[str, str], str] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        artifact = entry.get("artifact")
        if not isinstance(artifact, dict):
            continue
        path = artifact.get("path")
        digest = artifact.get("digest")
        entry_hash = entry.get("entryHash")
        if isinstance(path, str) and isinstance(digest, str) and isinstance(entry_hash, str):
            result[(path, digest)] = entry_hash
    return result


def _validate_episode(episode: Any, index: int, blockers: list[dict[str, Any]]) -> None:
    if not isinstance(episode, dict):
        blockers.append({"code": "episode-entry-invalid", "index": index})
        return
    for key in ("episodeId", "sourcePath", "artifactDigest", "artifactType", "provenance"):
        if key not in episode:
            blockers.append({"code": "episode-field-missing", "index": index, "field": key})
    provenance = episode.get("provenance")
    if not isinstance(provenance, dict):
        blockers.append({"code": "episode-provenance-invalid", "index": index})
        return
    if provenance.get("chainState") not in {"chainVerified", "chainUnchecked"}:
        blockers.append({"code": "episode-chain-state-invalid", "index": index})
    if provenance.get("chainState") == "chainVerified" and provenance.get("chainUnchecked") is not False:
        blockers.append({"code": "episode-chain-verified-unchecked-mismatch", "index": index})
    if provenance.get("chainState") == "chainUnchecked" and provenance.get("chainUnchecked") is not True:
        blockers.append({"code": "episode-chain-unchecked-mismatch", "index": index})


def _rank_episodes(episodes: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return sorted(episodes, key=lambda item: str(item.get("sourcePath")))
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for episode in episodes:
        haystack = json.dumps(_retrieval_projection(episode), ensure_ascii=False, sort_keys=True).lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((score, str(episode.get("sourcePath")), episode))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [episode for _, _, episode in ranked]


def _retrieval_projection(episode: dict[str, Any]) -> dict[str, Any]:
    provenance = episode.get("provenance") if isinstance(episode.get("provenance"), dict) else {}
    return {
        "episodeId": episode.get("episodeId"),
        "sourcePath": episode.get("sourcePath"),
        "artifactType": episode.get("artifactType"),
        "status": episode.get("status"),
        "summary": episode.get("summary"),
        "chainState": provenance.get("chainState"),
        "chainUnchecked": provenance.get("chainUnchecked"),
        "chainEntryHash": provenance.get("chainEntryHash"),
    }


def _project_external_context_hints(
    hints: list[dict[str, Any]],
    *,
    query: str,
    max_hints: int,
) -> list[dict[str, Any]]:
    ranked = _rank_external_context_hints([item for item in hints if isinstance(item, dict)], query)
    projected: list[dict[str, Any]] = []
    for hint in ranked[:max_hints]:
        projected.append(
            {
                "hintId": hint.get("hintId"),
                "contextRole": "optional-external-context",
                "sourceOfTruth": False,
                "proof": False,
                "citation": hint.get("citation"),
                "sourceDigest": hint.get("sourceDigest"),
                "redactionStatus": hint.get("redactionStatus"),
                "text": hint.get("text"),
            }
        )
    return projected


def _rank_external_context_hints(hints: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    terms = [term for term in query.lower().split() if term]
    if not terms:
        return sorted(hints, key=lambda item: str(item.get("hintId") or item.get("citation")))
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for hint in hints:
        haystack = json.dumps(hint, ensure_ascii=False, sort_keys=True).lower()
        score = sum(1 for term in terms if term in haystack)
        if score:
            ranked.append((score, str(hint.get("hintId") or hint.get("citation")), hint))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [hint for _, _, hint in ranked]


def _compact_summary(summary: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in summary.items()
        if key in {"schemaVersion", "status", "packageId", "runId", "taskId", "operationId", "adapterId", "host", "topLevelKeys"}
    }


def _chain_state_counts(results: list[dict[str, Any]]) -> dict[str, int]:
    counts = {"chainVerified": 0, "chainUnchecked": 0}
    for item in results:
        state = item.get("chainState")
        if state in counts:
            counts[state] += 1
    return counts


def _positive_int(value: int, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise LifecycleError("invalid-episode-retrieval", f"{label} must be a positive integer")
    return value
