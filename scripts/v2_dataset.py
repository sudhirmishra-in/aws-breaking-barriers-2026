#!/usr/bin/env python3
"""Deterministic generator for the V2 SYNTHETIC demonstration dataset (data/v2-synthetic/*.json). Every record is fictional.

Not FTUSA data. APS/FPS clauses are NOT invented here: `standards` stay empty and `standards_status` says the supplied clauses are required.
Run: python scripts/v2_dataset.py   (rewrites the JSON files; the files are committed so seeding does not need this step)
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "data" / "v2-synthetic"
NOTE = "SYNTHETIC DEMONSTRATION DATA. Fictional organizations, people, conversations and outcomes. Not FTUSA data."

def info(sk, cat, products, typ, scope, status, country, roles, structure):
    return {"accountSk": sk, "accountCategoryName": cat, "productCategoryName": products, "accountTypeName": typ, "certificationScopeName": scope,
            "certificationStatusName": status, "countryName": country, "rawSupplyChainRoleTxt": roles, "structureTxt": structure}

ORGS = [
    {"organizationId": "ORG-AND-COL", "name": "Andean Coffee Cooperative", "info": info("ACC-COL-0000412873", "Producer organization (cooperative)", ["Coffee (green, washed arabica)", "Specialty micro-lots"], "Small producer organization (SPO)", "Coffee production and cooperative wet milling", "Certified", "Colombia", ["Grower (member farms)", "Primary processor (wet mill)", "Exporter"], "Cooperative of 640 member farms in 14 veredas, general assembly and elected board")},
    {"organizationId": "ORG-COP-HON", "name": "Copán Coffee Association", "info": info("ACC-HND-0000377120", "Producer association", ["Coffee (green, washed arabica)"], "Small producer organization (SPO)", "Coffee production", "Certified", "Honduras", ["Grower (member farms)", "Dry mill operator"], "Association of 210 smallholder members in 9 communities")},
    {"organizationId": "ORG-NAW-CIV", "name": "Nawa Cocoa Cooperative", "info": info("ACC-CIV-0000559004", "Producer organization (cooperative)", ["Cocoa (fermented, dried beans)", "Plantain (intercrop)"], "Small producer organization (SPO)", "Cocoa production, fermentation and bulk aggregation", "Certification suspended pending audit follow-up", "Côte d'Ivoire", ["Grower (member farms)", "Aggregator", "Fermentation and drying"], "Cooperative of 1,150 members in 22 village sections, supervised by a management committee")},
]
PRODUCERS = [  # name, org, language, handle
    ("PRD-ANA", "Ana", "ORG-AND-COL", "es"), ("PRD-MATEO", "Mateo", "ORG-AND-COL", "es"), ("PRD-ELENA", "Elena", "ORG-AND-COL", "en"),
    ("PRD-LUCIA", "Lucía", "ORG-COP-HON", "es"), ("PRD-DIEGO", "Diego", "ORG-COP-HON", "en"), ("PRD-ROSA", "Rosa", "ORG-COP-HON", "es"),
    ("PRD-AWA", "Awa", "ORG-NAW-CIV", "fr"), ("PRD-KOFFI", "Koffi", "ORG-NAW-CIV", "fr"), ("PRD-MARIAM", "Mariam", "ORG-NAW-CIV", "en"),
]
HANDLE = {"Ana": "ana", "Mateo": "mateo", "Elena": "elena", "Lucía": "lucia", "Diego": "diego", "Rosa": "rosa", "Awa": "awa", "Koffi": "koffi", "Mariam": "mariam"}
ORG_OF = {p[0]: p[2] for p in PRODUCERS}
NAME_OF = {p[0]: p[1] for p in PRODUCERS}
LANG_OF = {p[0]: p[3] for p in PRODUCERS}

producers = [{"producerId": p, "displayName": n, "organizationId": o, "applicationUserId": f"user-{HANDLE[n]}", "preferredLanguage": l, "entityType": "smallholder",
              "seedUsername": f"{HANDLE[n]}.demo@example.com", "location": {"ORG-AND-COL": "Huila, Colombia", "ORG-COP-HON": "Copán, Honduras", "ORG-NAW-CIV": "Nawa, Côte d'Ivoire"}[o],
              "crop": "cocoa" if o == "ORG-NAW-CIV" else "coffee", "synthetic": True} for p, n, o, l in PRODUCERS]
reviewers = [{"reviewerId": "REV-1", "displayName": "Reviewer One", "seedUsername": "reviewer1.demo@example.com"}, {"reviewerId": "REV-2", "displayName": "Reviewer Two", "seedUsername": "reviewer2.demo@example.com"}]

# Topic text: (challenge in each language, English summary). Fictional.
T = {
 "drought": {"es": "Hubo sequía este año y las plantas de café perdieron flores.", "en": "There was a drought this year and the coffee plants lost flowers.", "fr": "Il y a eu une sécheresse cette année.", "tag": "climate_weather", "sum_en": "A dry spell reduced flowering and expected yield this season."},
 "water": {"es": "Construimos tanques para guardar agua de lluvia.", "en": "We built tanks to store rainwater.", "fr": "Nous avons construit des citernes.", "tag": "water", "sum_en": "Rainwater storage tanks were built to bridge the dry season."},
 "price": {"es": "El precio bajó y no cubre mis costos.", "en": "The price fell and does not cover my costs.", "fr": "Le prix a baissé.", "tag": "market_price", "sum_en": "A sharp price decline no longer covers production costs."},
 "labor": {"es": "Faltan trabajadores para la cosecha.", "en": "There are not enough workers for the harvest.", "fr": "Il manque de main-d'œuvre pour la récolte.", "tag": "labor_migration", "sum_en": "A shortage of harvest labor delayed picking."},
 "soil": {"es": "El suelo se ve más pobre cada año.", "en": "My soil looks poorer every year.", "fr": "Le sol est plus pauvre chaque année.", "tag": "soil_land", "sum_en": "Soil fertility appears to be declining year over year."},
}
def tr(topic, lang, extra=""):
    t = T[topic]; first = t[lang]
    q = {"es": "¿Qué ha sido difícil últimamente?", "en": "What has been difficult recently?", "fr": "Qu'est-ce qui a été difficile ces derniers temps ?"}[lang]
    fol = {"es": "¿Cuándo empezó y qué intentó?", "en": "When did it start and what have you tried?", "fr": "Quand cela a-t-il commencé et qu'avez-vous essayé ?"}[lang]
    conf = {"es": "Sí, es correcto.", "en": "Yes, that's right.", "fr": "Oui, c'est exact."}[lang]
    return [("assistant", q), ("user", first + (" " + extra if extra else "")), ("assistant", fol), ("user", {"es": "Empezó hace dos meses; todavía no he hecho nada.", "en": "It started two months ago; I have not tried anything yet.", "fr": "Cela a commencé il y a deux mois ; je n'ai encore rien essayé."}[lang]), ("assistant", t["sum_en"]), ("user", conf)]

CONVS = []
def conv(cid, prod, topic, days, status="completed", sharing="share_summary", review="approved", pub="published", identity=False, issue=None, kind="issue", extra="", result=None, action=None, lang=None, reconfirm=False, correction_turn=False, pii=False, version=1):
    lang = lang or LANG_OF[prod]
    c = {"conversationId": cid, "producerId": prod, "organizationId": ORG_OF[prod], "language": lang, "daysAgo": days, "status": status, "kind": kind, "topic": topic,
         "title": T[topic]["sum_en"][:60], "messages": [{"role": r, "text": x} for r, x in tr(topic, lang, extra)], "issueId": issue, "piiFlag": pii}
    if correction_turn: c["messages"] += [{"role": "user", "text": {"es": "Corrección: la sequía fue en la finca de arriba, no en la de abajo.", "en": "Correction: the drought was at the upper farm, not the lower one.", "fr": "Correction."}[lang]}]; c["playbackCorrected"] = True
    if status == "completed" and kind == "issue":
        c.update({"summaryOriginal": T[topic][lang], "summaryEn": T[topic]["sum_en"], "tags": [T[topic]["tag"]], "sharingChoice": sharing, "identityPermitted": identity,
                  "reviewStatus": review, "publicationStatus": pub if sharing != "ftusa_only" else ("not_shared"), "summaryVersion": version,
                  "caseCard": {"action": action, "result": result, "standards": [], "standards_status": "supplied APS/FPS clauses required; none invented"}})
        if reconfirm: c["publicationStatus"] = "awaiting_reconfirmation"; c["pendingRevision"] = {"summaryEn": T[topic]["sum_en"] + " (reviewer edit)"}
    return c

# 24 conversations covering the required scenarios.
CONVS += [
 conv("cv-01", "PRD-ANA", "drought", 0, status="active", issue="ISS-01", correction_turn=True),
 conv("cv-02", "PRD-ANA", "drought", 30, sharing="share_summary", issue="ISS-01", action="Planned to build water storage tanks", result=None),
 conv("cv-03", "PRD-ANA", "water", 90, sharing="share_conversation", identity=True, issue="ISS-02", action="Installed two rainwater tanks", result="Fewer lost harvest days reported by Ana (fictional)"),
 conv("cv-04", "PRD-MATEO", "water", 12, sharing="share_conversation", identity=True, issue="ISS-03", action="Shared irrigation schedule across three farms", result="Water use steadier through the dry weeks (fictional)"),
 conv("cv-05", "PRD-MATEO", "drought", 5, sharing="share_summary", issue="ISS-01", action="Mulching trial", result=None),
 conv("cv-06", "PRD-ELENA", "drought", 2, kind="search", status="completed"),
 conv("cv-07", "PRD-ELENA", "soil", 40, sharing="share_summary", review="pending", pub="awaiting_review", issue="ISS-04"),
 conv("cv-08", "PRD-LUCIA", "drought", 8, sharing="share_summary", issue="ISS-05", action="Moved pruning earlier", result="Too early to tell (fictional)"),
 conv("cv-09", "PRD-LUCIA", "drought", 70, sharing="share_summary", issue="ISS-05", action="Planted shade trees", result="Recurrence in the next season (fictional)"),
 conv("cv-10", "PRD-DIEGO", "price", 3, sharing="share_conversation", identity=False, issue="ISS-06", action="Sold part of the harvest through the Premium-funded drying program", result="Price risk reduced but income lower (fictional)", lang="en"),
 conv("cv-11", "PRD-DIEGO", "price", 25, status="stopped", issue="ISS-06"),
 conv("cv-12", "PRD-ROSA", "labor", 6, sharing="ftusa_only", review="pending", pub="not_shared", issue="ISS-07"),
 conv("cv-13", "PRD-ROSA", "price", 60, sharing="ftusa_only", review="approved", pub="not_shared", issue="ISS-08"),
 conv("cv-14", "PRD-AWA", "labor", 4, sharing="share_summary", issue="ISS-09", action="Organized a community harvest exchange", result="Harvest finished two weeks earlier (fictional)"),
 conv("cv-15", "PRD-AWA", "labor", 55, sharing="share_summary", issue="ISS-09", action="Asked neighbors for help", result=None),
 conv("cv-16", "PRD-KOFFI", "labor", 9, sharing="share_summary", review="pending", pub="awaiting_review", issue="ISS-09", extra="Mon voisin Yao, téléphone 0102030405, a quitté la ferme.", pii=True),
 conv("cv-17", "PRD-KOFFI", "price", 35, sharing="share_summary", reconfirm=True, review="corrected", issue="ISS-10", version=2),
 conv("cv-18", "PRD-MARIAM", "soil", 1, kind="search", status="completed"),
 conv("cv-19", "PRD-MARIAM", "soil", 20, sharing="share_conversation", identity=True, issue="ISS-11", action="Added compost and cover crops", result="Early signs of better leaf color (fictional)"),
 conv("cv-20", "PRD-MARIAM", "drought", 45, sharing="share_summary", pub="withdrawn", issue="ISS-12", action=None, result=None),
 conv("cv-21", "PRD-ELENA", "water", 100, sharing="share_summary", issue="ISS-03", action="Attended a water-management workshop", result=None),
 conv("cv-22", "PRD-MATEO", "soil", 120, sharing="ftusa_only", issue="ISS-04"),
 conv("cv-23", "PRD-AWA", "price", 15, kind="out_of_scope", status="completed"),
 conv("cv-24", "PRD-DIEGO", "drought", 75, sharing="share_summary", issue="ISS-05", action=None, result=None),
]
for c in CONVS:
    if c["kind"] in ("search", "out_of_scope"):
        c.pop("summaryOriginal", None)

ISSUES = [  # status coverage: open, action_planned, action_in_progress, resolved, recurring, unknown
 {"issueId": "ISS-01", "organizationId": "ORG-AND-COL", "reporters": ["PRD-ANA", "PRD-MATEO"], "tags": ["climate_weather"], "crop": "coffee", "geography": "Huila, Colombia", "status": "action_planned",
  "events": [{"type": "reported", "by": "PRD-ANA", "daysAgo": 30}, {"type": "guidance", "daysAgo": 30, "text": "Water storage was discussed"}, {"type": "reported", "by": "PRD-MATEO", "daysAgo": 5}], "linkedConversations": ["cv-02", "cv-05", "cv-01"], "note": "Guidance given; no outcome recorded (multiple reporters, one incident)"},
 {"issueId": "ISS-02", "organizationId": "ORG-AND-COL", "reporters": ["PRD-ANA"], "tags": ["water"], "crop": "coffee", "geography": "Huila, Colombia", "status": "resolved", "resolutionConfirmed": True,
  "events": [{"type": "reported", "daysAgo": 90}, {"type": "action", "daysAgo": 80, "text": "Installed two rainwater tanks"}, {"type": "outcome", "daysAgo": 60, "text": "Fewer lost harvest days"}, {"type": "resolution_confirmed", "daysAgo": 59}], "linkedConversations": ["cv-03"]},
 {"issueId": "ISS-03", "organizationId": "ORG-AND-COL", "reporters": ["PRD-MATEO", "PRD-ELENA"], "tags": ["water"], "crop": "coffee", "geography": "Huila, Colombia", "status": "action_in_progress",
  "events": [{"type": "reported", "daysAgo": 100}, {"type": "action", "daysAgo": 12, "text": "Shared irrigation schedule"}], "linkedConversations": ["cv-04", "cv-21"], "note": "Action without a reported outcome"},
 {"issueId": "ISS-04", "organizationId": "ORG-AND-COL", "reporters": ["PRD-ELENA", "PRD-MATEO"], "tags": ["soil_land"], "crop": "coffee", "geography": "Huila, Colombia", "status": "open",
  "events": [{"type": "reported", "daysAgo": 120}, {"type": "reported", "daysAgo": 40}], "linkedConversations": ["cv-22", "cv-07"], "note": "Same challenge, different profiles; no guidance acted on"},
 {"issueId": "ISS-05", "organizationId": "ORG-COP-HON", "reporters": ["PRD-LUCIA", "PRD-DIEGO"], "tags": ["climate_weather"], "crop": "coffee", "geography": "Copán, Honduras", "status": "recurring",
  "events": [{"type": "reported", "daysAgo": 75}, {"type": "action", "daysAgo": 70, "text": "Planted shade trees"}, {"type": "outcome", "daysAgo": 60, "text": "Improved shade"}, {"type": "recurrence", "daysAgo": 8}], "linkedConversations": ["cv-24", "cv-09", "cv-08"], "note": "Resolution not confirmed; recurrence in a later season"},
 {"issueId": "ISS-06", "organizationId": "ORG-COP-HON", "reporters": ["PRD-DIEGO"], "tags": ["market_price"], "crop": "coffee", "geography": "Copán, Honduras", "status": "action_in_progress",
  "events": [{"type": "reported", "daysAgo": 25}, {"type": "action", "daysAgo": 3, "text": "Drying program"}], "linkedConversations": ["cv-11", "cv-10"]},
 {"issueId": "ISS-07", "organizationId": "ORG-COP-HON", "reporters": ["PRD-ROSA"], "tags": ["labor_migration"], "crop": "coffee", "geography": "Copán, Honduras", "status": "unknown", "events": [{"type": "reported", "daysAgo": 6}], "linkedConversations": ["cv-12"], "note": "FTUSA-only"},
 {"issueId": "ISS-08", "organizationId": "ORG-COP-HON", "reporters": ["PRD-ROSA"], "tags": ["market_price"], "crop": "coffee", "geography": "Copán, Honduras", "status": "open", "events": [{"type": "reported", "daysAgo": 60}], "linkedConversations": ["cv-13"], "note": "FTUSA-only, reviewed"},
 {"issueId": "ISS-09", "organizationId": "ORG-NAW-CIV", "reporters": ["PRD-AWA", "PRD-KOFFI"], "tags": ["labor_migration"], "crop": "cocoa", "geography": "Nawa, Côte d'Ivoire", "status": "action_in_progress",
  "events": [{"type": "reported", "daysAgo": 55}, {"type": "action", "daysAgo": 40, "text": "Asked neighbors"}, {"type": "reported", "by": "PRD-KOFFI", "daysAgo": 9}, {"type": "action", "daysAgo": 4, "text": "Community harvest exchange"}], "linkedConversations": ["cv-15", "cv-16", "cv-14"]},
 {"issueId": "ISS-10", "organizationId": "ORG-NAW-CIV", "reporters": ["PRD-KOFFI"], "tags": ["market_price"], "crop": "cocoa", "geography": "Nawa, Côte d'Ivoire", "status": "open", "events": [{"type": "reported", "daysAgo": 35}], "linkedConversations": ["cv-17"], "note": "Summary revision awaiting producer re-confirmation"},
 {"issueId": "ISS-11", "organizationId": "ORG-NAW-CIV", "reporters": ["PRD-MARIAM"], "tags": ["soil_land"], "crop": "cocoa", "geography": "Nawa, Côte d'Ivoire", "status": "action_in_progress", "events": [{"type": "reported", "daysAgo": 20}, {"type": "action", "daysAgo": 15, "text": "Compost and cover crops"}], "linkedConversations": ["cv-19"]},
 {"issueId": "ISS-12", "organizationId": "ORG-NAW-CIV", "reporters": ["PRD-MARIAM"], "tags": ["climate_weather"], "crop": "cocoa", "geography": "Nawa, Côte d'Ivoire", "status": "unknown", "events": [{"type": "reported", "daysAgo": 45}], "linkedConversations": ["cv-20"], "note": "Publication withdrawn"},
]

def corr(i, prod, field, orig, prop, status, expl=None):
    return {"correctionId": f"corr-{prod}-seed{i:02d}", "organizationId": ORG_OF[prod], "requesterProducerId": prod, "status": status, "daysAgo": 20 - i * 2,
            "changes": [{"field": field, "original": orig, "proposed": prop}], "explanation": expl}
CORRECTIONS = [
 corr(1, "PRD-ANA", "country_name", "Colombia", "Colombia (Huila)", "pending", "Add the department"),
 corr(2, "PRD-MATEO", "product_category_name", "Coffee (green, washed arabica); Specialty micro-lots", "Coffee (green, washed arabica); Specialty micro-lots; Plantain", "pending"),
 corr(3, "PRD-LUCIA", "structure_txt", "Association of 210 smallholder members in 9 communities", "Association of 210 smallholder members in 10 communities", "accepted_awaiting_source_update"),
 corr(4, "PRD-DIEGO", "certification_status_name", "Certified", "Certified (renewed 2026)", "applied"),
 corr(5, "PRD-AWA", "raw_supply_chain_role_txt", "Grower (member farms); Aggregator; Fermentation and drying", "Grower (member farms); Aggregator; Fermentation and drying; Exporter", "rejected", "We also dry beans"),
 corr(6, "PRD-KOFFI", "account_type_name", "Small producer organization (SPO)", "Producer group", "pending"),
]
for c in CORRECTIONS: c["decidedBy"] = {"pending": None}.get(c["status"], "Reviewer One")

# 12 Premium projects (fictional), keyed by organization (Premium accrues to the organization).
PREMIUM = []
for i, (o, title, tag, amt, st) in enumerate([
    ("ORG-AND-COL", "Rainwater catchment tanks", "water", 8000, "completed"), ("ORG-AND-COL", "Shade-tree nursery", "climate_weather", 5200, "completed"),
    ("ORG-AND-COL", "Soil testing lab access", "soil_land", 3000, "in_progress"), ("ORG-AND-COL", "Community scholarship", "education", 4000, "completed"),
    ("ORG-COP-HON", "Solar drying beds", "market_price", 7000, "completed"), ("ORG-COP-HON", "Pruning training", "climate_weather", 2500, "in_progress"),
    ("ORG-COP-HON", "Harvest worker housing", "labor_migration", 9000, "planned"), ("ORG-COP-HON", "Credit guarantee fund", "financial_capital", 6000, "completed"),
    ("ORG-NAW-CIV", "Village water point", "water", 7500, "completed"), ("ORG-NAW-CIV", "Cocoa seedling distribution", "soil_land", 4800, "in_progress"),
    ("ORG-NAW-CIV", "Harvest labor exchange", "labor_migration", 3500, "in_progress"), ("ORG-NAW-CIV", "Health post supplies", "health", 3000, "completed")], 1):
    PREMIUM.append({"projectId": f"PRJ-V2-{i:02d}", "organizationId": o, "year": 2023 + (i % 3), "title": title, "tags": [tag], "amountUsd": amt, "status": st, "synthetic": True})

SURVEYS = [{"organizationId": o["organizationId"], "year": 2025, "topConcern": c, "respondents": r, "synthetic": True} for o, c, r in zip(ORGS, ["climate_weather", "market_price", "labor_migration"], [112, 64, 143])]
CERTS = [{"organizationId": o["organizationId"], "standard": "Fair Trade (synthetic reference)", "status": o["info"]["certificationStatusName"], "lastAudit": "2025-09-15", "synthetic": True} for o in ORGS]
EVIDENCE = [  # regional; ILLUSTRATIVE, not measured data. origin vs curation are separate fields.
 {"evidenceId": "EV-01", "geography": "Huila, Colombia", "period": "2025-12 to 2026-03", "tag": "climate_weather", "finding": "Rainfall was below the multi-year average during the flowering window (illustrative).", "origin": "external_imported", "source": "Synthetic climate table", "curationStatus": "not_curated", "illustrative": True, "standards": []},
 {"evidenceId": "EV-02", "geography": "Huila, Colombia", "period": "2026", "tag": "water", "finding": "Household rainwater storage is a documented drought buffer (illustrative).", "origin": "ftusa_authored", "source": "FTUSA guidance note (synthetic)", "curationStatus": "ftusa_curated", "illustrative": True, "standards": []},
 {"evidenceId": "EV-03", "geography": "Copán, Honduras", "period": "2026-Q2", "tag": "market_price", "finding": "Reference prices declined over the quarter (illustrative).", "origin": "external_imported", "source": "Synthetic market table", "curationStatus": "ftusa_curated", "illustrative": True, "standards": []},
 {"evidenceId": "EV-04", "geography": "Nawa, Côte d'Ivoire", "period": "2025", "tag": "soil_land", "finding": "Soil organic matter below target on sampled plots (illustrative; sample is small, so treat as a limitation).", "origin": "external_imported", "source": "Synthetic soil survey", "curationStatus": "not_curated", "illustrative": True, "standards": []},
 {"evidenceId": "EV-05", "geography": "Nawa, Côte d'Ivoire", "period": "2024", "tag": "labor_migration", "finding": "Older figures; newer data conflicts (stale/conflicting evidence fixture).", "origin": "external_imported", "source": "Synthetic labor table", "curationStatus": "not_curated", "illustrative": True, "stale": True, "conflictsWith": "EV-06", "standards": []},
 {"evidenceId": "EV-06", "geography": "Nawa, Côte d'Ivoire", "period": "2026", "tag": "labor_migration", "finding": "Different labor estimate for the same area (conflicting fixture).", "origin": "external_imported", "source": "Synthetic labor table v2", "curationStatus": "not_curated", "illustrative": True, "standards": []},
]
FAILURES = {"memoryUpdateFailures": [{"outcomeId": "rec-cv-17", "reason": "memory_write_failed", "retries": 2}], "retryFixtures": [{"requestId": "seed-retry-001", "note": "duplicate turn submission fixture"}]}

# ---- history for the ORIGINAL demo accounts (their organizations get colleagues without logins so "my peers" is realistic) ----
LEGACY = {  # old account id -> (organization id, colleagues [(id, name, language)])
    "P-MX-004": ("ORG-P-MX-004", [("PRD-MX-CARLA", "Carla", "es"), ("PRD-MX-JOSE", "José", "es")]),
    "P-CO-001": ("ORG-P-CO-001", [("PRD-CO-LUIS", "Luis", "es"), ("PRD-CO-MARTA", "Marta", "es")]),
    "P-CI-005": ("ORG-P-CI-005", [("PRD-CI-ADAMA", "Adama", "fr"), ("PRD-CI-FATOU", "Fatou", "fr")]),
}
LEGACY_LANG = {"P-MX-004": "en", "P-CO-001": "es", "P-CI-005": "fr"}
LEGACY_PRODUCERS, LEGACY_CONVS, n = [], [], 100
for owner, (org, cols) in LEGACY.items():
    ORG_OF[owner] = org; LANG_OF[owner] = LEGACY_LANG[owner]
    for pid, nm, lg in cols:
        ORG_OF[pid] = org; LANG_OF[pid] = lg
        LEGACY_PRODUCERS.append({"producerId": pid, "displayName": nm, "organizationId": org, "preferredLanguage": lg, "entityType": "smallholder", "location": "", "crop": "coffee" if owner != "P-CI-005" else "cocoa", "noLogin": True, "synthetic": True})
    c1, c2 = cols
    topics = ("drought", "water", "price") if owner != "P-CI-005" else ("labor", "soil", "price")
    plan = [  # (producer, topic, daysAgo, sharing, identity, review/pub, action, result)
        (owner, topics[0], 2, "share_summary", False, ("pending", "awaiting_review"), None, None),
        (owner, topics[1], 21, "ftusa_only", False, ("approved", "not_shared"), "Joined a group purchase of storage tanks", "Too early to tell (fictional)"),
        (owner, topics[2], 63, "share_summary", False, ("approved", "published"), "Sold through the cooperative's forward contract", "Income steadier across the season (fictional)"),
        (c1[0], topics[0], 6, "share_conversation", True, ("approved", "published"), "Shifted pruning and added mulch", "Fewer plants lost this season (fictional)"),
        (c1[0], topics[2], 38, "ftusa_only", False, ("approved", "not_shared"), None, None),
        (c1[0], topics[1], 80, "share_summary", False, ("approved", "published"), "Dug a shared reservoir with two neighbors", "Water lasted through the dry weeks (fictional)"),
        (c2[0], topics[1], 4, "share_summary", False, ("pending", "awaiting_review"), None, None),
        (c2[0], topics[0], 27, "ftusa_only", False, ("pending", "not_shared"), "Asked the cooperative technician for a visit", None),
        (c2[0], topics[2], 52, "share_conversation", True, ("approved", "published"), "Negotiated a delayed sale with the buyer", "Price recovered partly (fictional)"),
    ]
    for pid, topic, days, sh, ident, (rv, pb), act, res in plan:
        n += 1
        LEGACY_CONVS.append(conv(f"cv-{n}", pid, topic, days, sharing=sh, identity=ident, review=rv, pub=pb, action=act, result=res))
    n += 1; LEGACY_CONVS.append(conv(f"cv-{n}", owner, topics[0], 0, status="active"))
    n += 1; LEGACY_CONVS.append(conv(f"cv-{n}", owner, "soil" if owner != "P-CI-005" else "drought", 9, kind="search"))
for c in LEGACY_CONVS:
    if c["kind"] == "search": c.pop("summaryOriginal", None)

def dump(name, obj):
    (OUT / name).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    dump("organizations.json", {"_notice": NOTE, "organizations": ORGS})
    dump("people.json", {"_notice": NOTE, "producers": producers, "reviewers": reviewers})
    dump("conversations.json", {"_notice": NOTE, "conversations": CONVS})
    dump("issues.json", {"_notice": NOTE, "issues": ISSUES})
    dump("corrections.json", {"_notice": NOTE, "corrections": CORRECTIONS})
    dump("premium_projects.json", {"_notice": NOTE, "projects": PREMIUM})
    dump("surveys_certifications.json", {"_notice": NOTE, "surveys": SURVEYS, "certifications": CERTS})
    dump("regional_evidence.json", {"_notice": NOTE, "evidence": EVIDENCE})
    dump("legacy_history.json", {"_notice": NOTE, "producers": LEGACY_PRODUCERS, "conversations": LEGACY_CONVS})
    dump("failure_fixtures.json", {"_notice": NOTE, **FAILURES})
    print("wrote", len(CONVS), "conversations,", len(ISSUES), "issues,", len(CORRECTIONS), "corrections")
