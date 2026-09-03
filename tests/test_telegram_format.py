from app.telegram_bot import format_project_card, format_daily_report, format_run_report


def test_project_card_uses_unknown_for_missing_fields():
    card = {"name": "Test Project", "score": 75, "confidence": 80}
    text = format_project_card(card)
    assert "Test Project" in text
    assert "UNKNOWN" in text  # client/location/etc missing -> UNKNOWN, never blank/fabricated


def test_daily_report_handles_no_opportunities():
    summary = {"runs": 10, "candidates": 30, "duplicates": 5, "rejected": 20, "verified": 5,
               "high_priority": 1, "top_opportunities": []}
    text = format_daily_report(summary)
    assert "None" in text


def test_run_report_includes_all_counts():
    run = {"run_label": "10:00 Test", "candidates": 10, "duplicates": 2, "rejected": 5, "verified": 3, "high_priority": 1}
    text = format_run_report(run)
    for val in ["10", "2", "5", "3", "1"]:
        assert val in text
