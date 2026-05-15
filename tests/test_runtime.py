from __future__ import annotations

from parrot_forwarder.forwarder.runtime import _normalize_telemetry


def test_normalize_telemetry_groups_rich_snapshot() -> None:
    snapshot: dict[str, object] = {
        "timestamp": "2026-04-17T16:00:00Z",
        "sequence": 12,
        "source_id": "anafi",
        "source_name": "Anafi",
        "battery_percent": 82,
        "telemetry_hz": 30,
        "gps_fixed": False,
        "position_valid": False,
        "position_source": "invalid",
        "position_message": "gps_fix_unavailable",
        "position_is_default": False,
        "position_satellites": 0,
        "position_latitude_accuracy_m": 3.0,
        "position_longitude_accuracy_m": 4.0,
        "position_altitude_accuracy_m": 5.0,
        "gps_location_latitude_raw": 500.0,
        "gps_location_longitude_raw": 500.0,
        "gps_location_altitude_msl_raw": 143.2,
        "position_changed_latitude_raw": 500.0,
        "position_changed_longitude_raw": 500.0,
        "position_changed_altitude_msl_raw": 143.2,
        "latitude": None,
        "longitude": None,
        "altitude": None,
        "position_altitude_msl": None,
        "altitude_agl": 21.7,
        "altitude_relative_takeoff_m": 24.5,
        "ground_altitude_msl": None,
        "roll": 0.10,
        "pitch": -0.20,
        "yaw": 1.20,
        "roll_deg": 5.73,
        "pitch_deg": -11.46,
        "yaw_deg": 68.75,
        "heading_deg": 68.75,
        "speed_x": 4.2,
        "speed_y": -0.4,
        "speed_z": -0.9,
        "speed_horizontal_mps": 4.22,
        "speed_total_mps": 4.31,
        "airspeed_mps": 4.8,
        "rssi_dbm": -54.0,
        "link_quality_level": 5,
        "link_quality_bits": 69,
        "link_quality_4g_interference": True,
        "link_quality_external_perturbation": False,
        "gimbal_id": 0,
        "gimbal_yaw_frame_of_reference": "absolute",
        "gimbal_pitch_frame_of_reference": "absolute",
        "gimbal_roll_frame_of_reference": "absolute",
        "gimbal_yaw_abs": 12.5,
        "gimbal_pitch_abs": -88.0,
        "gimbal_roll_abs": 0.2,
        "gimbal_yaw_rel": 1.0,
        "gimbal_pitch_rel": -45.0,
        "gimbal_roll_rel": 0.0,
        "gimbal_offset_update_state": "active",
        "gimbal_offset_yaw": 0.2,
        "gimbal_offset_pitch": -0.4,
        "gimbal_offset_roll": 0.1,
        "gimbal_offset_min_yaw": -5.0,
        "gimbal_offset_max_yaw": 5.0,
        "gimbal_offset_min_pitch": -10.0,
        "gimbal_offset_max_pitch": 10.0,
        "gimbal_offset_min_roll": -2.0,
        "gimbal_offset_max_roll": 2.0,
        "camera_id": 0,
        "camera_sensor_width_mm": 6.3,
        "camera_sensor_height_mm": 4.7,
        "camera_focal_length_mm": 23.0,
        "camera_focal_length_base_mm": 23.0,
        "camera_zoom_level": 1.0,
        "camera_h_fov_deg": 76.6,
        "camera_v_fov_deg": 59.3,
        "cam_align_yaw": 0.1,
        "cam_align_pitch": -0.2,
        "cam_align_roll": 0.0,
        "cam_align_min_yaw": -1.0,
        "cam_align_max_yaw": 1.0,
        "cam_align_min_pitch": -1.0,
        "cam_align_max_pitch": 1.0,
        "cam_align_min_roll": -1.0,
        "cam_align_max_roll": 1.0,
        "camera_recording_available": "available",
        "camera_recording_state": "inactive",
        "camera_recording_start_timestamp_ms": 0.0,
        "flying_state": "hovering",
        "alert_state": "none",
        "return_home_state": "available",
        "return_home_reason": "finished",
        "return_home_min_altitude_m": 10.0,
        "return_home_min_altitude_min_m": 5.0,
        "return_home_min_altitude_max_m": 30.0,
        "heading_locked_state": "disabled",
        "wind_state": "ok",
        "vibration_level": "ok",
        "hovering_warning_no_gps_too_dark": False,
        "hovering_warning_no_gps_too_high": True,
        "product_name": "Anafi",
        "product_software_version": "1.8.2",
        "product_hardware_version": "hw-1",
        "motor_total_flights": 12,
        "motor_last_flight_duration_s": 240,
        "motor_total_flight_duration_s": 7200,
        "storage_free_space_mb": 1800,
        "storage_recording_time_remaining_min": 48,
        "storage_photo_remaining": 350,
    }

    normalized = _normalize_telemetry(snapshot)

    assert normalized["gps_fix"] is False
    assert normalized["source_id"] == "anafi"
    assert normalized["source_name"] == "Anafi"
    assert normalized["battery_percent"] == 82
    assert normalized["telemetry_hz"] == 30
    assert normalized["telemetry_target_hz"] == 30
    assert "fps" not in normalized
    assert normalized["position_valid"] is False
    assert normalized["position"] == {
        "valid": False,
        "source": "invalid",
        "message": "gps_fix_unavailable",
        "is_default": False,
        "gps_fix": False,
        "satellites": 0,
        "altitude_agl_m": 21.7,
        "altitude_relative_takeoff_m": 24.5,
        "accuracy_m": {"latitude": 3.0, "longitude": 4.0, "altitude": 5.0},
        "raw": {
            "gps_location": {
                "latitude": 500.0,
                "longitude": 500.0,
                "altitude_msl_m": 143.2,
            },
            "position_changed": {
                "latitude": 500.0,
                "longitude": 500.0,
                "altitude_msl_m": 143.2,
            },
        },
    }
    assert normalized["gimbal"]["absolute_deg"]["pitch"] == -88.0
    assert normalized["gimbal"]["offset_bounds_deg"]["yaw"] == {"min": -5.0, "max": 5.0}
    assert normalized["camera"]["recording"] == {
        "available": "available",
        "state": "inactive",
        "start_timestamp_ms": 0.0,
    }
    assert normalized["flight"]["return_home"] == {
        "state": "available",
        "reason": "finished",
        "min_altitude_m": 10.0,
        "min_bound_m": 5.0,
        "max_bound_m": 30.0,
    }
    assert normalized["system"]["motor_flights"]["total_flights"] == 12
    assert normalized["storage"]["photo_remaining"] == 350
    assert normalized["raw"] == snapshot
