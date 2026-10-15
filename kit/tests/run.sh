#!/usr/bin/env bash
# The kit's tests: node unit tests, then the headless-Chromium end-to-end run.
# Needs Node >= 22 and Python 3 with playwright (+ Chromium), numpy and scipy
# (kit/tests/requirements.txt). Generated audio only ever lives in temporary directories.
set -euo pipefail
cd "$(dirname "$0")/../.."
node --test 'kit/tests/unit/*.test.js'
python3 kit/tests/e2e.py
