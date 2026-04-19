#!/bin/sh
# Seed the mounted config directory if empty, then hand off to the supervisor.
set -e

CONFIG_DIR="/etc/parrot-forwarder"
CONFIG_FILE="${CONFIG_DIR}/config.yaml"
EXAMPLE_FILE="/opt/pf/config.yaml.example"

mkdir -p "${CONFIG_DIR}"

if [ ! -f "${CONFIG_FILE}" ]; then
    if [ -f "${EXAMPLE_FILE}" ]; then
        cp "${EXAMPLE_FILE}" "${CONFIG_FILE}"
        echo "Seeded default config at ${CONFIG_FILE}"
    else
        echo "ERROR: no config file and no example available at ${EXAMPLE_FILE}" >&2
        exit 1
    fi
fi

exec /opt/pf/.venv/bin/parrot-forwarder-supervisor --config "${CONFIG_FILE}" "$@"
