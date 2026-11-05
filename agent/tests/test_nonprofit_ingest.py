"""Pipeline tests on small in-memory fixtures (the real source files are not in the repository)."""
import csv, json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import nonprofit_ingest as ni  # noqa: E402

ACC = {"A1", "A2"}
HEADERS = {
    "R1": {"survey_response_sk": "R1", "survey_sk": "S1", "account_sk": "A1", "response_id": "r_1"},
    "R2": {"survey_response_sk": "R2", "survey_sk": "S1", "account_sk": "A2", "response_id": "r_2"},
    "R3": {"survey_response_sk": "R3", "survey_sk": "S1", "account_sk": "ZZ", "response_id": "r_3"},
}
row = lambda **k: {"survey_response_sk": "R1", "survey_sk": "S1", "account_sk": "A1", "response_id": "r_1", **k}


def test_joins_and_conflicting_accounts_are_never_attached():
    assert ni.classify_answer(row(), HEADERS, ACC) == "consistent"
    assert ni.classify_answer(row(account_sk="A2"), HEADERS, ACC) == "account_conflict"          # header says A1, answer says A2: neither is preferred
    assert ni.classify_answer(row(survey_response_sk="R9"), HEADERS, ACC) == "no_header"
    assert ni.classify_answer(row(survey_sk="S2"), HEADERS, ACC) == "survey_conflict"
    assert ni.classify_answer(row(response_id="x"), HEADERS, ACC) == "response_id_conflict"
    assert ni.classify_answer(row(survey_response_sk="R3", account_sk="ZZ", response_id="r_3"), HEADERS, ACC) == "consistent_account_not_supplied"


def test_multiple_choice_aggregation_does_not_multiply_respondents():
    rows = [{"survey_response_sk": r, "question_label_txt": "q", "question_choice_txt": c} for r, c in
            [("R1", "Bank"), ("R1", "Bank"), ("R1", "Coop"), ("R2", "Bank"), ("R2", "Bank"), ("R2", "Bank")]]
    d = ni.multi_distribution(ni.aggregate_multi(rows))["q"]
    assert d["denominatorResponses"] == 2 and d["options"] == {"Bank": 2, "Coop": 1}               # option rows = 6, respondents = 2
    assert max(d["options"].values()) <= d["denominatorResponses"]


def test_country_aliases_keep_raw_and_conflicts_are_not_aliases():
    c = ni.normalize_country("Côte d’Ivoire"); assert c["raw"] == "Côte d’Ivoire" and c["normalized"] == "Côte d'Ivoire" and c["iso2"] == "CI" and c["status"] == "alias"
    assert ni.country_link_status("Côte d’Ivoire", "Cote d'Ivoire") == "alias"
    assert ni.country_link_status("Peru", "Peru") == "same"
    assert ni.country_link_status("Colombia", "Peru") == "conflict"
    assert ni.normalize_country("Atlantis")["status"] == "unmapped" and ni.country_link_status("Atlantis", "Peru") == "unreviewed"
    assert ni.normalize_country("Bolivia (Plurinational State of)")["normalized"] == "Bolivia"


def test_suspicious_dates_are_flagged_not_rewritten():
    assert ni.date_flags("1970-01-01", "2021-01-01") == ["start_epoch_placeholder"]
    assert "end_before_start" in ni.date_flags("2022-01-01", "2021-01-01")
    assert "end_after_2035" in ni.date_flags("2022-01-01", "2040-01-01")
    assert ni.date_flags("2021-02-03", "2022-03-04") == []
    assert ni.date_flags("", "") == []


def test_missing_zero_refused_and_dont_know_stay_distinct():
    for v, k in [("", "missing"), ("0", "zero_raw"), ("0.000000", "zero_raw"), ("Refused", "refused"), ("Don't know", "dont_know"), ("Don’t Know", "dont_know"),
                 ("I don't know", "dont_know"), ("None of the above applies", "not_applicable_label"), ("Yes", "value"), ("3651.48", "value")]:
        assert ni.classify_value(v) == k, v
    d = ni.single_distribution([{"c": ""}, {"c": "0"}, {"c": "Yes"}, {"c": "Yes"}, {"c": "No"}, {"c": "Refused"}, {"c": "Don't know"}], "c")
    assert d["responsesInScope"] == 7 and d["answered"] == 3 and d["options"] == {"Yes": 2, "No": 1}
    assert d["states"] == {"missing": 1, "zero_raw": 1, "value": 3, "refused": 1, "dont_know": 1}


def test_project_ids_are_stable_survive_description_edits_and_never_collide():
    base = {"account_sk": "A1", "project_name": "Shade trees", "project_start_date": "2022-01-01", "project_end_date": "2023-01-01", "project_description_txt": "v1"}
    t1, t2 = set(), set()
    a = ni.project_id(base, t1); b = ni.project_id({**base, "project_description_txt": "edited"}, t2)
    assert a == b and a.startswith("PRJ-")                                                             # description edits do not change the id
    assert ni.project_id({**base, "project_start_date": "2022-02-01"}, set()) != a                     # identity fields do
    assert ni.project_id(base, t1) == a + "-2"                                                         # identical rows are disambiguated by order


def _write(p: Path, rows, cols):
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(rows)


def test_end_to_end_on_fixture_is_idempotent_scoped_and_labels_origin(tmp_path):
    src = tmp_path / "src"; src.mkdir()
    A = ["account_sk", "account_category_name", "product_category_name", "account_type_name", "certification_scope_name", "certification_status_name", "country_name", "raw_supply_chain_role_txt", "structure_txt"]
    _write(src / ni.FILES["accounts"], [dict(zip(A, ["A1", "Coffee", "Coffee", "Supplier", "Producer", "Authorized", "Peru", "", ""])), dict(zip(A, ["A2", "Cocoa", "Cocoa", "Supplier", "Producer", "Authorized", "Cote d'Ivoire", "", ""]))], A)
    P = ["account_sk", "project_name", "project_description_txt", "country_name", "country_region_name", "category_taxonomy_term_txt", "sub_category_taxonomy_term_txt", "project_start_date", "project_end_date", "project_status_name"]
    _write(src / ni.FILES["projects"], [dict(zip(P, ["A1", "Nursery", "Trees", "Peru", "Cajamarca", "Environmental", "Reforestation", "2021-01-01", "2022-01-01", "Completed"])),
                                       dict(zip(P, ["A2", "Shade", "Shade trees", "Côte d’Ivoire", "Bas-Sassandra", "Environmental", "Agroforestry", "1970-01-01", "2022-01-01", "Completed"]))], P)
    S = ["survey_sk", "survey_name", "survey_id"]; _write(src / ni.FILES["survey_defs"], [dict(zip(S, ["S1", "Survey one", "SV_1"]))], S)
    H = ["survey_response_sk", "survey_sk", "account_sk", "survey_id", "response_id", "start_date", "end_date"]
    _write(src / ni.FILES["headers"], [dict(zip(H, ["R1", "S1", "A1", "SV_1", "r_1", "2021-05-01", "2021-05-01"])), dict(zip(H, ["R2", "S1", "A2", "SV_1", "r_2", "2024-05-01", "2024-05-01"]))], H)
    SC = ["survey_response_sk", "account_sk", "survey_sk", "survey_id", "response_id", "harvest_changed_code"]
    _write(src / ni.FILES["single"], [dict(zip(SC, ["R1", "A1", "S1", "SV_1", "r_1", "It has decreased"])), dict(zip(SC, ["R1", "A2", "S1", "SV_1", "r_1", "LEAK"]))], SC)
    MC = ["fssrrm_sk", "survey_response_sk", "account_sk", "survey_sk", "survey_id", "response_id", "extended_question_id", "question_label_txt", "question_choice_nbr", "question_choice_txt"]
    _write(src / ni.FILES["multi"], [dict(zip(MC, ["m1", "R1", "A1", "S1", "SV_1", "r_1", "q", "borrow", "0", "Bank"])), dict(zip(MC, ["m2", "R1", "A1", "S1", "SV_1", "r_1", "q", "borrow", "1", "Bank"]))], MC)
    out1, out2 = tmp_path / "o1", tmp_path / "o2"
    r1 = ni.run(src, out1, tmp_path / "b1"); r2 = ni.run(src, out2, tmp_path / "b2")
    assert r1["manifest"]["ingestionVersion"] == r2["manifest"]["ingestionVersion"]                                    # deterministic
    assert (out1 / "projects.json").read_text() == (out2 / "projects.json").read_text()
    e = r1["exceptions"]; assert e["single_choice"]["classification"] == {"consistent": 1, "account_conflict": 1}
    assert "LEAK" not in json.dumps(json.loads((out1 / "demo_accounts.json").read_text()))                              # conflicting rows never reach summaries
    projs = json.loads((out1 / "projects.json").read_text())["projects"]
    assert all(p["outcome"] == "not_reported" and p["origin"] == "public_source_data" and p["curationStatus"] == "not_curated" for p in projs)
    ci = next(p for p in projs if p["country"]["raw"] == "Côte d’Ivoire")
    assert ci["countryLink"] == "alias" and "start_epoch_placeholder" in ci["dateFlags"] and ci["usableAsRegionalPrecedent"] is False
    assert not any("standard" in k.lower() or "aps" in k.lower() for p in projs for k in p)                              # no standards clause is ever produced
    assert (tmp_path / "b1" / "quarantine" / "single_choice_quarantine.csv.gz").exists()                                # excluded rows are kept, not deleted


def test_cards_never_derive_outcomes_or_curation_and_skip_unusable_rows(tmp_path):
    base = {"projectId": "PRJ-AAA", "title": "Shade trees", "description": "Distributed shade trees", "country": ni.normalize_country("Côte d’Ivoire"), "region": "Bas-Sassandra", "products": ["Cocoa"],
            "startDate": "2022-01-01", "endDate": "2023-01-01", "dateFlags": [], "recordedStatus": "Completed", "category": "Environmental", "subCategory": "Agroforestry", "contentHash": "h",
            "sourceRef": {"accountSk": "ACC-INTERNAL", "row": 2}, "usableAsRegionalPrecedent": True}
    text, meta = ni.project_card(base, "v1")
    assert "Measured outcome: not reported" in text and "not FTUSA-curated" in text and "Recorded status: Completed" in text
    assert "ACC-INTERNAL" not in text and meta["metadataAttributes"]["sourceAccountSk"] == "ACC-INTERNAL"             # account reference is internal metadata only
    assert meta["metadataAttributes"]["curationStatus"] == "not_curated" and meta["metadataAttributes"]["countryIso2"] == "CI"
    assert not any(w in text.lower() for w in ("improved", "increased yield", "success", "resolved", "aps ", "fps "))
    n = ni.write_cards([base, {**base, "projectId": "PRJ-BBB", "usableAsRegionalPrecedent": False}], "v1", tmp_path)
    assert n == 1 and (tmp_path / "cards" / "PRJ-AAA.md").exists() and not (tmp_path / "cards" / "PRJ-BBB.md").exists()


def test_card_metadata_has_no_empty_values():
    p = {"projectId": "PRJ-E", "title": "t", "description": "d", "country": ni.normalize_country("Peru"), "region": "", "products": [], "startDate": "", "endDate": "", "dateFlags": [],
         "recordedStatus": "Completed", "category": "Environmental", "subCategory": "", "contentHash": "h", "sourceRef": {"accountSk": "A", "row": 2}, "usableAsRegionalPrecedent": True}
    _, meta = ni.project_card(p, "v1")
    assert all(v != "" for v in meta["metadataAttributes"].values()) and "region" not in meta["metadataAttributes"] and "subCategory" not in meta["metadataAttributes"]
