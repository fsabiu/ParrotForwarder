# ParrotForwarder v2 - Operator Runbook

Practical, paste-able procedures for installing, upgrading, rolling back, and
troubleshooting the v2 service. If you are reading this during an incident:
skip to [Quick diagnostic flow](#quick-diagnostic-flow).

## Target host

- Ubuntu 24.04 LTS ARM64.
- Any sudo-capable account used to install and operate the service.
- Parrot Anafi + Skycontroller 3.
- Control path can be either:
  - direct USB/RNDIS from the Linux host to the controller/drone (`192.168.53.1`), or
  - controller-over-LAN cable mode, where `drone.ip` is the SkyController's LAN IP and `drone.device_kind: skycontroller`.

## Install (cold)

```bash
git clone https://github.com/fsabiu/ParrotForwarder.git
cd ParrotForwarder
./scripts/install.sh            # idempotent - safe to re-run
source .venv/bin/activate
parrot-forwarder-supervisor --help
```

Environment overrides for the installer:
- `PF_SKIP_APT=1`   - skip apt packages (already provisioned).
- `PF_SKIP_PYENV=1` - use system `python3.11`.

## Run under systemd

The v1 unit file at `parrot_forwarder.service` still works for v2; update the
`ExecStart` line to point at the new venv:

```ini
[Service]
ExecStart=/home/pf/ParrotForwarder/.venv/bin/parrot-forwarder-supervisor --config /etc/parrot-forwarder/config.yaml
```

Reload and start:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now parrot_forwarder
sudo journalctl -u parrot_forwarder -f
```

Logs are rotating JSON at the path in `config.yaml` (`/var/log/parrot-forwarder/forwarder.log`). `journalctl` also captures stdout for the last service run.

## Run in Docker

This is the preferred path when you want the service reachable directly on the
machine's LAN IP instead of a host-local tunnel or VM port-forward.

```bash
cd ParrotForwarder
docker compose up -d --build
docker compose ps
```

Compose uses:
- `network_mode: host` so SRT and the dashboard bind directly on the Linux host.
- `build.network: host` so `docker compose up -d --build` reuses the Linux host resolver during image builds. This avoids bridge-network DNS failures on guests that use VPN-managed resolvers such as Tailscale MagicDNS.
- The image itself prefers IPv4 for `apt` and `pip` downloads. This avoids rebuild stalls on guests whose resolver advertises IPv6 answers but whose outbound IPv6 path is not actually usable.
- `PARROT_FORWARDER_SUPERVISOR__HTTP__BIND=0.0.0.0` so the dashboard is reachable at `http://<machine-ip>:8080/`.
- `PARROT_FORWARDER_SUPERVISOR__BACKOFF__BASE_SECONDS=1`, `MAX_SECONDS=1`, and `JITTER_SECONDS=0` so a power-cycled drone is retried every second instead of backing off for longer intervals.
- `/dev/bus/usb` passthrough for the Skycontroller 3.
- `./recordings:/recordings` so recordings are written to the host at `ParrotForwarder/recordings/`.
- `restart: unless-stopped` so the container survives reboots and crashes.

LAN endpoints:
- Dashboard: `http://<machine-ip>:8080/`
- SRT output: `srt://<machine-ip>:8890`
- Because Docker uses host networking here, there is no separate `ports:` section; services bind directly on the Linux machine running Docker.
- Example hostname form: `http://parrot-forwarder-vm:8080/`
- If you publish the dashboard behind port 80 with DNS or a reverse proxy, the same host can also appear as `http://parrot-forwarder-vm/`.

Recording files:
- On the Linux machine running Docker, find them under `ParrotForwarder/recordings/`.
- Inside the container, the same directory is `/recordings`.
- Active and finalized recordings are organized by date, typically `recordings/YYYY-MM-DD/default/<file>.ts`.
- Deleted recordings are moved under `recordings/.trash/<recording-id>/`.
- If Docker is running inside a VM, this path is inside the guest by default. It does not appear automatically on the macOS host unless you also configure a VM shared folder or another host/guest file-sharing mechanism.

Startup behavior:
- After the first successful `docker compose up -d`, the container will restart automatically after a guest reboot because the service uses `restart: unless-stopped`.
- This depends on the Docker daemon starting on boot. Verify or enable it with `sudo systemctl enable --now docker`.
- If you remove the container with `docker compose down`, there is nothing left for Docker to restart on the next boot. Run `docker compose up -d` again after that.

Finding the dashboard address:

```bash
hostname -I
ip -brief addr
```

Use the guest's LAN address in the browser:

```text
http://<machine-ip>:8080/
```

The IP usually stays the same only as long as your DHCP lease and network
topology stay the same. If you need a stable URL across reboots, create a DHCP
reservation on the router or configure a static IP in the guest.

### Virtualized hosts

For a VM deployment, keep the instructions generic:

- Use a bridged network adapter if operators should reach the dashboard directly from the LAN.
- Enable USB passthrough for the Skycontroller before starting the container.
- The guest's LAN IP carries both the dashboard on `8080/tcp` and the SRT stream on `8890/udp`.
- On VirtualBox specifically, enable the USB controller for the guest and attach the Skycontroller device to the VM; exact host adapter names and local usernames are machine-specific and should not be committed.
- After boot, verify the guest sees the controller with `lsusb` and verify the dashboard with `curl http://<machine-ip>:8080/health`.
- If the guest firewall is enabled, allow `8080/tcp` and `8890/udp` before testing from other hosts.

If you want a host-managed config instead of the image default, uncomment the
config bind mount in `docker-compose.yml`.

For controller-over-LAN cable mode, mount a config with:

```yaml
drone:
  ip: "192.168.1.136"          # controller LAN IP
  video_ip: null               # or set explicitly if RTSP is on a different IP
  device_kind: "skycontroller"
```

If the controller IP responds to ping but refuses Parrot control/video ports,
the cable adapter chain is not exposing a usable SDK endpoint yet. In that
case the service should sit in `DISCONNECTED` or `READY`, not fake `STREAMING`.

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

Bare metal / systemd default: the dashboard is localhost-only
(`supervisor.http.bind: 127.0.0.1` in `config.yaml`), so expose it deliberately
before opening it to a LAN.

Docker compose default: browse directly to `http://<machine-ip>:8080/` on the
same trusted LAN/VPN because compose overrides the bind address to `0.0.0.0`.

Docker compose also exposes the transport stream on `srt://<machine-ip>:8890`
to the same LAN/VPN because the SRT listener is bound on the Linux host
network namespace.

Examples:
- Direct IP: `http://192.168.1.134:8080/`
- Hostname alias: `http://parrot-forwarder-vm:8080/`
- Bare hostname only: `http://parrot-forwarder-vm/` if you front the dashboard with port 80.

## Quick diagnostic flow

```bash
# 1. Is it running?
systemctl status parrot_forwarder
# or, if containerized:
docker compose ps

# 2. What does it think it is doing?
curl -sf http://localhost:8080/status | jq

# 3. What has happened recently?
sudo journalctl -u parrot_forwarder -n 200 --no-pager
# or, if containerized:
docker compose logs --tail=200 parrot-forwarder

# 4. Is the drone reachable?
ping -c 3 192.168.53.1
# or, for controller-over-LAN:
ping -c 3 <controller-ip>

# 5. Is GStreamer happy?
gst-inspect-1.0 mpegtsmux srtsink | head

# 6. Is the SRT output listening?
sudo ss -lpn | grep 8890

# 7. Can another host read it?
ffplay -fflags nobuffer -flags low_delay 'srt://<machine-ip>:8890'
```

## Common faults

| Symptom | Likely cause | Fix |
|---|---|---|
| `state: DISCONNECTED`, many restarts | Skycontroller USB flapping | reseat cable; check `dmesg \| grep usb` |
| `state: READY`, telemetry present, no preview | control link is up but RTSP not live yet | check drone/camera state; if using controller-over-LAN, verify the controller actually exposes Parrot ports on its LAN IP |
| `POST /control/start` returns 409 | worker backend disabled on this host | use Linux + Olympe + GStreamer, or run the Docker compose deployment on the target machine |
| `state: DEGRADED`, signal=fps | video pipeline stalled | restart via `POST /control/reset`; if persists, `sudo journalctl -u parrot_forwarder \| grep pipeline.error` |
| `state: STREAMING` but no video at client | network / firewall | `ufw allow 8890`; verify SRT locally: `ffplay -fflags nobuffer -flags low_delay 'srt://localhost:8890'` |
| controller LAN IP pings but ports `180/554/44444-44447` are refused | incompatible USB-Ethernet adapter / dock path | replace the adapter chain; keep the Mac out of the USB path and use a known-good controller Ethernet path |
| Dashboard blank / 404 | wrong port | confirm `supervisor.http.port` in `config.yaml` and `ss -lpn \| grep 8080` |
| `protobuf 4.x` error | env corruption | re-run `./scripts/install.sh` - it force-reinstalls `protobuf==3.20.3` |

## Metrics

Prometheus scrape target: `http://localhost:8080/metrics`.
Grafana dashboard JSON shipping in a follow-up; the metric set is documented
in [v2/architecture/state-machine.md#metrics-exported](../v2/architecture/state-machine.md#metrics-exported).

## REST / WS contract

Canonical source: [v2/architecture/api-contract.md](../v2/architecture/api-contract.md). The
OpenAPI document is generated from the running supervisor at `/openapi.json`.
