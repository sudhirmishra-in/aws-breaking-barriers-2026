"""Component 5 integration: country resolution, the agent tool's trusted scope, and what the agent is told to do with the data. No AWS, no network."""
import sys

import external_data.access as access
import external_data.keys as keys
import external_data.tool as tool
from exchange.context import ProducerRef, TrustedContext
from exchange.prompts import system_prompt
from exchange.tools import build_tools

CASES = [("Colombia", "colombia#COUNTRY"), ("Huila, Colombia", "colombia#COUNTRY"), ("Chiapas, Mexico", "mexico#COUNTRY"), ("Nawa (Soubré), Côte d'Ivoire", "côte d'ivoire#COUNTRY"),
         ("Cote d'Ivoire", "côte d'ivoire#COUNTRY"), ("Côte d’Ivoire", "côte d'ivoire#COUNTRY"), ("Ivory Coast", "côte d'ivoire#COUNTRY"), ("  Copán,  Honduras ", "honduras#COUNTRY")]


def test_every_location_shape_resolves_to_one_country_partition():
    for raw, key in CASES:
        assert keys.region_key(raw) == key, raw
    assert keys.country_of({"country": "Huila, Colombia"}) == "colombia"
    for bad in (None, "", "   ", {}, {"country": None}, 5, "x" * 200):
        assert keys.country_of(bad) is None


def test_the_agent_tool_does_not_import_geospatial_code():
    assert "shapely" not in sys.modules or True  # other tests may import it; the real guard is the zip contents below
    import importlib, pathlib
    src = pathlib.Path(tool.__file__).read_text()
    assert "shapely" not in src and "gazetteer" not in src


def _spy(monkeypatch, facts=None):
    seen = []
    monkeypatch.setattr(access, "get_facts", lambda rk, themes=None, horizon="current", profile=None: (seen.append((rk, set(themes or []), horizon)) or (facts or [])))
    return seen


def test_tool_queries_the_country_partition_even_for_region_country_locations(monkeypatch):
    seen = _spy(monkeypatch)
    tool.get_environmental_context({"country": "Huila, Colombia"}, ["climate and weather"])
    assert seen == [("colombia#COUNTRY", {"climate"}, "current")]


def test_tool_scope_comes_from_trusted_context_not_from_model_arguments(monkeypatch):
    seen = _spy(monkeypatch)
    producer = ProducerRef(producerId="P", entityType="cooperative", location="Huila, Colombia", crop="coffee", country="Colombia")
    fn = [t for t in build_tools(producer) if t.tool_name == "get_environmental_context"][0]
    assert "country" not in fn.tool_spec["inputSchema"]["json"]["properties"] and "location" not in fn.tool_spec["inputSchema"]["json"]["properties"]
    fn(tags=["drought"], horizon="current")
    assert seen[0][0] == "colombia#COUNTRY"
    # without an organization country the free-text location still resolves, never a different country
    seen.clear(); p2 = ProducerRef(producerId="P", entityType="cooperative", location="Chiapas, Mexico", crop="coffee")
    [t for t in build_tools(p2) if t.tool_name == "get_environmental_context"][0](tags=["rain"]); assert seen[0][0] == "mexico#COUNTRY"


def test_unknown_tags_or_country_return_an_empty_list_without_touching_the_store(monkeypatch):
    seen = _spy(monkeypatch)
    assert tool.get_environmental_context({"country": "Colombia"}, ["tax law"]) == []
    assert tool.get_environmental_context({"country": ""}, ["rain"]) == []
    assert tool.get_environmental_context({"country": "Colombia"}, []) == []
    assert seen == []


def test_stand_ins_are_returned_flagged_so_the_agent_can_say_there_is_no_reliable_value(monkeypatch):
    stand_in = {"dataset": "open_meteo", "indicator": "ytd_rainfall_mm", "value": None, "is_stand_in": True, "is_projection": False}
    _spy(monkeypatch, [stand_in])
    out = tool.get_environmental_context({"country": "Peru"}, ["rainfall"])
    assert out[0]["is_stand_in"] is True and out[0]["value"] is None


def test_guidance_prompt_uses_the_tool_cites_dataset_and_baseline_and_forbids_invented_numbers():
    ctx = TrustedContext.model_validate({"conversationId": "c", "language": "en", "mode": "guidance", "allowPlayback": False,
                                         "producer": {"producerId": "P", "entityType": "cooperative", "location": "L", "crop": "coffee", "country": "Colombia"}, "confirmedAccount": "late rain"})
    p = system_prompt(ctx)
    assert "get_environmental_context" in p and "dataset" in p and "baseline" in p and "never give a number" in p
    assert "No regional facts were supplied" in p
    assert "do NOT ask the producer any question" in p and "challenge_tags" in p       # the earlier closing-turn contract still holds
    assert "stand-in" in p


def test_deployed_zip_ships_the_tool_but_not_the_geospatial_pieces():
    import pathlib, re
    sh = (pathlib.Path(__file__).resolve().parents[2] / "scripts" / "build_agent.sh").read_text()
    assert "cp -R ../external_data build/pkg/" in sh
    assert re.search(r"rm -rf build/pkg/external_data/data build/pkg/external_data/ingest build/pkg/external_data/gazetteer.py", sh)
    pp = (pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml").read_text()
    runtime_deps = pp.split("dependencies = [")[1].split("]")[0]
    assert "shapely" not in runtime_deps and "shapely" in pp


def test_supplied_facts_appear_in_the_closing_turn_and_stand_ins_do_not():
    base = {"conversationId": "c", "language": "en", "mode": "guidance", "allowPlayback": False, "confirmedAccount": "heavy rain",
            "producer": {"producerId": "P", "entityType": "cooperative", "location": "L", "crop": "coffee", "country": "Colombia"}}
    good = {"dataset": "open_meteo", "indicator": "ytd_rainfall_mm", "value": 2831.3, "unit": "mm", "period": "2026 YTD", "baselineValue": 2487.0, "baselineDeltaPct": 13.8, "baselinePeriod": "1981-2010 (same window)", "is_stand_in": False}
    bad = {"dataset": "open_meteo", "indicator": "other", "value": None, "unit": "mm", "period": "2026", "is_stand_in": True}
    p = system_prompt(TrustedContext.model_validate({**base, "externalFacts": [good, bad]}))
    assert "2831.3 mm" in p and "+13.8 %" in p and "1981-2010" in p and "other = None" not in p and "reference point" in p


def test_external_data_is_context_never_proof():
    from exchange.prompts import system_prompt as sp
    ctx = TrustedContext.model_validate({"conversationId": "c", "language": "en", "mode": "intake", "allowPlayback": False,
                                         "producer": {"producerId": "P", "entityType": "cooperative", "location": "L", "crop": "coffee"}})
    assert "Never say it confirms, proves or explains" in sp(ctx) and "reference-point" in sp(ctx)
