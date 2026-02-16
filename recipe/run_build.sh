#!/bin/bash
set -euo pipefail

export PKG_VERSION=$(pixi run python ../print_version.py)

rattler-build build -c ga-fdp -c conda-forge --channel-priority=disabled
