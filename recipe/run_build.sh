#!/bin/bash
set -euo pipefail

export PKG_VERSION=$(pixi run python ../print_version.py)

echo "Building version: ${PKG_VERSION}"

OUTPUT_DIR="${1:-${HOME}/outdir}"
mkdir -p "${OUTPUT_DIR}"

CHANNEL_FLAGS="-c ga-fdp -c conda-forge"
if [ -n "${EXTRA_CHANNEL:-}" ]; then
    CHANNEL_FLAGS="-c ${EXTRA_CHANNEL} ${CHANNEL_FLAGS}"
fi

# Both OS variants are built here, but each can only be tested on its own
# OS: build untested, then test the variant native to this machine. CI's
# macOS job tests the other one.
rattler-build build \
  ${CHANNEL_FLAGS} \
  --channel-priority=disabled \
  --test skip \
  --output-dir "${OUTPUT_DIR}"

# CI tests every python in a matrix instead (RUN_TESTS=0).
if [ "${RUN_TESTS:-1}" = "0" ]; then
    exit 0
fi

case "$(uname -s)" in
    Darwin) NATIVE=osx ;;
    *) NATIVE=linux ;;
esac
shopt -s nullglob
tested=0
for pkg in "${OUTPUT_DIR}"/noarch/toksearch_d3d-"${PKG_VERSION}"-*_"${NATIVE}".conda; do
    rattler-build test --package-file "${pkg}" \
      ${CHANNEL_FLAGS} \
      --channel-priority=disabled
    tested=$((tested + 1))
done
if [ "${tested}" -eq 0 ]; then
    echo "no ${NATIVE} variant was built to test" >&2
    exit 1
fi
