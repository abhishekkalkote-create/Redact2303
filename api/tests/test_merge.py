from app.pipeline.merge import MergeInput, group_recurrence, merge_overlapping


def _mk(key, page_no=1, bbox=None, origin="deterministic", code="code_a", confidence="high", text=None):
    return MergeInput(
        key=key, page_no=page_no, bbox=bbox or {"x": 0, "y": 0, "w": 10, "h": 10},
        origin=origin, exemption_code_id=code, confidence=confidence, detector_versions={}, text=text,
    )


def test_no_merge_for_non_overlapping_candidates() -> None:
    a = _mk("a", bbox={"x": 0, "y": 0, "w": 10, "h": 10})
    b = _mk("b", bbox={"x": 100, "y": 100, "w": 10, "h": 10})
    groups = merge_overlapping([a, b])
    assert groups == []


def test_merges_overlapping_candidates_and_unions_bbox() -> None:
    a = _mk("a", bbox={"x": 0, "y": 0, "w": 10, "h": 10}, origin="deterministic")
    b = _mk("b", bbox={"x": 2, "y": 2, "w": 10, "h": 10}, origin="deterministic")
    groups = merge_overlapping([a, b], iou_threshold=0.1)
    assert len(groups) == 1
    g = groups[0]
    assert g.dropped_keys == ["b"] or g.kept_key in ("a", "b")
    assert g.bbox["x"] == 0
    assert g.bbox["y"] == 0
    assert g.bbox["w"] == 12  # 0 to 12 (2+10)
    assert g.bbox["h"] == 12


def test_prefers_llm_origin_over_deterministic_when_merging() -> None:
    a = _mk("det", bbox={"x": 0, "y": 0, "w": 10, "h": 10}, origin="deterministic", code="b(6)")
    b = _mk("llm", bbox={"x": 1, "y": 1, "w": 10, "h": 10}, origin="llm", code="7(C)")
    groups = merge_overlapping([a, b], iou_threshold=0.1)
    assert len(groups) == 1
    assert groups[0].kept_key == "llm"
    assert groups[0].exemption_code_id == "7(C)"
    assert groups[0].detector_versions_update["alternative_exemption_code_id"] == "b(6)"


def test_different_pages_never_merge() -> None:
    a = _mk("a", page_no=1, bbox={"x": 0, "y": 0, "w": 10, "h": 10})
    b = _mk("b", page_no=2, bbox={"x": 0, "y": 0, "w": 10, "h": 10})
    groups = merge_overlapping([a, b])
    assert groups == []


def test_recurrence_grouping_matches_identical_text_across_pages() -> None:
    a = _mk("a", page_no=1, text="John Smith")
    b = _mk("b", page_no=3, text="John Smith")
    c = _mk("c", page_no=2, text="unique text")
    result = group_recurrence([a, b, c])
    assert result["a"] == result["b"]
    assert "c" not in result


def test_recurrence_grouping_ignores_candidates_without_text() -> None:
    a = _mk("a", text=None)
    result = group_recurrence([a])
    assert result == {}
