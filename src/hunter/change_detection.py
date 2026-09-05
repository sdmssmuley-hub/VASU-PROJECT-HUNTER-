"""
Section 28/29: only re-alert on an already-known project if something
material changed (not just because the same article was found again).
"""

MATERIAL_FIELDS = [
    "equipment_name", "actual_weight_tonnes", "oem", "epc", "quantity",
    "installation_contractor", "dispatch_date", "arrival_date",
    "installation_date", "civil_status", "project_status",
]

NOT_PUBLIC_MARKER = "not publicly disclosed"


def _norm(v):
    if v is None:
        return ""
    return str(v).strip().lower()


def detect_material_change(old_row: dict, new_record: dict):
    """
    Returns a list of change dicts: {field, previous, new} for fields
    where the new value is a real, non-empty, non-"not disclosed" value
    that differs from what was previously stored. Returns [] if nothing
    material changed.
    """
    changes = []
    for field in MATERIAL_FIELDS:
        old_val = old_row.get(field)
        new_val = new_record.get(field)
        new_norm = _norm(new_val)

        if not new_norm or NOT_PUBLIC_MARKER in new_norm:
            continue  # new info isn't more informative than before

        if _norm(old_val) == new_norm:
            continue  # unchanged

        changes.append({"field": field, "previous": old_val, "new": new_val})

    return changes
