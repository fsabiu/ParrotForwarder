// ParrotForwarder v2 dashboard - minimal vanilla JS.
// Consumes REST + WebSocket contract from v2/architecture/api-contract.md.
// A Svelte rewrite is tracked per ADR-003.

const state = {
  startedAt: null,
};

const el = (id) => document.getElementById(id);

function clearTelemetry() {
  el("battery").textContent = "-";
  el("gps").textContent = "-";
  el("rssi").textContent = "-";
  el("fps").textContent = "-";
}

function setState(name) {
  const badge = el("state-badge");
  badge.textContent = name;
  badge.className = `state state-${name.toLowerCase()}`;
  if (name === "STREAMING" && !state.startedAt) {
    state.startedAt = Date.now();
  }
  if (!["STREAMING", "DEGRADED"].includes(name)) {
    state.startedAt = null;
    el("uptime").textContent = "-";
  }
  if (["DISCONNECTED", "CONNECTING", "RESTARTING"].includes(name)) {
    clearTelemetry();
  }
}

async function refreshStatus() {
  try {
    const response = await fetch("/status");
    if (!response.ok) return;
    const body = await response.json();
    setState(body.state);
    el("restarts").textContent = body.restarts_total ?? 0;
    el("failures").textContent = body.consecutive_failures ?? 0;
  } catch (err) {
    console.warn("status fetch failed", err);
  }
}

function tickUptime() {
  if (!state.startedAt) return;
  const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  el("uptime").textContent = `${h}h${m}m${s}s`;
}

function wsUrl(path) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${path}`;
}

function connectEventStream() {
  const ws = new WebSocket(wsUrl("/stream/events"));
  ws.addEventListener("message", (evt) => {
    try {
      const msg = JSON.parse(evt.data);
      handleEvent(msg);
    } catch (err) {
      console.warn("bad event frame", err, evt.data);
    }
  });
  ws.addEventListener("close", () => {
    appendLog("[info] event stream closed; reconnecting in 2 s");
    setTimeout(connectEventStream, 2000);
  });
}

function connectTelemetryStream() {
  const ws = new WebSocket(wsUrl("/stream/telemetry?rate=2"));
  ws.addEventListener("message", (evt) => {
    try {
      const payload = JSON.parse(evt.data);
      if (payload.payload) {
        const p = payload.payload;
        if ("battery_percent" in p) el("battery").textContent = `${p.battery_percent}%`;
        if ("gps_fix" in p) el("gps").textContent = p.gps_fix ? "yes" : "no";
        if ("rssi_dbm" in p) el("rssi").textContent = `${p.rssi_dbm} dBm`;
        if ("fps" in p) el("fps").textContent = `${p.fps.toFixed(1)}`;
      }
    } catch (err) {
      console.warn("bad telemetry frame", err);
    }
  });
  ws.addEventListener("close", () => setTimeout(connectTelemetryStream, 2000));
}

function handleEvent(msg) {
  if (msg.type === "state") {
    setState(msg.to);
    appendLog(`[state] ${msg.from} -> ${msg.to} (${msg.reason})`);
  } else if (msg.type === "restart") {
    appendLog(`[restart] #${msg.count} reason=${msg.reason}`);
  } else if (msg.type === "log") {
    appendLog(`[${msg.level}] ${msg.message}`);
  }
}

function appendLog(line) {
  const ol = el("event-log");
  const li = document.createElement("li");
  li.textContent = line;
  ol.prepend(li);
  while (ol.children.length > 100) {
    ol.removeChild(ol.lastChild);
  }
}

async function postControl(endpoint, body) {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) {
    const problem = await response.json().catch(() => ({}));
    appendLog(`[error] ${endpoint} failed: ${problem.title || response.statusText}`);
    return;
  }
  const body_ = await response.json();
  appendLog(`[control] ${endpoint} -> state=${body_.state ?? "?"}`);
}

el("btn-start").addEventListener("click", () => postControl("/control/start"));
el("btn-stop").addEventListener("click", () => postControl("/control/stop"));
el("btn-reset").addEventListener("click", () =>
  postControl("/control/reset", { reason: "dashboard" })
);

refreshStatus();
connectEventStream();
connectTelemetryStream();
setInterval(tickUptime, 1000);
setInterval(refreshStatus, 5000);
