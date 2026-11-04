"""Component 5 — External datasets (climate, soil, water, biodiversity, tenure,
prices, elevation).

The agent grounds its answers in real external geospatial/climate data for the
producer's region. All data is pre-aggregated and cached (never pulled on a
call); every figure is attributable (dataset, period, method) and forward-looking
figures are labeled projections.

Modules:
  gazetteer   — country -> geometry (the keystone bridging name-only data to grids)
  access      — the backend-agnostic data-access layer (DynamoDB environmental_facts)
  tool        — get_environmental_context (the Strands tool)
  ingest/     — one module per dataset (fetch -> aggregate to country -> cache)
"""
