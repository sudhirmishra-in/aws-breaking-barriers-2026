#!/usr/bin/env bash
# Builds agent/dist/agent.zip: arm64 Linux wheels for Python 3.13 + app code (AgentCore CodeZip artifact).
set -euo pipefail
cd "$(dirname "$0")/../agent"
rm -rf dist build && mkdir -p dist build/pkg
uv export --no-dev --no-hashes --no-emit-project -o build/requirements.txt >/dev/null
uv pip install --quiet --target build/pkg --python-version 3.13 --python-platform aarch64-manylinux2014 -r build/requirements.txt
cp -R app/* build/pkg/
cp -R ../external_data build/pkg/   # Component 5: ship the external-datasets package + gazetteer GeoJSON into the agent zip
find build/pkg -name '__pycache__' -type d -prune -exec rm -rf {} +
(cd build/pkg && zip -qr ../../dist/agent.zip .)
ls -lh dist/agent.zip
