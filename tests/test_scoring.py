from app.scoring import score_project


def test_high_priority_arrival_window_scores_higher():
    project_soon = {"state": "Maharashtra", "status": "awarded", "civil_status": "advanced", "arrival_month": "2026-11"}
    project_far = {"state": "Maharashtra", "status": "awarded", "civil_status": "advanced", "arrival_month": "2027-06"}
    equipment = [{"equipment_type": "transformer", "capacity": "500 MVA", "quantity": "2",
                  "weight_value": "180 tonnes", "weight_confidence": "CONFIRMED"}]
    companies = [{"role": "OEM", "company_name": "BHEL"}]

    r_soon = score_project(project_soon, equipment, companies)
    r_far = score_project(project_far, equipment, companies)
    assert r_soon["total"] > r_far["total"]


def test_unknown_weight_scores_lower_than_confirmed():
    project = {"state": "Maharashtra", "status": "awarded", "civil_status": "advanced", "arrival_month": "2026-11"}
    eq_confirmed = [{"equipment_type": "transformer", "capacity": "500 MVA",
                      "weight_value": "180T", "weight_confidence": "CONFIRMED"}]
    eq_unknown = [{"equipment_type": "transformer", "capacity": "500 MVA",
                    "weight_value": None, "weight_confidence": "UNKNOWN"}]
    r1 = score_project(project, eq_confirmed, [])
    r2 = score_project(project, eq_unknown, [])
    assert r1["total"] > r2["total"]


def test_geographic_tier_affects_score():
    base = {"status": "awarded", "civil_status": "advanced", "arrival_month": "2026-11"}
    eq = [{"equipment_type": "transformer", "capacity": "500 MVA"}]
    r_mh = score_project({**base, "state": "Maharashtra"}, eq, [])
    r_other = score_project({**base, "state": "Bihar"}, eq, [])
    assert r_mh["total"] > r_other["total"]


def test_score_never_exceeds_100():
    project = {"state": "Maharashtra", "status": "awarded", "civil_status": "advanced complete", "arrival_month": "2026-11"}
    equipment = [{"equipment_type": "transformer", "capacity": "500 MVA", "quantity": "2",
                  "weight_value": "180 tonnes", "weight_confidence": "CONFIRMED"}]
    companies = [{"role": "OEM", "company_name": "BHEL"}, {"role": "EPC", "company_name": "L&T"}]
    r = score_project(project, equipment, companies)
    assert r["total"] <= 100


def test_breakdown_sums_to_total():
    project = {"state": "Gujarat", "status": "tender", "civil_status": "", "arrival_month": None}
    r = score_project(project, [], [])
    assert sum(b["points"] for b in r["breakdown"]) == r["total"]
