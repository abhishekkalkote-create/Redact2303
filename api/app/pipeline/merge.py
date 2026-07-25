"""specs/05-redaction-pipeline.md Stage 5: Merge & manifest.

Dedup preference (deterministic vs LLM code): the LLM's citation is usually more specific
than the deterministic pass's federal-fallback default (e.g. 7(C) victim-identity vs a
generic b(6) personal-privacy default from Core PII) — see app/pipeline/detect.py's
STATE_PII_OVERRIDE_FOR comment on why b(6) is a broad fallback, not a precise fit. When
codes genuinely disagree
and neither is a clear fallback, this keeps the LLM's choice as primary but PRESERVES the
alternative in `detector_versions.alternative_exemption_code_id` rather than discarding it
silently — a proper "keep both, let the reviewer pick" UI (specs/05-redaction-pipeline.md:
"UI shows picker, medium confidence max") is not built yet; the data survives so that UI
can be added later without re-running detection.
"""

from dataclasses import dataclass, field


@dataclass
class MergeInput:
    key: str  # opaque identifier the caller can use to look the candidate back up
    page_no: int
    bbox: dict
    origin: str
    exemption_code_id: str | None
    confidence: str
    detector_versions: dict
    text: str | None = None  # decrypted text, only needed for recurrence grouping


@dataclass
class MergedGroup:
    kept_key: str  # which input's row should remain (others are dropped as duplicates)
    dropped_keys: list[str] = field(default_factory=list)
    bbox: dict | None = None  # union bbox, only set if it changed
    exemption_code_id: str | None = None
    confidence: str | None = None
    detector_versions_update: dict | None = None


_ORIGIN_PRIORITY = {"manual": 3, "llm": 2, "deterministic": 1, "search_apply": 0}
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1, "n/a-manual": 0}


def _iou(a: dict, b: dict) -> float:
    ax0, ay0, ax1, ay1 = a["x"], a["y"], a["x"] + a["w"], a["y"] + a["h"]
    bx0, by0, bx1, by1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    if ix1 <= ix0 or iy1 <= iy0:
        return 0.0
    intersection = (ix1 - ix0) * (iy1 - iy0)
    area_a = a["w"] * a["h"]
    area_b = b["w"] * b["h"]
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _union_bbox(a: dict, b: dict) -> dict:
    x0 = min(a["x"], b["x"])
    y0 = min(a["y"], b["y"])
    x1 = max(a["x"] + a["w"], b["x"] + b["w"])
    y1 = max(a["y"] + a["h"], b["y"] + b["h"])
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def merge_overlapping(candidates: list[MergeInput], iou_threshold: float = 0.5) -> list[MergedGroup]:
    """Groups same-page candidates whose boxes overlap above `iou_threshold`. O(n^2) per
    page — fine at page-level candidate counts (tens, not thousands)."""
    by_page: dict[int, list[MergeInput]] = {}
    for c in candidates:
        by_page.setdefault(c.page_no, []).append(c)

    groups: list[MergedGroup] = []
    for page_candidates in by_page.values():
        used: set[str] = set()
        for i, a in enumerate(page_candidates):
            if a.key in used:
                continue
            cluster = [a]
            used.add(a.key)
            for b in page_candidates[i + 1 :]:
                if b.key in used:
                    continue
                if _iou(a.bbox, b.bbox) > iou_threshold:
                    cluster.append(b)
                    used.add(b.key)

            if len(cluster) == 1:
                continue  # nothing to merge

            cluster.sort(key=lambda c: (_ORIGIN_PRIORITY.get(c.origin, 0), _CONFIDENCE_RANK.get(c.confidence, 0)), reverse=True)
            primary, *rest = cluster
            union_bbox = primary.bbox
            for other in rest:
                union_bbox = _union_bbox(union_bbox, other.bbox)

            alt_code = next((r.exemption_code_id for r in rest if r.exemption_code_id and r.exemption_code_id != primary.exemption_code_id), None)
            detector_update = dict(primary.detector_versions)
            detector_update["merged_from"] = [r.key for r in rest]
            if alt_code:
                detector_update["alternative_exemption_code_id"] = alt_code

            groups.append(
                MergedGroup(
                    kept_key=primary.key, dropped_keys=[r.key for r in rest], bbox=union_bbox,
                    exemption_code_id=primary.exemption_code_id, confidence=primary.confidence,
                    detector_versions_update=detector_update,
                )
            )
    return groups


def group_recurrence(candidates: list[MergeInput]) -> dict[str, str]:
    """Returns {candidate_key: recurrence_group_id} for candidates whose exact decrypted
    text appears more than once (across any page) — powers "apply to all similar"
    (specs/05-redaction-pipeline.md Stage 5). Candidates with no `.text` or unique text are
    omitted from the result."""
    from app.core.ids import new_id

    by_text: dict[str, list[str]] = {}
    for c in candidates:
        if not c.text:
            continue
        by_text.setdefault(c.text, []).append(c.key)

    result: dict[str, str] = {}
    for keys in by_text.values():
        if len(keys) < 2:
            continue
        group_id = new_id("rec")
        for key in keys:
            result[key] = group_id
    return result
