# WP-03 (Parrot) Field Validation Prep

This runbook prepares ParrotForwarder for real field validation over a trusted
site network or Tailscale. It is not live acceptance by itself. Do not mark SRT,
KLV, telemetry accuracy, restart recovery, or detector consumption accepted
until a powered drone/controller and the target consumer have been exercised.

## Git-safe environment

Start from the committed template and keep the filled file untracked:

```bash
cp field.env.example field.env
set -a; source ./field.env; set +a
```

Fill only non-secret endpoint metadata:

- `PARROT_FORWARDER_FIELD__TAILSCALE_HOST`: Tailscale DNS name or Tailscale IP of the field node.
- `PARROT_FORWARDER_FIELD__ADVERTISED_DASHBOARD_HOST`: optional dashboard host override.
- `PARROT_FORWARDER_FIELD__ADVERTISED_DASHBOARD_PORT`: optional dashboard port override.
- `PARROT_FORWARDER_FIELD__ADVERTISED_SRT_HOST`: optional SRT host override.
- `PARROT_FORWARDER_FIELD__ADVERTISED_SRT_PORT`: optional SRT port override.
- `PF_DASHBOARD_URL` and `PF_SRT_URL`: optional exact helper URLs when the advertised fields are not enough.

Do not add wallets, secrets, private notes, local absolute paths, site-specific
hostnames, or private addresses to committed files.

## Runtime launch

```bash
set -a; source ./field.env; set +a
docker compose up -d --build
docker compose ps
```

The compose stack uses host networking. `PARROT_FORWARDER_SUPERVISOR__HTTP__PORT`
controls the dashboard/API listen port, and `PARROT_FORWARDER_FORWARDER__SRT_PORT`
controls the SRT listener port. The `field.*` config values are advertised
endpoint metadata only; they do not change listen behavior.

## Operator checks

Run from the field node or a client that can reach the advertised Tailscale
endpoint:

```bash
set -a; source ./field.env; set +a
scripts/field_check.sh urls
scripts/field_check.sh health
scripts/field_check.sh status
scripts/field_check.sh config
```

Expected result:

- `health` returns `{"status":"ok"}`.
- `status` returns the supervisor state and restart counters.
- `config` returns the effective config, including the `field` metadata.

These checks do not prove live SRT or KLV acceptance.

## SRT and KLV checks

With drone/controller powered and forwarding active:

```bash
set -a; source ./field.env; set +a
scripts/field_check.sh srt
scripts/field_check.sh sample
scripts/field_check.sh sample-n
```

`srt` uses `ffprobe` to list the MPEG-TS streams from the SRT URL. The expected
shape is one H.264 video stream plus one data stream.

`sample` uses `ffmpeg` to extract one data packet and decodes MISB 0601 tag
`120`. The expected payload contains:

- `contract_version: aion.parrot.telemetry.v1`
- `source: parrot_forwarder`
- `source_id` and `source_name` for the real drone label
- `timestamp_us`
- `sequence`
- `telemetry` with the full ParrotForwarder sample

`sample-n` decodes multiple data packets so cadence and field stability can be
checked before starting a longer recording.

If `sample` times out or does not find tag `120`, do not treat the stream as
validated. Check the supervisor state, drone/controller link, SRT URL, and
whether the running image includes the latest ParrotForwarder code.

## Indoor no-GPS check

When validating indoors, GPS is expected to be invalid. The stream is accepted
only if tag `120` reports `position_valid=false`, leaves
`position_latitude`/`position_longitude` as `null`, and does not publish
hardcoded compatibility coordinates. Battery, product/source identity, camera,
gimbal, and any Olympe-provided altitude fields should still be captured.

## Recording audit

Start and stop a short recording through the API:

```bash
set -a; source ./field.env; set +a
PF_REC_MISSION=indoor-smoke PF_REC_DRONE=anafi scripts/field_check.sh record-start
# wait 20-30 seconds
scripts/field_check.sh record-stop
scripts/field_check.sh record-status
```

Audit the resulting `.ts` file on the machine that can read the recordings
directory:

```bash
scripts/field_check.sh audit-file recordings/<date>/<mission>/<file>.ts
```

The audit must report H.264 video, a KLV data stream, tag `120` presence,
cadence, `source_id`/`source_name`, GPS valid/invalid counts, altitude field
availability, and any missing required tag `120` fields.

## Evidence to record

For WP-03 (Parrot), record exact command/result evidence in the root WP evidence
file after the field run. Include:

- Commit hash under test.
- Whether the source was live drone/controller or mock.
- Exact exported non-secret endpoint metadata.
- `docker compose ps` result.
- `scripts/field_check.sh health` result.
- `scripts/field_check.sh status` result.
- `scripts/field_check.sh config` result.
- `scripts/field_check.sh srt` result.
- `scripts/field_check.sh sample` result or failure.
- `scripts/field_check.sh sample-n` result or failure.
- Recording start/stop/status result.
- `scripts/field_check.sh audit-file <file.ts>` summary.
- Duration of sustained SRT playback.
- Explicit limitations, including any missing detector-side consumption.
