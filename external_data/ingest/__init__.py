"""Component 5 ingest modules — one per dataset.

Each module: fetch -> aggregate to the pilot countries -> write to the
``environmental_facts`` cache (idempotent upserts, ING-6). The heavy work
happens here, at ingest — never on the tool's hot path (NFR-1).
"""
