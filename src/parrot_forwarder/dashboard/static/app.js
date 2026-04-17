// ParrotForwarder v2 dashboard.
// Vanilla JS only; no build step.

const state = {
  startedAt: null,
  lastTelemetryAt: null,
  serviceState: "DISCONNECTED",
  previewAvailable: false,
};

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

function setField(id, value = "-") {
  const node = el(id);
  if (node) node.textContent = value;
}

function syncPreviewState() {
  const frame = el("preview-frame");
  if (!frame) return;
  const visible = state.previewAvailable && ["STREAMING", "DEGRADED"].includes(state.serviceState);
  frame.classList.toggle("has-video", visible);
}

function clearTelemetry() {
  for (const id of TELEMETRY_FIELDS) {
    setField(id, "-");
  }
  setField("telemetry-json", "{}");
  state.lastTelemetryAt = null;
}

function setState(name) {
  const badge = el("state-badge");
  state.serviceState = name;
  badge.textContent = name;
  badge.className = `state state-${name.toLowerCase()}`;
  if (name === "STREAMING" && !state.startedAt) {
    state.startedAt = Date.now();
  }
  if (!["STREAMING", "DEGRADED"].includes(name)) {
    state.startedAt = null;
    state.previewAvailable = false;
    syncPreviewState();
    setField("uptime", "-");
    clearTelemetry();
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

function fmtCoords(latitude, longitude, digits = 6) {
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
  return `${klv.latitude.toFixed(6)}, ${klv.longitude.toFixed(6)}${altitude}`;
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
    const seconds = Math.floor((Date.now() - state.lastTelemetryAt) / 1000);
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
  if (!preview) return;
  for (const eventName of ["loadeddata", "canplay", "playing"]) {
    preview.addEventListener(eventName, () => setPreviewAvailable(true));
  }
  for (const eventName of ["emptied", "abort", "error"]) {
    preview.addEventListener(eventName, () => setPreviewAvailable(false));
  }
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
    appendLog("[info] event stream closed; reconnecting in 2 s");
    setTimeout(connectEventStream, 2000);
  });
}

function renderTelemetry(payload, sampleTime) {
  const position = payload.position || {};
  const gimbal = payload.gimbal || {};
  const camera = payload.camera || {};
  const flight = payload.flight || {};
  const system = payload.system || {};
  const storage = payload.storage || {};

  state.lastTelemetryAt = Date.now();
  setField("battery", isNumber(payload.battery_percent) ? `${payload.battery_percent}%` : "-");
  setField("gps", fmtBool(payload.gps_fix));
  setField("position-valid", fmtBool(payload.position_valid));
  setField("satellites", fmtInteger(position.satellites));
  setField("rssi", isNumber(payload.rssi_dbm) ? `${payload.rssi_dbm} dBm` : "-");
  setField("fps", isNumber(payload.fps) ? payload.fps.toFixed(1) : "-");
  if (sampleTime) setField("last-telemetry", sampleTime);

  setField("position-source", position.source || "-");
  setField("position-message", position.message || "-");
  setField("position-coords", fmtCoords(position.latitude, position.longitude));
  setField("position-altitudes", fmtAltitudes(position));
  setField("position-accuracy", fmtAccuracy(position));
  setField("home-coords", fmtCoords(position.home?.latitude, position.home?.longitude));
  setField("klv-coords", fmtKlvCoords(position));

  setField("gimbal-abs", fmtAxisTriplet(gimbal.absolute_deg));
  setField("gimbal-rel", fmtAxisTriplet(gimbal.relative_deg));
  setField("gimbal-offsets", fmtAxisTriplet(gimbal.offset_deg));
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
  setField("camera-alignment", fmtAxisTriplet(camera.alignment_deg));
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
  setField("telemetry-json", JSON.stringify(payload, null, 2));
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
    appendLog("[info] telemetry stream closed; reconnecting in 2 s");
    clearTelemetry();
    setTimeout(connectTelemetryStream, 2000);
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

clearTelemetry();
refreshStatus();
wirePreviewState();
connectEventStream();
connectTelemetryStream();
setInterval(tickTimers, 1000);
setInterval(refreshStatus, 5000);
