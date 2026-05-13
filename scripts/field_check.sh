#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  cat <<'USAGE'
Usage: scripts/field_check.sh <command>

Commands:
  urls      Print derived dashboard and SRT URLs
  health    GET /health from the dashboard/API
  status    GET /status from the dashboard/API
  config    GET /config from the dashboard/API
  srt       Probe the SRT stream and list streams with ffprobe
  sample    Decode one KLV tag 120 JSON sample from the SRT data stream
  preflight Run urls, health, status, and config
  all       Run urls, health, status, config, srt, and sample

Inputs:
  PF_DASHBOARD_URL and PF_SRT_URL override derived URLs.
  PARROT_FORWARDER_FIELD__TAILSCALE_HOST provides the default remote host.
  PARROT_FORWARDER_FIELD__ADVERTISED_* override dashboard/SRT host or port.
  PARROT_FORWARDER_SUPERVISOR__HTTP__PORT defaults to 8080.
  PARROT_FORWARDER_FORWARDER__SRT_PORT defaults to 8890.
USAGE
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    return 127
  fi
}

dashboard_base_url() {
  local scheme="${PARROT_FORWARDER_FIELD__DASHBOARD_SCHEME:-http}"
  local host="${PARROT_FORWARDER_FIELD__ADVERTISED_DASHBOARD_HOST:-${PARROT_FORWARDER_FIELD__TAILSCALE_HOST:-localhost}}"
  local port="${PARROT_FORWARDER_FIELD__ADVERTISED_DASHBOARD_PORT:-${PARROT_FORWARDER_SUPERVISOR__HTTP__PORT:-8080}}"
  local url="${PF_DASHBOARD_URL:-${scheme}://${host}:${port}}"
  printf '%s\n' "${url%/}"
}

srt_probe_url() {
  local dashboard_host="${PARROT_FORWARDER_FIELD__ADVERTISED_DASHBOARD_HOST:-${PARROT_FORWARDER_FIELD__TAILSCALE_HOST:-localhost}}"
  local host="${PARROT_FORWARDER_FIELD__ADVERTISED_SRT_HOST:-${PARROT_FORWARDER_FIELD__TAILSCALE_HOST:-${dashboard_host}}}"
  local port="${PARROT_FORWARDER_FIELD__ADVERTISED_SRT_PORT:-${PARROT_FORWARDER_FORWARDER__SRT_PORT:-8890}}"
  local url="${PF_SRT_URL:-srt://${host}:${port}?mode=caller}"
  printf '%s\n' "$url"
}

json_pretty() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    "${PYTHON:-python3}" -m json.tool
  fi
}

curl_json() {
  require_cmd curl
  local path="$1"
  local base
  base="$(dashboard_base_url)"
  curl -fsS --max-time "${PF_CURL_TIMEOUT_SECONDS:-5}" "${base}${path}" | json_pretty
}

with_timeout() {
  local seconds="${PF_SAMPLE_TIMEOUT_SECONDS:-12}"
  if command -v timeout >/dev/null 2>&1; then
    timeout "$seconds" "$@"
  else
    "$@"
  fi
}

cmd_urls() {
  printf 'dashboard=%s\n' "$(dashboard_base_url)"
  printf 'srt=%s\n' "$(srt_probe_url)"
}

cmd_health() {
  curl_json "/health"
}

cmd_status() {
  curl_json "/status"
}

cmd_config() {
  curl_json "/config"
}

cmd_srt() {
  require_cmd ffprobe
  local url
  url="$(srt_probe_url)"
  with_timeout ffprobe \
    -hide_banner \
    -loglevel error \
    -rw_timeout 5000000 \
    -i "$url" \
    -show_entries stream=index,codec_type,codec_name \
    -of json | json_pretty
}

cmd_sample() {
  require_cmd ffmpeg
  require_cmd "${PYTHON:-python3}"
  local url
  url="$(srt_probe_url)"
  with_timeout ffmpeg \
    -hide_banner \
    -loglevel error \
    -rw_timeout 5000000 \
    -i "$url" \
    -map 0:d:0 \
    -c copy \
    -frames:d 1 \
    -f data - | "${PYTHON:-python3}" "$SCRIPT_DIR/klv_tag120_sample.py"
}

cmd_preflight() {
  cmd_urls
  cmd_health
  cmd_status
  cmd_config
}

cmd_all() {
  cmd_preflight
  cmd_srt
  cmd_sample
}

main() {
  local command="${1:-}"
  case "$command" in
    urls) cmd_urls ;;
    health) cmd_health ;;
    status) cmd_status ;;
    config) cmd_config ;;
    srt) cmd_srt ;;
    sample) cmd_sample ;;
    preflight) cmd_preflight ;;
    all) cmd_all ;;
    -h|--help|help|"")
      usage
      ;;
    *)
      echo "unknown command: $command" >&2
      usage >&2
      return 2
      ;;
  esac
}

main "$@"
