# ParrotForwarder Telemetry Contract

Contract version: `aion.parrot.telemetry.v1`

This is the detector-facing contract for telemetry emitted by ParrotForwarder.
The detector consumes the MPEG-TS/SRT stream and reads one H.264 video stream
plus one KLV data stream. The KLV stream carries both the compatibility MISB
0601 geolocation tags and an AION full-telemetry JSON extension.

## Transport And Cadence

- Transport: MPEG-TS over SRT, listener port from `forwarder.srt_port`.
- Telemetry cadence: `forwarder.telemetry_fps`, default `30` Hz.
- Dashboard/API control: `PUT /config/forwarder/telemetry-fps` updates the
  in-memory cadence and requests a controlled worker reset when active.
- Ordering: KLV packets are append-only samples. `timestamp_us` and `sequence`
  must be treated as the primary ordering keys.
- Live-drone evidence is recorded in the WP-03 evidence file. The latest
  compact-mode evidence from 2026-05-17 is summarized below.

## KLV Local Set

The detector must continue to parse the legacy flat MISB-compatible tags:

| Tag | Detector field | Unit / encoding |
|---:|---|---|
| 2 | `timestamp_us` | Unix epoch microseconds, uint64 |
| 5 | `roll` | degrees, int16 scaled by 100 |
| 6 | `pitch` | degrees, int16 scaled by 100 |
| 7 | `heading` | degrees, uint16 scaled by 100 |
| 13 | `latitude` | degrees, int32 scaled by 1e7 |
| 14 | `longitude` | degrees, int32 scaled by 1e7 |
| 15 | `altitude` | meters MSL, uint16 scaled by 10 |
| 16 | `sensor_h_fov` | degrees, uint16 scaled by 100 |
| 17 | `sensor_v_fov` | degrees, uint16 scaled by 100 |
| 21 | `gimbal_roll_rel` | degrees, int32 scaled by 1e6 |
| 22 | `gimbal_pitch_rel` | degrees, int32 scaled by 1e6 |
| 23 | `gimbal_yaw_rel` | degrees, int32 scaled by 1e6 |
| 102 | `sensor_width_mm` | float32 millimeters |
| 103 | `sensor_height_mm` | float32 millimeters |
| 104 | `focal_length_mm` | float32 millimeters |
| 105 | `gimbal_yaw_abs` | degrees, int32 scaled by 1e6 |
| 106 | `gimbal_pitch_abs` | degrees, int32 scaled by 1e6 |
| 107 | `gimbal_roll_abs` | degrees, int32 scaled by 1e6 |
| 120 | `aion_telemetry_json` | UTF-8 JSON, BER length |

Detector KLV parsing must support BER item lengths, not only one-byte item
lengths. Tag `120` can exceed 127 bytes and will use BER long-form lengths.

## AION JSON Extension

Tag `120` contains this JSON envelope:

```json
{
  "contract_version": "aion.parrot.telemetry.v1",
  "source": "parrot_forwarder",
  "source_id": "anafi",
  "source_name": "Anafi",
  "timestamp": "2026-05-12T12:00:00.000Z",
  "timestamp_us": 1778587200000000,
  "sequence": 1234,
  "telemetry": {}
}
```

`telemetry` is the complete ParrotForwarder sample: stable flat fields plus raw
SDK state evidence. Consumers must ignore unknown fields and preserve the
envelope for evidence/debug dumps.

`source` is the producer component identity and remains `parrot_forwarder`.
Downstream systems that need the real aircraft label must use `source_id` and
`source_name`, which are resolved from the drone product/name telemetry when
available and fall back to `parrot_anafi_unknown`.

The stable flat fields below are the detector contract. In addition, each
sample may contain:

- `olympe_state_count`: number of SDK state entries captured from
  `Drone.query_state("")`.
- `olympe_state`: sanitized raw Olympe state cache keyed by SDK message name.
- `olympe_event_state`: sanitized last-known payloads for event-only surfaces
  subscribed by ParrotForwarder, including gimbal, camera, storage, and RSSI
  events that are not always available through `get_state()`.

Normal e2e KLV uses compact tag `120`: `olympe_state_count` remains present,
but `olympe_state` and `olympe_event_state` are omitted from the 30 Hz KLV
payload to avoid spending most of the SRT bitrate on repeated raw SDK evidence.
Set `forwarder.include_raw_sdk_state_in_klv: true` only for short debug
captures that need full raw SDK state in the MPEG-TS/SRT stream. Dashboard and
consumer logic must not require these raw fields.

## Latest Live Compact Evidence

The latest current-version live evidence was captured on 2026-05-17 with the
dashboard closed and one detector SRT consumer. It decoded `3881` tag `120`
payloads at `29.948 Hz`. The total MPEG-TS/SRT-equivalent bitrate was
`6.118 Mbps` / `0.765 MB/s`; KLV/tag `120` was `0.903 Mbps` / `0.113 MB/s`;
video plus MPEG-TS overhead was `5.215 Mbps` / `0.652 MB/s`. Compared with the
pre-compact clean baseline, total bandwidth dropped by `7.260 Mbps` (`54.3%`)
and KLV/tag `120` dropped by `7.120 Mbps` (`88.7%`).

The decoded KLV local-set tags in that run were `2`, `5`, `6`, `7`, `16`,
`17`, `21`, `22`, `23`, `102`, `103`, `104`, `105`, `106`, `107`, and `120`.
Tags `13`, `14`, and `15` are intentionally omitted when `position_valid=false`
because no trusted latitude, longitude, or MSL altitude is available.

Detector/geolocation tests this week should explicitly verify the following
tag `120` fields against outdoor data:

- GPS gate: `position_valid`, `gps_fix`, `position_latitude`,
  `position_longitude`, `position_altitude_msl`, and `position_is_default`.
- Height fields: `altitude_agl`, `altitude_relative_takeoff_m`,
  `altitude_takeoff_m`, and, when GPS is valid, `ground_altitude_msl`.
- Camera/geolocation fields: `heading_deg`, `roll_deg`, `pitch_deg`,
  `yaw_deg`, `gimbal_*_abs`, `gimbal_*_rel`, `camera_h_fov_deg`,
  `camera_v_fov_deg`, `camera_focal_length_mm`, and `camera_zoom_level`.

This is a real compact tag `120` JSON payload decoded from the current live
evidence. It is an indoor/no-GPS sample, so coordinates and MSL altitude are
`null`; the height-above-ground and takeoff-relative fields are still present.

```json
{
  "contract_version": "aion.parrot.telemetry.v1",
  "sequence": 10771,
  "source": "parrot_forwarder",
  "source_id": "anafi_g032304",
  "source_name": "ANAFI-G032304",
  "telemetry": {
    "alert_state": "none",
    "altitude": null,
    "altitude_agl": 3.5,
    "altitude_relative_takeoff_m": 0.0,
    "altitude_takeoff_m": 0.0,
    "battery_percent": 73,
    "cam_align_max_pitch": null,
    "cam_align_max_roll": null,
    "cam_align_max_yaw": null,
    "cam_align_min_pitch": null,
    "cam_align_min_roll": null,
    "cam_align_min_yaw": null,
    "cam_align_pitch": null,
    "cam_align_roll": null,
    "cam_align_yaw": null,
    "camera_focal_length": 23.0,
    "camera_focal_length_base": 23.0,
    "camera_focal_length_base_mm": 23.0,
    "camera_focal_length_mm": 23.0,
    "camera_h_fov_deg": 76.09408506365217,
    "camera_recording_available": null,
    "camera_recording_start_timestamp_ms": null,
    "camera_recording_state": null,
    "camera_sensor_height": 4.7,
    "camera_sensor_height_mm": 4.7,
    "camera_sensor_width": 6.3,
    "camera_sensor_width_mm": 6.3,
    "camera_v_fov_deg": 60.55711817004386,
    "camera_zoom_level": 1.0,
    "flying_state": "landed",
    "gimbal_attitude_updated_at": "2026-05-17T08:45:44.366Z",
    "gimbal_id": 0,
    "gimbal_offset_max_pitch": null,
    "gimbal_offset_max_roll": null,
    "gimbal_offset_max_yaw": null,
    "gimbal_offset_min_pitch": null,
    "gimbal_offset_min_roll": null,
    "gimbal_offset_min_yaw": null,
    "gimbal_offset_pitch": null,
    "gimbal_offset_roll": null,
    "gimbal_offset_update_state": null,
    "gimbal_offset_yaw": null,
    "gimbal_pitch_abs": 11.728273391723633,
    "gimbal_pitch_frame_of_reference": "absolute",
    "gimbal_pitch_rel": 11.728273391723633,
    "gimbal_roll_abs": 0.0000010695001719795982,
    "gimbal_roll_frame_of_reference": "absolute",
    "gimbal_roll_rel": -5.3690905055248095e-9,
    "gimbal_yaw_abs": -101.267578125,
    "gimbal_yaw_frame_of_reference": "relative",
    "gimbal_yaw_rel": -0.0000553164463781286,
    "gps_fix": false,
    "gps_fixed": false,
    "gps_location_altitude_msl_raw": 500.0,
    "gps_location_latitude_raw": 500.0,
    "gps_location_longitude_raw": 500.0,
    "heading_deg": 258.7330403840739,
    "home_altitude_msl": 500.0,
    "hovering_warning_no_gps_too_dark": true,
    "hovering_warning_no_gps_too_high": false,
    "latitude": null,
    "link_quality_4g_interference": false,
    "link_quality_bits": 5,
    "link_quality_external_perturbation": false,
    "link_quality_level": 5,
    "longitude": null,
    "motor_last_flight_duration_s": 58,
    "motor_total_flight_duration_s": 10634,
    "motor_total_flights": 65,
    "olympe_state_count": 170,
    "pitch": 0.07345602661371231,
    "pitch_deg": 4.208720304766367,
    "platform_altitude_msl": null,
    "position_altitude_accuracy_m": 14.0,
    "position_altitude_msl": null,
    "position_changed_altitude_msl_raw": 500.0,
    "position_changed_latitude_raw": 500.0,
    "position_changed_longitude_raw": 500.0,
    "position_is_default": false,
    "position_latitude": null,
    "position_latitude_accuracy_m": 14.0,
    "position_longitude": null,
    "position_longitude_accuracy_m": 14.0,
    "position_message": "gps_fix_unavailable",
    "position_source": "invalid",
    "position_valid": false,
    "product_hardware_version": "HW_03",
    "product_name": "ANAFI-G032304",
    "product_software_version": "1.8.2",
    "return_home_min_altitude_m": 30.0,
    "return_home_min_altitude_max_m": 100.0,
    "return_home_min_altitude_min_m": 20.0,
    "return_home_reason": "disabled",
    "return_home_state": "unavailable",
    "roll": 0.004881664644926786,
    "roll_deg": 0.27969878115253444,
    "rssi_dbm": -34.0,
    "sensor_h_fov": 76.09408506365217,
    "sensor_v_fov": 60.55711817004386,
    "sequence": 10771,
    "source_id": "anafi_g032304",
    "source_name": "ANAFI-G032304",
    "speed_horizontal_mps": 0.0,
    "speed_total_mps": 0.0,
    "speed_x": 0.0,
    "speed_y": -0.0,
    "speed_z": 0.0,
    "telemetry_hz": 30,
    "telemetry_target_hz": 30,
    "timestamp": "2026-05-17T08:45:44.561Z",
    "timestamp_us": 1779007544561000,
    "vibration_level": "ok",
    "wind_state": "ok",
    "yaw": -1.7674418687820435,
    "yaw_deg": -101.26695961592614
  },
  "timestamp": "2026-05-17T08:45:44.561Z",
  "timestamp_us": 1779007544561000
}
```

## Required Detector Semantics

- Use `position_valid=true` before trusting `position_latitude` and
  `position_longitude`.
- `latitude`, `longitude`, and `altitude` are the KLV compatibility values.
  When GPS is unavailable they are `null` in tag `120` telemetry and the
  compatibility KLV geolocation tags `13`, `14`, and `15` are omitted. No
  downstream consumer may substitute hardcoded coordinates.
- Prefer `position_altitude_msl` for aircraft MSL altitude when
  `position_valid=true`; use `altitude_agl` only as above-ground height.
- `roll`, `pitch`, and `yaw` in the JSON are radians from Olympe. `roll_deg`,
  `pitch_deg`, `yaw_deg`, and `heading_deg` are the degree forms.
- Gimbal absolute and relative angles are degrees. Frame-of-reference fields
  must be carried through with detections when geolocation is computed.
- Camera FOV, focal length, zoom, and sensor dimensions are part of the
  geolocation contract. Do not substitute hardcoded detector defaults when
  these fields are present.
- Accuracy fields are meters. If an accuracy is absent or `null`, downstream
  geolocation quality must mark the source as unknown rather than inventing a
  value.

## Complete Telemetry Field Set

The `telemetry` object currently includes every passive real-time field the
forwarder extracts from the Parrot Anafi/Olympe state surface used by this
runtime:

| Group | Fields |
|---|---|
| Sample | `timestamp`, `timestamp_us`, `sequence`, `source_id`, `source_name`, `telemetry_hz`, `telemetry_target_hz` |
| Battery / signal | `battery_percent`, `rssi_dbm`, `rssi_updated_at`, `link_quality_bits`, `link_quality_level`, `link_quality_4g_interference`, `link_quality_external_perturbation` |
| GPS validity | `gps_fixed`, `gps_fix`, `position_valid`, `position_is_default`, `position_source`, `position_message`, `position_satellites` |
| GPS raw | `gps_location_latitude_raw`, `gps_location_longitude_raw`, `gps_location_altitude_msl_raw`, `position_changed_latitude_raw`, `position_changed_longitude_raw`, `position_changed_altitude_msl_raw` |
| GPS accuracy | `position_latitude_accuracy_m`, `position_longitude_accuracy_m`, `position_altitude_accuracy_m` |
| Aircraft position | `position_latitude`, `position_longitude`, `position_altitude_msl`, `platform_altitude_msl`, `altitude_relative_takeoff_m`, `altitude_takeoff_m`, `altitude_agl`, `ground_altitude_msl` |
| KLV compatibility position | `latitude`, `longitude`, `altitude` |
| Home / RTH | `home_latitude`, `home_longitude`, `home_altitude_msl`, `return_home_state`, `return_home_reason`, `return_home_min_altitude_m`, `return_home_min_altitude_min_m`, `return_home_min_altitude_max_m` |
| Aircraft attitude | `roll`, `pitch`, `yaw`, `roll_deg`, `pitch_deg`, `yaw_deg`, `heading_deg` |
| Speed | `speed_x`, `speed_y`, `speed_z`, `speed_horizontal_mps`, `speed_total_mps`, `airspeed_mps` |
| Flight state | `flying_state`, `alert_state`, `wind_state`, `vibration_level`, `heading_locked_state`, `hovering_warning_no_gps_too_dark`, `hovering_warning_no_gps_too_high` |
| Gimbal | `gimbal_id`, `gimbal_yaw_frame_of_reference`, `gimbal_pitch_frame_of_reference`, `gimbal_roll_frame_of_reference`, `gimbal_yaw_abs`, `gimbal_pitch_abs`, `gimbal_roll_abs`, `gimbal_yaw_rel`, `gimbal_pitch_rel`, `gimbal_roll_rel`, `gimbal_attitude_updated_at` |
| Gimbal offsets | `gimbal_offset_update_state`, `gimbal_offset_min_yaw`, `gimbal_offset_max_yaw`, `gimbal_offset_yaw`, `gimbal_offset_min_pitch`, `gimbal_offset_max_pitch`, `gimbal_offset_pitch`, `gimbal_offset_min_roll`, `gimbal_offset_max_roll`, `gimbal_offset_roll` |
| Camera optics | `camera_id`, `camera_sensor_width`, `camera_sensor_height`, `camera_sensor_width_mm`, `camera_sensor_height_mm`, `camera_focal_length_base`, `camera_focal_length_base_mm`, `camera_zoom_level`, `camera_focal_length`, `camera_focal_length_mm`, `sensor_h_fov`, `sensor_v_fov`, `camera_h_fov_deg`, `camera_v_fov_deg` |
| Camera alignment | `camera_alignment_cam_id`, `cam_align_min_yaw`, `cam_align_max_yaw`, `cam_align_yaw`, `cam_align_min_pitch`, `cam_align_max_pitch`, `cam_align_pitch`, `cam_align_min_roll`, `cam_align_max_roll`, `cam_align_roll` |
| Camera recording | `camera_recording_cam_id`, `camera_recording_available`, `camera_recording_state`, `camera_recording_start_timestamp_ms`, `camera_recording_start_time` |
| Storage / product | `storage_free_space_mb`, `storage_recording_time_remaining_min`, `storage_photo_remaining`, `product_name`, `product_software_version`, `product_hardware_version` |
| Motor stats | `motor_total_flights`, `motor_last_flight_duration_s`, `motor_total_flight_duration_s` |
| Raw SDK completeness evidence | `olympe_state_count`; optional debug-only `olympe_state`, `olympe_event_state` |

Any future ParrotForwarder field added to the telemetry sample is automatically
carried by tag `120`. If detector logic depends on a new field, this file must
be updated in the same PR.
