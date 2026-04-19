// ParrotForwarder v2 dashboard.
// Vanilla JS only; no build step.

const state = {
  startedAt: null,
  lastTelemetryAt: null,
  serviceState: "DISCONNECTED",
  previewAvailable: false,
  telemetryStale: true,
};

const DASHBOARD_THEME_KEY = "parrotForwarder.theme";
const DASHBOARD_THEMES = new Set(["dark", "light", "sun"]);
const STREAM_RECONNECT_DELAY_MS = 1000;
const STATUS_REFRESH_INTERVAL_MS = 1000;
const TELEMETRY_STALE_AFTER_MS = 3000;
const DESKTOP_LAYOUT_MEDIA_QUERY = "(min-width: 1101px)";

let previewController = null;
let telemetryLayoutObserver = null;

const TELEMETRY_FIELDS = [
  "battery",
  "gps",
  "position-valid",
  "satellites",
  "rssi",
  "fps",
  "last-telemetry",
  "position-source",
  "position-message",
  "position-coords",
  "position-altitudes",
  "position-accuracy",
  "home-coords",
  "klv-coords",
  "gimbal-abs",
  "gimbal-rel",
  "gimbal-offsets",
  "gimbal-frames",
  "gimbal-offset-bounds",
  "camera-optics",
  "camera-recording",
  "camera-alignment",
  "camera-alignment-bounds",
  "flying-state",
  "alert-state",
  "return-home",
  "heading-lock",
  "wind",
  "vibration",
  "hovering-warning",
  "product-info",
  "flight-hours",
  "storage-info",
];

const el = (id) => document.getElementById(id);

function storageGet(key) {
  try {
    return localStorage.getItem(key);
  } catch (err) {
    return null;
  }
}

function storageSet(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (err) {
    // Ignore storage failures (private mode / policy lock-down).
  }
}

function updateThemeButtons(theme) {
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    const active = button.dataset.themeChoice === theme;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function applyTheme(theme) {
  const nextTheme = DASHBOARD_THEMES.has(theme) ? theme : "dark";
  document.documentElement.dataset.theme = nextTheme;
  document.documentElement.style.colorScheme = nextTheme === "dark" ? "dark" : "light";
  updateThemeButtons(nextTheme);
  storageSet(DASHBOARD_THEME_KEY, nextTheme);
}

function restoreTheme() {
  applyTheme(storageGet(DASHBOARD_THEME_KEY) || "dark");
}

function wireThemeToggle() {
  document.querySelectorAll("[data-theme-choice]").forEach((button) => {
    button.addEventListener("click", () => applyTheme(button.dataset.themeChoice));
  });
}

function setField(id, value = "-") {
  const node = el(id);
  if (node) node.textContent = value;
}

function syncTelemetryJsonHeight() {
  const rawPanel = document.querySelector(".raw");
  const previewFrame = document.querySelector(".preview-frame");
  const pre = el("telemetry-json");
  if (!rawPanel || !previewFrame || !pre) return;

  pre.style.removeProperty("height");
  pre.style.removeProperty("max-height");

  if (!window.matchMedia(DESKTOP_LAYOUT_MEDIA_QUERY).matches) {
    return;
  }

  const targetPreHeight = Math.max(240, Math.floor(previewFrame.getBoundingClientRect().height));

  pre.style.height = `${targetPreHeight}px`;
  pre.style.maxHeight = `${targetPreHeight}px`;
}

function wireTelemetryJsonHeight() {
  const previewFrame = document.querySelector(".preview-frame");
  if (!previewFrame) return;
  syncTelemetryJsonHeight();
  telemetryLayoutObserver?.disconnect();
  telemetryLayoutObserver = new ResizeObserver(() => syncTelemetryJsonHeight());
  telemetryLayoutObserver.observe(previewFrame);
  window.addEventListener("resize", syncTelemetryJsonHeight);
}

function syncPreviewState() {
  const frame = el("preview-frame");
  const status = el("preview-status");
  if (!frame) return;
  frame.classList.toggle("has-video", state.previewAvailable);
  if (status) {
    status.textContent = state.previewAvailable ? "" : previewMessageForState(state.serviceState);
  }
}

function previewMessageForState(name) {
  if (name === "CONNECTING") return "Connecting to drone";
  if (name === "RESTARTING") return "Reconnecting to drone";
  if (name === "DISCONNECTED") return "Drone disconnected";
  if (name === "DEGRADED") return "Video reconnecting";
  return "Waiting for live video";
}

function previewStateActive(name) {
  return ["READY", "STREAMING", "DEGRADED"].includes(name);
}

function updatePreviewFullscreenButton() {
  const button = el("btn-preview-fullscreen");
  const frame = el("preview-frame");
  if (!button || !frame) return;
  const fullscreen = document.fullscreenElement === frame;
  button.textContent = fullscreen ? "Exit full screen" : "Full screen";
  button.setAttribute("aria-pressed", fullscreen ? "true" : "false");
}

function clearTelemetry() {
  for (const id of TELEMETRY_FIELDS) {
    setField(id, "-");
  }
  setField("telemetry-json", "");
  state.lastTelemetryAt = null;
  syncTelemetryJsonHeight();
}

function markTelemetryStale() {
  if (state.telemetryStale) return;
  state.telemetryStale = true;
  clearTelemetry();
  previewController?.stop();
  state.previewAvailable = false;
  syncPreviewState();
}

function setState(name) {
  const badge = el("state-badge");
  const wasPreviewActive = previewStateActive(state.serviceState);
  const isPreviewActive = previewStateActive(name);
  state.serviceState = name;
  badge.textContent = name;
  badge.className = `state state-${name.toLowerCase()}`;
  if (name === "STREAMING" && !state.startedAt) {
    state.startedAt = Date.now();
  }
  if (!isPreviewActive) {
    state.startedAt = null;
    setField("uptime", "-");
  }
  if (!["STREAMING", "DEGRADED", "READY"].includes(name)) {
    state.telemetryStale = true;
    clearTelemetry();
  }
  if (previewController) {
    if (isPreviewActive && !wasPreviewActive) {
      previewController.start();
    } else if (!isPreviewActive && wasPreviewActive) {
      previewController.stop();
    } else if (isPreviewActive && !el("preview")?.getAttribute("src")) {
      previewController.start();
    }
  }
  if (!isPreviewActive) {
    state.previewAvailable = false;
  }
  syncPreviewState();
}

function isNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function fmtNumber(value, digits = 1, suffix = "") {
  return isNumber(value) ? `${value.toFixed(digits)}${suffix}` : "-";
}

function fmtInteger(value, suffix = "") {
  return isNumber(value) ? `${Math.round(value)}${suffix}` : "-";
}

function fmtBool(value) {
  return value === true ? "yes" : value === false ? "no" : "-";
}

function fmtCoords(latitude, longitude, digits = 4) {
  if (!isNumber(latitude) || !isNumber(longitude)) return "-";
  return `${latitude.toFixed(digits)}, ${longitude.toFixed(digits)}`;
}

function fmtAltitudes(position = {}) {
  const parts = [];
  if (isNumber(position.altitude_msl_m)) parts.push(`MSL ${position.altitude_msl_m.toFixed(1)} m`);
  if (isNumber(position.altitude_agl_m)) parts.push(`AGL ${position.altitude_agl_m.toFixed(1)} m`);
  if (isNumber(position.altitude_relative_takeoff_m)) {
    parts.push(`takeoff ${position.altitude_relative_takeoff_m.toFixed(1)} m`);
  }
  if (isNumber(position.ground_altitude_msl_m)) {
    parts.push(`ground MSL ${position.ground_altitude_msl_m.toFixed(1)} m`);
  }
  return parts.length ? parts.join(" | ") : "-";
}

function fmtAccuracy(position = {}) {
  const accuracy = position.accuracy_m || {};
  const parts = [];
  if (isNumber(accuracy.latitude)) parts.push(`lat ${accuracy.latitude.toFixed(1)} m`);
  if (isNumber(accuracy.longitude)) parts.push(`lon ${accuracy.longitude.toFixed(1)} m`);
  if (isNumber(accuracy.altitude)) parts.push(`alt ${accuracy.altitude.toFixed(1)} m`);
  return parts.length ? parts.join(" | ") : "-";
}

function fmtAxisTriplet(values, digits = 1) {
  if (!values || typeof values !== "object") return "-";
  const parts = [];
  if (isNumber(values.yaw)) parts.push(`yaw ${values.yaw.toFixed(digits)}°`);
  if (isNumber(values.pitch)) parts.push(`pitch ${values.pitch.toFixed(digits)}°`);
  if (isNumber(values.roll)) parts.push(`roll ${values.roll.toFixed(digits)}°`);
  return parts.length ? parts.join(" | ") : "-";
}

function fmtAxisBounds(bounds, digits = 1) {
  if (!bounds || typeof bounds !== "object") return "-";
  const parts = [];
  for (const axis of ["yaw", "pitch", "roll"]) {
    const axisBounds = bounds[axis];
    if (axisBounds && isNumber(axisBounds.min) && isNumber(axisBounds.max)) {
      parts.push(`${axis} ${axisBounds.min.toFixed(digits)}..${axisBounds.max.toFixed(digits)}°`);
    }
  }
  return parts.length ? parts.join(" | ") : "-";
}

function fmtKlvCoords(position = {}) {
  const klv = position.klv || {};
  if (!isNumber(klv.latitude) || !isNumber(klv.longitude)) return "-";
  const altitude = isNumber(klv.altitude_msl_m) ? ` @ ${klv.altitude_msl_m.toFixed(1)} m` : "";
  return `${klv.latitude.toFixed(4)}, ${klv.longitude.toFixed(4)}${altitude}`;
}

function fmtRecording(camera = {}) {
  const recording = camera.recording || {};
  const parts = [];
  if (recording.state) parts.push(`${recording.state}`);
  if (recording.available) parts.push(`available=${recording.available}`);
  if (recording.start_time) parts.push(`since ${recording.start_time}`);
  return parts.length ? parts.join(" | ") : "-";
}

function fmtProductInfo(system = {}) {
  const parts = [];
  if (system.product_name) parts.push(system.product_name);
  if (system.software_version) parts.push(`SW ${system.software_version}`);
  if (system.hardware_version) parts.push(`HW ${system.hardware_version}`);
  return parts.length ? parts.join(" | ") : "-";
}

function fmtMotorFlights(system = {}) {
  const flights = system.motor_flights || {};
  const parts = [];
  if (isNumber(flights.total_flights)) parts.push(`${Math.round(flights.total_flights)} flights`);
  if (isNumber(flights.last_flight_duration_s)) {
    parts.push(`last ${Math.round(flights.last_flight_duration_s)} s`);
  }
  if (isNumber(flights.total_flight_duration_s)) {
    parts.push(`total ${Math.round(flights.total_flight_duration_s)} s`);
  }
  return parts.length ? parts.join(" | ") : "-";
}

function fmtStorage(storage = {}) {
  const parts = [];
  if (isNumber(storage.free_space_mb)) parts.push(`${Math.round(storage.free_space_mb)} MB free`);
  if (isNumber(storage.recording_time_remaining_min)) {
    parts.push(`${Math.round(storage.recording_time_remaining_min)} min rec`);
  }
  if (isNumber(storage.photo_remaining)) {
    parts.push(`${Math.round(storage.photo_remaining)} photos`);
  }
  return parts.length ? parts.join(" | ") : "-";
}

function fmtReturnHome(flight = {}) {
  const rth = flight.return_home || {};
  const parts = [];
  if (rth.state) parts.push(`${rth.state}`);
  if (rth.reason) parts.push(`reason=${rth.reason}`);
  if (isNumber(rth.min_altitude_m)) parts.push(`min ${rth.min_altitude_m.toFixed(1)} m`);
  return parts.length ? parts.join(" | ") : "-";
}

function fmtHoveringWarning(flight = {}) {
  const warning = flight.hovering_warning || {};
  const parts = [];
  if (warning.no_gps_too_dark) parts.push("no GPS: too dark");
  if (warning.no_gps_too_high) parts.push("no GPS: too high");
  return parts.length ? parts.join(" | ") : "none";
}

function hasDisplayablePosition(payload, position = {}) {
  if (payload.position_valid !== true) return false;
  if (position.valid === false) return false;
  return position.source !== "default" && position.is_default !== true;
}

function sanitizedTelemetryForDisplay(payload) {
  const clone = JSON.parse(JSON.stringify(payload));
  const position = clone.position || {};
  if (!hasDisplayablePosition(clone, position)) {
    delete clone.position;
    if (clone.raw && typeof clone.raw === "object") {
      for (const key of [
        "altitude",
        "altitude_agl",
        "altitude_relative_takeoff_m",
        "altitude_takeoff_m",
        "gps_location_altitude_msl_raw",
        "gps_location_latitude_raw",
        "gps_location_longitude_raw",
        "ground_altitude_msl",
        "home_altitude_msl",
        "home_latitude",
        "home_longitude",
        "latitude",
        "longitude",
        "platform_altitude_msl",
        "position_altitude_accuracy_m",
        "position_altitude_msl",
        "position_changed_altitude_msl_raw",
        "position_changed_latitude_raw",
        "position_changed_longitude_raw",
        "position_is_default",
        "position_latitude",
        "position_latitude_accuracy_m",
        "position_longitude",
        "position_longitude_accuracy_m",
        "position_message",
        "position_source",
        "position_valid",
      ]) {
        delete clone.raw[key];
      }
      if (Object.keys(clone.raw).length === 0) {
        delete clone.raw;
      }
    }
  }
  return clone;
}

async function refreshStatus() {
  try {
    const response = await fetch("/status", { cache: "no-store" });
    if (!response.ok) return;
    const body = await response.json();
    setState(body.state);
    setField("restarts", body.restarts_total ?? 0);
    setField("failures", body.consecutive_failures ?? 0);
  } catch (err) {
    console.warn("status fetch failed", err);
  }
}

function tickTimers() {
  if (state.startedAt) {
    const seconds = Math.floor((Date.now() - state.startedAt) / 1000);
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = seconds % 60;
    setField("uptime", `${h}h${m}m${s}s`);
  }
  if (state.lastTelemetryAt) {
    const ageMs = Date.now() - state.lastTelemetryAt;
    if (ageMs > TELEMETRY_STALE_AFTER_MS) {
      markTelemetryStale();
      return;
    }
    const seconds = Math.floor(ageMs / 1000);
    setField("last-telemetry", `${seconds}s ago`);
  }
}

function wsUrl(path) {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${proto}://${window.location.host}${path}`;
}

function setPreviewAvailable(value) {
  state.previewAvailable = value;
  syncPreviewState();
}

function wirePreviewState() {
  const preview = el("preview");
  const frame = el("preview-frame");
  const button = el("btn-preview-fullscreen");
  if (!preview || !frame) return;

  const previewUrl = () => `/preview/stream.mjpg?ts=${Date.now()}`;
  const RETRY_DELAY_MS = 1500;
  let retryTimer = null;

  const start = () => {
    clearTimeout(retryTimer);
    if (preview.getAttribute("src")) return;
    setPreviewAvailable(false);
    preview.src = previewUrl();
  };

  const stop = () => {
    clearTimeout(retryTimer);
    preview.removeAttribute("src");
    setPreviewAvailable(false);
  };

  preview.addEventListener("load", () => {
    setPreviewAvailable(true);
  });
  preview.addEventListener("error", () => {
    setPreviewAvailable(false);
    if (!previewStateActive(state.serviceState)) return;
    retryTimer = setTimeout(start, RETRY_DELAY_MS);
  });

  previewController = { start, stop };
  if (previewStateActive(state.serviceState)) {
    start();
  }

  const toggleFullscreen = async () => {
    if (!document.fullscreenEnabled) return;
    try {
      if (document.fullscreenElement === frame) {
        await document.exitFullscreen();
      } else {
        await frame.requestFullscreen();
      }
    } catch (err) {
      console.warn("fullscreen toggle failed", err);
    } finally {
      updatePreviewFullscreenButton();
    }
  };

  button?.addEventListener("click", toggleFullscreen);
  frame.addEventListener("dblclick", toggleFullscreen);
  document.addEventListener("fullscreenchange", updatePreviewFullscreenButton);
  updatePreviewFullscreenButton();
}

function connectEventStream() {
  const ws = new WebSocket(wsUrl("/stream/events"));
  ws.addEventListener("message", (evt) => {
    try {
      handleEvent(JSON.parse(evt.data));
    } catch (err) {
      console.warn("bad event frame", err, evt.data);
    }
  });
  ws.addEventListener("close", () => {
    appendLog("[info] event stream closed; reconnecting in 1 s");
    setTimeout(connectEventStream, STREAM_RECONNECT_DELAY_MS);
  });
}

function renderTelemetry(payload, sampleTime) {
  const position = payload.position || {};
  const gimbal = payload.gimbal || {};
  const camera = payload.camera || {};
  const flight = payload.flight || {};
  const system = payload.system || {};
  const storage = payload.storage || {};
  const showPosition = hasDisplayablePosition(payload, position);

  if (!showPosition) {
    state.telemetryStale = true;
    clearTelemetry();
    return;
  }

  const displayPayload = sanitizedTelemetryForDisplay(payload);

  state.lastTelemetryAt = Date.now();
  state.telemetryStale = false;
  setField("battery", isNumber(payload.battery_percent) ? `${payload.battery_percent}%` : "-");
  setField("gps", fmtBool(payload.gps_fix));
  setField("position-valid", fmtBool(payload.position_valid));
  setField("satellites", fmtInteger(position.satellites));
  setField("rssi", isNumber(payload.rssi_dbm) ? `${payload.rssi_dbm} dBm` : "-");
  setField("fps", isNumber(payload.fps) ? payload.fps.toFixed(1) : "-");
  // "last-telemetry" is driven by tickTimers() as a relative "Ns ago" value;
  // don't overwrite with the raw ISO timestamp here (caused a 1 Hz flicker
  // between the timestamp and "0s ago").

  setField("position-source", position.source || "-");
  setField("position-message", position.message || "-");
  setField("position-coords", fmtCoords(position.latitude, position.longitude, 4));
  setField("position-altitudes", fmtAltitudes(position));
  setField("position-accuracy", fmtAccuracy(position));
  setField("home-coords", fmtCoords(position.home?.latitude, position.home?.longitude, 4));
  setField("klv-coords", fmtKlvCoords(position));

  setField("gimbal-abs", fmtAxisTriplet(gimbal.absolute_deg, 2));
  setField("gimbal-rel", fmtAxisTriplet(gimbal.relative_deg, 2));
  setField("gimbal-offsets", fmtAxisTriplet(gimbal.offset_deg, 2));
  setField(
    "gimbal-frames",
    [
      gimbal.yaw_frame_of_reference && `yaw=${gimbal.yaw_frame_of_reference}`,
      gimbal.pitch_frame_of_reference && `pitch=${gimbal.pitch_frame_of_reference}`,
      gimbal.roll_frame_of_reference && `roll=${gimbal.roll_frame_of_reference}`,
      gimbal.offset_update_state && `offset=${gimbal.offset_update_state}`,
    ]
      .filter(Boolean)
      .join(" | ") || "-"
  );
  setField("gimbal-offset-bounds", fmtAxisBounds(gimbal.offset_bounds_deg));

  setField(
    "camera-optics",
    [
      isNumber(camera.zoom_level) ? `zoom ${camera.zoom_level.toFixed(2)}x` : null,
      isNumber(camera.focal_length_mm) ? `f ${camera.focal_length_mm.toFixed(1)} mm` : null,
      isNumber(camera.h_fov_deg) ? `HFOV ${camera.h_fov_deg.toFixed(1)}°` : null,
      isNumber(camera.v_fov_deg) ? `VFOV ${camera.v_fov_deg.toFixed(1)}°` : null,
      isNumber(camera.sensor_width_mm) && isNumber(camera.sensor_height_mm)
        ? `${camera.sensor_width_mm.toFixed(1)}x${camera.sensor_height_mm.toFixed(1)} mm`
        : null,
    ]
      .filter(Boolean)
      .join(" | ") || "-"
  );
  setField("camera-recording", fmtRecording(camera));
  setField("camera-alignment", fmtAxisTriplet(camera.alignment_deg, 2));
  setField("camera-alignment-bounds", fmtAxisBounds(camera.alignment_bounds_deg));

  setField("flying-state", flight.state || "-");
  setField("alert-state", flight.alert_state || "-");
  setField("return-home", fmtReturnHome(flight));
  setField("heading-lock", flight.heading_locked_state || "-");
  setField("wind", flight.wind_state || "-");
  setField("vibration", flight.vibration_level || "-");
  setField("hovering-warning", fmtHoveringWarning(flight));

  setField("product-info", fmtProductInfo(system));
  setField("flight-hours", fmtMotorFlights(system));
  setField("storage-info", fmtStorage(storage));
  setField("telemetry-json", JSON.stringify(displayPayload, null, 2));
  syncTelemetryJsonHeight();
}

function connectTelemetryStream() {
  const ws = new WebSocket(wsUrl("/stream/telemetry?rate=2"));
  ws.addEventListener("message", (evt) => {
    try {
      const frame = JSON.parse(evt.data);
      if (frame.payload) {
        renderTelemetry(frame.payload, frame.t);
      }
    } catch (err) {
      console.warn("bad telemetry frame", err, evt.data);
    }
  });
  ws.addEventListener("close", () => {
    appendLog("[info] telemetry stream closed; reconnecting in 1 s");
    state.telemetryStale = true;
    clearTelemetry();
    previewController?.stop();
    setTimeout(connectTelemetryStream, STREAM_RECONNECT_DELAY_MS);
  });
}

function handleEvent(msg) {
  if (msg.type === "state") {
    setState(msg.to);
    appendLog(`[state] ${msg.from} -> ${msg.to} (${msg.reason})`);
  } else if (msg.type === "restart") {
    appendLog(`[restart] #${msg.count} reason=${msg.reason}`);
  } else if (msg.type === "log") {
    appendLog(`[${msg.level}] ${msg.message}`);
  } else if (msg.type === "recording.started") {
    const id = msg.payload?.recording_id?.slice(0, 8) ?? "?";
    appendLog(`[rec] started ${id}`);
    refreshRecStatus();
  } else if (msg.type === "recording.stopped") {
    const id = msg.payload?.recording_id?.slice(0, 8) ?? "?";
    appendLog(`[rec] stopped ${id}`);
    refreshRecStatus();
    refreshRecList();
    refreshRecDisk();
  } else if (msg.type === "recording.error") {
    const id = msg.payload?.recording_id?.slice(0, 8) ?? "?";
    appendLog(`[rec] error ${id}: ${msg.payload?.reason ?? "(no detail)"}`);
    refreshRecStatus();
    refreshRecList();
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

async function handleRestart() {
  const endpoint = state.serviceState === "DISCONNECTED" ? "/control/start" : "/control/reset";
  const body = endpoint === "/control/reset" ? { reason: "dashboard restart" } : undefined;
  await postControl(endpoint, body);
}

// ---------------------------------------------------------------------------
// Recording
// ---------------------------------------------------------------------------

const recState = {
  active: false,
  startedAt: null,
  bytes: 0,
};

const REC_INPUT_KEYS = {
  "rec-mission": "parrotForwarder.rec.mission",
  "rec-drone": "parrotForwarder.rec.drone",
  "rec-notes": "parrotForwarder.rec.notes",
};

function restoreRecInputs() {
  for (const [id, key] of Object.entries(REC_INPUT_KEYS)) {
    const node = el(id);
    if (!node) continue;
    const stored = storageGet(key);
    if (stored != null) node.value = stored;
    node.addEventListener("change", () => {
      storageSet(key, node.value);
    });
  }
}

function humanBytes(n) {
  if (n == null) return "-";
  if (n < 1024) return `${n} B`;
  const units = ["KiB", "MiB", "GiB", "TiB"];
  let v = n / 1024;
  let u = 0;
  while (v >= 1024 && u < units.length - 1) {
    v /= 1024;
    u += 1;
  }
  return `${v.toFixed(v >= 10 || u === 0 ? 0 : 1)} ${units[u]}`;
}

function humanDuration(s) {
  if (s == null) return "-";
  const sec = Math.floor(s);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const rs = sec % 60;
  if (h > 0) return `${h}:${String(m).padStart(2, "0")}:${String(rs).padStart(2, "0")}`;
  return `${m}:${String(rs).padStart(2, "0")}`;
}

function setRecIndicator(active) {
  const node = el("rec-indicator");
  if (!node) return;
  node.textContent = active ? "REC" : "off";
  node.className = `rec-indicator ${active ? "rec-on" : "rec-off"}`;
}

function setRecButtonsForState(active) {
  const btnStart = el("btn-rec-start");
  const btnStop = el("btn-rec-stop");
  if (btnStart) btnStart.disabled = active;
  if (btnStop) btnStop.disabled = !active;
}

async function refreshRecStatus() {
  try {
    const r = await fetch("/recording/status");
    if (!r.ok) return;
    const s = await r.json();
    recState.active = !!s.active;
    if (s.active) {
      recState.startedAt = Date.parse(s.started_at);
      recState.bytes = s.bytes || 0;
      setField("rec-status", `recording (id ${s.recording_id?.slice(0, 8) || "?"})`);
      setField("rec-elapsed", humanDuration(s.elapsed_s));
      setField("rec-bytes", humanBytes(s.bytes));
      setField("rec-file", s.path || "-");
    } else {
      recState.startedAt = null;
      recState.bytes = 0;
      setField("rec-status", "idle");
      setField("rec-elapsed", "-");
      setField("rec-bytes", "-");
      setField("rec-file", "-");
    }
    setRecIndicator(recState.active);
    setRecButtonsForState(recState.active);
  } catch (e) {
    // Network hiccup; leave state as-is.
  }
}

async function refreshRecDisk() {
  try {
    const r = await fetch("/recording/disk");
    if (!r.ok) return;
    const d = await r.json();
    setField("rec-disk-used", humanBytes(d.used_bytes));
    setField("rec-disk-total", humanBytes(d.total_bytes));
    setField("rec-disk-free", humanBytes(d.free_bytes));
    setField("rec-disk-count", d.count);
    const fill = el("rec-disk-bar-fill");
    if (fill && d.total_bytes > 0) {
      const pct = Math.min(100, (d.used_bytes / d.total_bytes) * 100);
      fill.style.width = `${pct}%`;
    }
  } catch (e) {
    // ignore
  }
}

async function refreshRecList() {
  try {
    const r = await fetch("/recording/list?limit=50");
    if (!r.ok) return;
    const rows = await r.json();
    const body = el("rec-list-body");
    if (!body) return;
    body.innerHTML = "";
    if (rows.length === 0) {
      const tr = document.createElement("tr");
      tr.className = "rec-list-empty";
      tr.innerHTML = '<td colspan="5">No recordings yet.</td>';
      body.appendChild(tr);
      return;
    }
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.dataset.id = row.id;
      const startCell = document.createElement("td");
      startCell.textContent = row.started_at;
      const durCell = document.createElement("td");
      durCell.textContent = humanDuration(row.duration_s);
      const sizeCell = document.createElement("td");
      sizeCell.textContent = humanBytes(row.bytes);
      const missionCell = document.createElement("td");
      missionCell.textContent = row.mission_id || "-";
      const actionsCell = document.createElement("td");
      const download = document.createElement("a");
      download.textContent = "Download";
      download.href = `/recording/${row.id}/download`;
      download.className = "small-link";
      download.target = "_blank";
      const delBtn = document.createElement("button");
      delBtn.textContent = "Delete";
      delBtn.className = "small danger";
      delBtn.addEventListener("click", () => handleRecDelete(row.id));
      actionsCell.append(download, " ", delBtn);
      tr.append(startCell, durCell, sizeCell, missionCell, actionsCell);
      if (row.state === "error") tr.classList.add("rec-row-error");
      body.appendChild(tr);
    }
  } catch (e) {
    // ignore
  }
}

async function handleRecStart() {
  const body = {
    mission_id: el("rec-mission")?.value || undefined,
    drone_id: el("rec-drone")?.value || undefined,
    notes: el("rec-notes")?.value || undefined,
  };
  try {
    const r = await fetch("/recording/start", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) {
      const p = await r.json().catch(() => ({}));
      appendLog(`[rec] start failed: ${p.title || r.statusText}`);
      return;
    }
    const data = await r.json();
    appendLog(`[rec] started ${data.recording_id?.slice(0, 8)} -> ${data.path}`);
    await refreshRecStatus();
    await refreshRecDisk();
  } catch (e) {
    appendLog(`[rec] start error: ${e.message}`);
  }
}

async function handleRecStop() {
  try {
    const r = await fetch("/recording/stop", { method: "POST" });
    if (!r.ok) {
      const p = await r.json().catch(() => ({}));
      appendLog(`[rec] stop failed: ${p.title || r.statusText}`);
      return;
    }
    const data = await r.json();
    appendLog(
      `[rec] stopped ${data.recording_id?.slice(0, 8)} duration=${humanDuration(
        data.duration_s
      )} size=${humanBytes(data.bytes)}`
    );
    await refreshRecStatus();
    await refreshRecList();
    await refreshRecDisk();
  } catch (e) {
    appendLog(`[rec] stop error: ${e.message}`);
  }
}

async function handleRecDelete(id) {
  if (!confirm(`Delete recording ${id.slice(0, 8)}...? (soft-delete, moves to .trash/)`)) return;
  try {
    const r = await fetch(`/recording/${id}`, { method: "DELETE" });
    if (!r.ok) {
      const p = await r.json().catch(() => ({}));
      appendLog(`[rec] delete failed: ${p.title || r.statusText}`);
      return;
    }
    appendLog(`[rec] deleted ${id.slice(0, 8)}`);
    await refreshRecList();
    await refreshRecDisk();
  } catch (e) {
    appendLog(`[rec] delete error: ${e.message}`);
  }
}

el("btn-restart")?.addEventListener("click", handleRestart);
el("btn-rec-start")?.addEventListener("click", handleRecStart);
el("btn-rec-stop")?.addEventListener("click", handleRecStop);
el("btn-rec-refresh")?.addEventListener("click", () => {
  refreshRecList();
  refreshRecDisk();
});

restoreTheme();
wireThemeToggle();
restoreRecInputs();

clearTelemetry();
refreshStatus();
wirePreviewState();
wireTelemetryJsonHeight();
connectEventStream();
connectTelemetryStream();
refreshRecStatus();
refreshRecList();
refreshRecDisk();
setInterval(tickTimers, 1000);
setInterval(refreshStatus, STATUS_REFRESH_INTERVAL_MS);
setInterval(refreshRecStatus, 2000);
setInterval(refreshRecDisk, 15000);
