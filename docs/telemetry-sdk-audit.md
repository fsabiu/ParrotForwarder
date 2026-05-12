# Telemetry SDK Audit

Purpose: evidence that the ParrotForwarder telemetry contract intentionally
covers the passive real-time Olympe telemetry needed by the detector/COP path.

Scope is Parrot Anafi + Skycontroller 3, read-only telemetry/state. Command
messages, configuration setters, calibration workflows, media download APIs,
debug traces, and non-real-time firmware metadata are out of scope unless they
produce a passive state/event already listed below.

## Included Olympe Surfaces

| SDK surface | Messages used | Contract coverage |
|---|---|---|
| `ardrone3.GPSSettingsState` | `GPSFixStateChanged`, `HomeChanged`, `ReturnHomeMinAltitudeChanged` | GPS fix validity, home coordinates, RTH minimum altitude bounds |
| `ardrone3.GPSState` | `NumberOfSatelliteChanged` | Satellite count |
| `ardrone3.PilotingState` | `GpsLocationChanged`, `PositionChanged`, `AltitudeChanged`, `AltitudeAboveGroundChanged`, `AttitudeChanged`, `SpeedChanged`, `AirSpeedChanged` | Position, MSL/AGL/takeoff altitude, attitude, heading, speed |
| `ardrone3.PilotingState` | `FlyingStateChanged`, `AlertStateChanged`, `NavigateHomeStateChanged`, `HeadingLockedStateChanged`, `HoveringWarning`, `VibrationLevelChanged`, `WindStateChanged` | Flight/status/degraded-state signals |
| `ardrone3.SettingsState` | `MotorFlightsStatusChanged` | Total flights and flight durations |
| `common.CommonState` | `BatteryStateChanged`, `WifiSignalChanged`, `LinkSignalQuality`, `MassStorageInfoRemainingListChanged` | Battery, fallback RSSI, link quality bitfield, storage availability |
| `common.SettingsState` | `ProductNameChanged`, `ProductVersionChanged` | Product/version telemetry for source evidence |
| `wifi` | `rssi_changed` | Primary RSSI source |
| `gimbal` | `attitude`, `offsets` | Absolute/relative gimbal attitude, frame references, offsets and bounds |
| `camera` | `zoom_level`, `recording_state`, `alignment_offsets` | Zoom/focal/FOV derivation, recording state, camera alignment offsets |

## Implementation Notes

- `TelemetryForwarder` calls `Drone.query_state("")` on every telemetry sample
  and publishes the sanitized raw SDK cache as `olympe_state` in KLV tag `120`.
- Stable detector fields are still extracted with `get_state()` so units,
  fallbacks, and validity flags stay explicit and backward compatible.
- Sticky event subscribers cover event-only telemetry such as gimbal attitude
  and RSSI; their sanitized last-known payloads are published as
  `olympe_event_state`.
- The telemetry sample is the source of truth. The supervisor WebSocket
  groups that sample for the dashboard, while KLV tag `120` carries the same
  complete sample to the detector.
- Standard MISB-compatible KLV tags remain for legacy detector geolocation.
  The AION JSON extension prevents data loss for fields that do not have a
  compact standard tag in the current forwarder.
- The audit is source/documentation based. Live confirmation that every field
  is populated on the target drone/controller combination is pending hardware
  validation and must be recorded in WP-03 evidence.

## Explicit Exclusions

| Surface | Reason |
|---|---|
| Olympe command messages such as takeoff, landing, camera commands, gimbal commands | They are control actions, not passive telemetry samples. |
| Calibration/settings mutation state that requires operator workflows | Not continuous real-time telemetry for detector geolocation. |
| Media gallery/download metadata | File management, not live frame telemetry. |
| Debug/profiling/log streams | Operational diagnostics; not detector/COP telemetry contract. |
| Non-Anafi product-specific messages not present on the target hardware | Outside the accepted hardware target. Add only when the target expands. |

## SDK References

- Parrot Olympe `get_state()` / `query_state()` API:
  `https://developer.parrot.com/docs/olympe/olympeapi.html`
- Parrot Olympe `ardrone3.PilotingState` messages:
  `https://developer.parrot.com/docs/olympe/arsdkng_ardrone3_piloting.html`
- Parrot Olympe GPS state/settings messages:
  `https://developer.parrot.com/docs/olympe/arsdkng_ardrone3_gps.html`
- Parrot Olympe common state/settings messages:
  `https://developer.parrot.com/docs/olympe/arsdkng_common_common.html`
- Parrot Olympe gimbal messages:
  `https://developer.parrot.com/docs/olympe/arsdkng_gimbal.html`
- Parrot Olympe camera messages:
  `https://developer.parrot.com/docs/olympe/arsdkng_camera.html`
- Parrot Olympe wifi messages:
  `https://developer.parrot.com/docs/olympe/arsdkng_wifi.html`

## Validation Checklist For Live Drone Run

- Verify 30 Hz KLV packet cadence over at least 60 seconds.
- Record representative tag `120` packet size with live hardware and confirm
  KLV UDP/SRT muxing stays stable at the configured 30 Hz cadence.
- Decode tag `120` from the SRT stream and confirm `contract_version`.
- Confirm `olympe_state_count > 0`, `olympe_state` contains SDK message-name
  keys, and `olympe_event_state` updates after gimbal/camera/RSSI events.
- Confirm `position_valid` and raw GPS defaults while GPS is unavailable.
- Confirm valid GPS, altitude, attitude, speed, gimbal, camera, signal, storage,
  and product fields with the drone/controller powered and connected.
- Compare dashboard JSON, KLV tag `120`, and detector-decoded telemetry for the
  same timestamp/sequence.
