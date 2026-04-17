# ParrotForwarder v2 - Operator Runbook

Practical, paste-able procedures for installing, upgrading, rolling back, and
troubleshooting the v2 service. If you are reading this during an incident:
skip to [Quick diagnostic flow](#quick-diagnostic-flow).

## Target host

- Ubuntu 24.04 LTS ARM64.
- User `pf` with sudo (or `oracle` on legacy hosts).
- Parrot Anafi + Skycontroller 3 on USB; drone reachable at `192.168.53.1`.

## Install (cold)

```bash
git clone https://github.com/fsabiu/ParrotForwarder.git
cd ParrotForwarder
./scripts/install.sh            # idempotent - safe to re-run
source .venv/bin/activate
parrot-forwarder --help
```

Environment overrides for the installer:
- `PF_SKIP_APT=1`   - skip apt packages (already provisioned).
- `PF_SKIP_PYENV=1` - use system `python3.11`.

## Run under systemd

The v1 unit file at `parrot_forwarder.service` still works for v2; update the
`ExecStart` line to point at the new venv:

```ini
[Service]
ExecStart=/home/pf/ParrotForwarder/.venv/bin/parrot-forwarder
```

Reload and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now parrot_forwarder
sudo journalctl -u parrot_forwarder -f
```

Logs are rotating JSON at the path in `config.yaml` (`/var/log/parrot-forwarder/forwarder.log`). `journalctl` also captures stdout for the last service run.

## Upgrade

```bash
cd ParrotForwarder
git pull origin main                    # or the tagged release
source .venv/bin/activate
pip install -e . --upgrade
sudo systemctl restart parrot_forwarder
```

If the upgrade changes `requirements.txt`, re-run `./scripts/install.sh` and
let it reconcile (it's idempotent).

## Rollback

The v1 pipeline path is wire-compatible with the v2 SRT output, so rollback
is non-destructive for consumers:

```bash
cd ParrotForwarder
git checkout v1-stable                 # or a known-good SHA
pip install -e . --upgrade
sudo systemctl restart parrot_forwarder
```

## Dashboard

Browse to `http://<host>:8080/` on the same LAN. The dashboard is localhost-only
by default (`supervisor.http.bind: 127.0.0.1` in `config.yaml`). If you need
remote access, SSH-tunnel the port rather than binding `0.0.0.0`:

```bash
ssh -L 8080:localhost:8080 pf@host
```

## Quick diagnostic flow

```bash
# 1. Is it running?
systemctl status parrot_forwarder

# 2. What does it think it is doing?
curl -sf http://localhost:8080/status | jq

# 3. What has happened recently?
sudo journalctl -u parrot_forwarder -n 200 --no-pager

# 4. Is the drone reachable?
ping -c 3 192.168.53.1

# 5. Is GStreamer happy?
gst-inspect-1.0 mpegtsmux srtsink | head

# 6. Is the SRT output listening?
sudo ss -lpn | grep 8890
```

## Common faults

| Symptom | Likely cause | Fix |
|---|---|---|
| `state: DISCONNECTED`, many restarts | Skycontroller USB flapping | reseat cable; check `dmesg \| grep usb` |
| `state: DEGRADED`, signal=fps | video pipeline stalled | restart via `POST /control/reset`; if persists, `sudo journalctl -u parrot_forwarder \| grep pipeline.error` |
| `state: STREAMING` but no video at client | network / firewall | `ufw allow 8890`; verify SRT locally: `ffplay srt://localhost:8890` |
| Dashboard blank / 404 | wrong port | confirm `supervisor.http.port` in `config.yaml` and `ss -lpn \| grep 8080` |
| `protobuf 4.x` error | env corruption | re-run `./scripts/install.sh` - it force-reinstalls `protobuf==3.20.3` |

## Metrics

Prometheus scrape target: `http://localhost:8080/metrics`.
Grafana dashboard JSON shipping in a follow-up; the metric set is documented
in [v2/architecture/state-machine.md#metrics-exported](../v2/architecture/state-machine.md#metrics-exported).

## REST / WS contract

Canonical source: [v2/architecture/api-contract.md](../v2/architecture/api-contract.md). The
OpenAPI document is generated from the running supervisor at `/openapi.json`.
