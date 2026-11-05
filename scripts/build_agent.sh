#!/usr/bin/env bash
# Builds agent/dist/agent.zip: arm64 Linux wheels for Python 3.13 + app code (AgentCore CodeZip artifact).
set -euo pipefail
cd "$(dirname "$0")/../agent"
rm -rf dist build && mkdir -p dist build/pkg
uv export --no-dev --no-hashes --no-emit-project -o build/requirements.txt >/dev/null
uv pip install --quiet --target build/pkg --python-version 3.13 --python-platform aarch64-manylinux_2_28 -r build/requirements.txt
cp -R app/* build/pkg/
cp -R ../external_data build/pkg/   # Component 5: the tool, data access and keys only; the gazetteer, GeoJSON and ingest (shapely) stay offline
rm -rf build/pkg/external_data/data build/pkg/external_data/ingest build/pkg/external_data/gazetteer.py
find build/pkg -name '__pycache__' -type d -prune -exec rm -rf {} +
(cd build/pkg && zip -qr ../../dist/agent.zip .)
ls -lh dist/agent.zip
