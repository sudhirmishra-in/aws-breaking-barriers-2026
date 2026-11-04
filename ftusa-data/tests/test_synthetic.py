"""Synthetic generator: determinism, schema parity, profile realism, and integration with the pipeline and C3 tools."""
import csv
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from ftusa_data import io
from ftusa_data import synthetic as gen
from ftusa_data.config import CHALLENGE_TAGS

ROOT = Path(os.environ.get('FTUSA_PROJECT_ROOT', Path(__file__).resolve().parents[1]))


@pytest.fixture(scope='module')
def built(tmp_path_factory):
    d = tmp_path_factory.mktemp('syn')
    gen.generate(d / 'raw', ROOT / 'raw')
    gen.build(d / 'raw', d / 'out')
    return d


def test_determinism_and_refuse_overwrite(tmp_path):
    for directory in ('a', 'b'):
        gen.generate(tmp_path / directory, ROOT / 'raw', 123)
    for path in (tmp_path / 'a').glob('*.csv'):
        assert path.read_bytes() == (tmp_path / 'b' / path.name).read_bytes()
    with pytest.raises(FileExistsError):
        gen.generate(tmp_path / 'a', ROOT / 'raw', 123)


def test_raw_schema_matches_ftusa_sample(built):
    """The FTUSA sample must stay a drop-in replacement: same files, same columns, same order."""
    for key, cols in gen.COLUMNS.items():
        assert list(pd.read_csv(built / 'raw' / io.RAW_FILES[key], nrows=0).columns) == cols
        try:
            real = io.find(ROOT / 'raw', key)
        except FileNotFoundError:
            continue
        assert list(pd.read_csv(real, nrows=0).columns) == cols, key


def test_survey_metrics_differ_by_profile(built):
    s = pd.read_csv(built / 'out/tables/survey_summary/survey_summary.csv')
    latest = s.sort_values('survey_year').groupby('account_sk').tail(1)
    shown = latest[latest.n_responses >= 10]
    # regression: one categorical answer used to be written for every respondent (100% "no drinking water")
    for col in ['pct_no_drinking_water', 'pct_temporary_workers', 'pct_no_ipm_practices', 'pct_water_conservation']:
        assert not (shown[col] == 100).all(), col
    assert shown.pct_harvest_decreased.nunique() == len(shown)
    assert shown.top_borrow_sources.str.split(' ').str[0].nunique() > 1
    # longitudinal + small-n suppression
    assert (s.groupby('account_sk').survey_year.nunique() > 1).any()
    assert s[s.n_responses < 10].pct_harvest_decreased.isna().all()


def test_pipeline_and_private_scope(built):
    from c3.tools import local_data_access, impl_get_producer_record, impl_find_similar_projects
    from c3.access import Session
    access = local_data_access(built / 'out/tables')
    record = impl_get_producer_record(access, Session('SYN-42-01'))
    assert record['survey']['n_responses'] == 20
    with (built / 'out/tables/premium_projects/premium_projects.csv').open() as f:
        rows = list(csv.DictReader(f))
    owned = {r['project_id'] for r in rows if r['account_sk'] == 'SYN-42-01'}
    excluded = {r['project_id'] for r in rows if r['is_peer_eligible'] != 'True'}
    assert {p['project_id'] for p in record['projects']} == owned
    assert impl_get_producer_record(access, Session('DOES-NOT-EXIST'))['error'] == 'no_session_producer'
    for acct, query in [('SYN-42-01', 'drought rainfall water'), ('SYN-42-03', 'coffee prices income'),
                        ('SYN-42-04', 'labor shortage workers migration')]:
        peers = impl_find_similar_projects(access, Session(acct), query, top_k=5)['results']
        assert peers, acct
        assert all('account_sk' not in p for p in peers)
        assert not {p['project_id'] for p in peers} & (owned | excluded)
    assert impl_get_producer_record(access, Session('SYN-42-05'))['survey'] is None


def test_scenarios_are_consistent(built):
    scenarios = json.loads((built / 'raw/scenarios.json').read_text())
    prod = pd.read_csv(built / 'out/tables/producers/producers.csv').set_index('account_sk')
    exchanges = [s for s in scenarios if s['scenario_id'].startswith('exchange')]
    assert len(exchanges) >= 3 and any(s['language'] == 'es' for s in exchanges)
    for s in scenarios:
        assert s['account_sk'] in prod.index
        assert set(s.get('expected_tags', [])) <= set(CHALLENGE_TAGS)
    water = [s for s in exchanges if s.get('contrast_group') == 'water']
    assert len({prod.at[s['account_sk'], 'entity_type'] for s in water}) == 2
    decline = next(s for s in scenarios if s['scenario_id'] == 'decline')
    assert len(decline['turns']) >= 2  # starts describing a challenge, then declines (Journey 2)
