from app.agents.qc import qc_review


def _base_sources():
    return [{"title": "Real tender notice", "url": "https://powergrid.in/tender/1", "snippet": "..."}]


def test_demo_data_never_approved():
    verified = {"name": "Test Project", "status": "tender", "overall_confidence": 90,
                "_sources": [{"title": "[DEMO DATA] Sample", "url": "https://example.invalid"}]}
    decision, reason = qc_review(verified)
    assert decision == "HOLD"
    assert "DEMO DATA" in reason


def test_no_sources_rejected():
    verified = {"name": "Test Project", "status": "tender", "overall_confidence": 90, "_sources": []}
    decision, reason = qc_review(verified)
    assert decision == "REJECTED"


def test_unknown_name_rejected():
    verified = {"name": "UNKNOWN", "status": "tender", "overall_confidence": 90, "_sources": _base_sources()}
    decision, reason = qc_review(verified)
    assert decision == "REJECTED"


def test_commissioned_project_rejected_as_stale():
    verified = {"name": "Old Project", "status": "commissioned", "overall_confidence": 90, "_sources": _base_sources()}
    decision, reason = qc_review(verified)
    assert decision == "REJECTED"
    assert "status" in reason.lower()


def test_low_confidence_rejected():
    verified = {"name": "Weak Project", "status": "tender", "overall_confidence": 15, "_sources": _base_sources()}
    decision, reason = qc_review(verified)
    assert decision == "REJECTED"


def test_moderate_confidence_goes_to_hold():
    verified = {"name": "Medium Project", "status": "tender", "overall_confidence": 45, "_sources": _base_sources()}
    decision, reason = qc_review(verified)
    assert decision == "HOLD"


def test_high_confidence_approved():
    verified = {"name": "Strong Project", "status": "awarded", "overall_confidence": 80, "_sources": _base_sources()}
    decision, reason = qc_review(verified)
    assert decision == "APPROVED"


def test_parse_failure_rejected():
    verified = {"_parse_failed": True, "_sources": []}
    decision, reason = qc_review(verified)
    assert decision == "REJECTED"
