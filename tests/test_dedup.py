from app.dedup import build_fingerprint, similarity_flag


def test_same_tender_number_dedupes_regardless_of_name_spelling():
    fp1 = build_fingerprint("500 MVA Transformer Substation", "PowerGrid", "Pune", tender_number="PG/2026/117")
    fp2 = build_fingerprint("500MVA Transformer  Substation Project", "Power Grid Ltd", "Pune, MH", tender_number="PG-2026-117")
    # normalization strips non-alnum, so these should match
    assert fp1 == fp2


def test_different_tender_numbers_dont_dedupe():
    fp1 = build_fingerprint("Substation A", "Client", "Pune", tender_number="T-001")
    fp2 = build_fingerprint("Substation A", "Client", "Pune", tender_number="T-002")
    assert fp1 != fp2


def test_no_tender_number_falls_back_to_name_client_location():
    fp1 = build_fingerprint("Steel Plant Expansion", "Tata Steel", "Jamshedpur")
    fp2 = build_fingerprint("steel plant expansion", "tata steel", "jamshedpur")
    assert fp1 == fp2


def test_similarity_flag_catches_near_duplicate_names():
    a = {"name": "765kV Substation Nashik Extension", "location": "Nashik"}
    b = {"name": "765 kV Substation Nashik Extension Project", "location": "Nashik"}
    assert similarity_flag(a, b) is True


def test_similarity_flag_rejects_different_locations():
    a = {"name": "Transformer Project Alpha", "location": "Pune"}
    b = {"name": "Transformer Project Alpha", "location": "Surat"}
    assert similarity_flag(a, b) is False
