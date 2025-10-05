"""
TelemetryForwarder - Handles telemetry data reading and forwarding

Reads drone telemetry at specified FPS and forwards via KLV (MISB 0601) over UDP.
"""

import logging
import time
import threading
import json
import socket
from datetime import datetime

from .klv_encoder import encode_telemetry_to_klv

from olympe.messages.ardrone3.PilotingState import (
    FlyingStateChanged, PositionChanged, SpeedChanged, 
    AltitudeChanged, AttitudeChanged
)
from olympe.messages.ardrone3.GPSSettingsState import GPSFixStateChanged
from olympe.messages.common.CommonState import BatteryStateChanged


class TelemetryForwarder(threading.Thread):
    """
    Handles reading and forwarding telemetry data from the drone.
    Runs in a separate thread and collects telemetry at specified intervals.
    Forwards telemetry as KLV (MISB 0601) over UDP to localhost for FFmpeg to consume.
    """
    
    def __init__(self, drone, fps=10, klv_port=12345, name="TelemetryForwarder"):
        """
        Initialize the telemetry forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Frames per second for telemetry updates
            klv_port: Local UDP port for KLV data (for FFmpeg to consume)
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.telemetry_count = 0
        self.logger = logging.getLogger(f"{__name__}.{name}")
        
        # KLV forwarding configuration - always send to localhost for FFmpeg
        self.local_klv_host = '127.0.0.1'
        self.local_klv_port = klv_port
        self.udp_socket = None
        
        # Initialize UDP socket for KLV forwarding (raw KLV for GStreamer)
        try:
            self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp_socket.setblocking(True)
            self.logger.info(f"✓ KLV UDP socket initialized - sending to {self.local_klv_host}:{self.local_klv_port}")
        except Exception as e:
            self.logger.error(f"✗ Failed to create KLV UDP socket: {e}")
            self.udp_socket = None
        
        # Performance tracking
        self.start_time = None
        self.last_stats_time = None
        self.stats_interval = 5.0  # Report stats every 5 seconds
        self.loop_times = []
        self.max_loop_times = 100  # Keep last 100 loop times for stats
        self.packets_sent = 0
        self.send_errors = 0
        
    def get_telemetry_data(self):
        """
        Collect current telemetry data from the drone.
        
        Returns:
            dict: Dictionary containing all telemetry data
        """
        telemetry = {
            'timestamp': datetime.utcnow().isoformat(),
            'sequence': self.telemetry_count,
        }
        
        try:
            # Battery
            battery = self.drone.get_state(BatteryStateChanged)
            if battery:
                telemetry['battery_percent'] = battery.get('percent', None)
            
            # GPS
            gps_fix = self.drone.get_state(GPSFixStateChanged)
            if gps_fix:
                telemetry['gps_fixed'] = bool(gps_fix.get('fixed', 0))
            
            # Position
            position = self.drone.get_state(PositionChanged)
            if position:
                telemetry['latitude'] = position.get('latitude', None)
                telemetry['longitude'] = position.get('longitude', None)
                telemetry['altitude'] = position.get('altitude', None)
            
            # Altitude
            altitude = self.drone.get_state(AltitudeChanged)
            if altitude:
                telemetry['altitude_agl'] = altitude.get('altitude', None)
            
            # Attitude (orientation)
            attitude = self.drone.get_state(AttitudeChanged)
            if attitude:
                telemetry['roll'] = attitude.get('roll', None)
                telemetry['pitch'] = attitude.get('pitch', None)
                telemetry['yaw'] = attitude.get('yaw', None)
            
            # Speed
            speed = self.drone.get_state(SpeedChanged)
            if speed:
                telemetry['speed_x'] = speed.get('speedX', None)
                telemetry['speed_y'] = speed.get('speedY', None)
                telemetry['speed_z'] = speed.get('speedZ', None)
            
            # Flying state
            flying_state = self.drone.get_state(FlyingStateChanged)
            if flying_state:
                telemetry['flying_state'] = flying_state.get('state', None)
            
        except Exception as e:
            # Only log error if it's not an uninitialized state (which is expected initially)
            error_msg = str(e)
            if "state is uninitialized" not in error_msg:
                self.logger.error(f"Error getting telemetry: {e}")
            # For uninitialized states, we just continue with empty telemetry
        
        return telemetry
    
    def forward_telemetry(self, telemetry):
        """
        Forward telemetry data via UDP as KLV (MISB 0601) binary format.
        
        Args:
            telemetry: Dictionary containing telemetry data
        """
        if not self.udp_socket:
            return
        
        try:
            # Convert ISO timestamp to Unix timestamp in microseconds
            try:
                ts_str = telemetry.get('timestamp', datetime.utcnow().isoformat())
                # Handle both with and without 'Z' suffix
                ts_str = ts_str.replace('Z', '+00:00')
                dt = datetime.fromisoformat(ts_str)
                telemetry['timestamp_us'] = int(dt.timestamp() * 1_000_000)
            except Exception as e:
                self.logger.warning(f"Error parsing timestamp: {e}")
                telemetry['timestamp_us'] = None
            
            # Encode telemetry to KLV using our custom encoder
            klv_packet = encode_telemetry_to_klv(telemetry)
            
            if not klv_packet:
                self.send_errors += 1
                self.logger.error(f"✗ Failed to encode KLV packet. Telemetry: {telemetry}")
                return
            
            # Debug: log first few KLV packets
            if self.packets_sent < 2:
                gps_status = "GPS FIXED" if telemetry.get('gps_fixed') else "NO GPS (orientation only)"
                self.logger.info(
                    f"DEBUG: KLV packet #{self.packets_sent + 1} - "
                    f"{len(klv_packet)} bytes - {gps_status}"
                )
                if telemetry.get('gps_fixed'):
                    self.logger.info(
                        f"  GPS: Lat={telemetry.get('latitude', 'N/A')}, "
                        f"Lon={telemetry.get('longitude', 'N/A')}, "
                        f"Alt={telemetry.get('altitude', 'N/A')}m"
                    )
                self.logger.info(
                    f"  Orientation: Roll={telemetry.get('roll', 'N/A'):.3f}°, "
                    f"Pitch={telemetry.get('pitch', 'N/A'):.3f}°, "
                    f"Yaw={telemetry.get('yaw', 'N/A'):.3f}°"
                )
            
            # Send raw KLV packet via UDP to localhost for GStreamer
            self.udp_socket.sendto(klv_packet, (self.local_klv_host, self.local_klv_port))
            self.packets_sent += 1
            
            # Debug: log first few KLV packets
            if self.packets_sent <= 3:
                self.logger.info(f"Sent KLV packet #{self.packets_sent}: {len(klv_packet)} bytes")
            
        except Exception as e:
            self.send_errors += 1
            self.logger.error(f"✗ Error encoding or sending KLV packet #{self.packets_sent}: {e}")
    
    def log_performance_stats(self):
        """Log performance statistics."""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
            self.last_stats_time = current_time
            return
        
        # Check if it's time to report stats
        if current_time - self.last_stats_time >= self.stats_interval:
            elapsed = current_time - self.start_time
            actual_fps = self.telemetry_count / elapsed if elapsed > 0 else 0
            
            # Calculate loop time statistics
            if self.loop_times:
                avg_loop_time = sum(self.loop_times) / len(self.loop_times)
                min_loop_time = min(self.loop_times)
                max_loop_time = max(self.loop_times)
                
                # Check if we're meeting target FPS
                fps_ratio = (actual_fps / self.fps) * 100 if self.fps > 0 else 0
                
                status = "✓" if fps_ratio >= 95 else "⚠" if fps_ratio >= 80 else "✗"
                
                # Build performance message
                perf_msg = (
                    f"{status} PERFORMANCE: "
                    f"Target={self.fps:.1f} fps, Actual={actual_fps:.2f} fps ({fps_ratio:.1f}%) | "
                    f"Loop: avg={avg_loop_time*1000:.2f}ms, min={min_loop_time*1000:.2f}ms, max={max_loop_time*1000:.2f}ms | "
                    f"Count={self.telemetry_count} | "
                    f"KLV: sent={self.packets_sent}, errors={self.send_errors}"
                )
                
                self.logger.info(perf_msg)
                
                # Warn if we're falling behind
                if fps_ratio < 95:
                    self.logger.warning(
                        f"Telemetry forwarding is running at {fps_ratio:.1f}% of target FPS! "
                        f"Target: {self.fps} fps, Actual: {actual_fps:.2f} fps"
                    )
            
            self.last_stats_time = current_time
    
    def run(self):
        """Main thread execution loop with precise timing."""
        self.logger.info(f"Started - Target FPS: {self.fps} Hz (interval: {self.interval*1000:.2f}ms)")
        self.running = True
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        
        # Use target time instead of sleep-based timing for better precision
        next_frame_time = self.start_time
        
        while self.running:
            try:
                loop_start = time.time()
                
                # Get telemetry data
                telemetry = self.get_telemetry_data()
                self.telemetry_count += 1
                
                # Forward telemetry
                self.forward_telemetry(telemetry)
                
                # Track loop time
                loop_time = time.time() - loop_start
                self.loop_times.append(loop_time)
                if len(self.loop_times) > self.max_loop_times:
                    self.loop_times.pop(0)
                
                # Log performance stats periodically
                self.log_performance_stats()
                
                # Calculate next target time
                next_frame_time += self.interval
                current_time = time.time()
                sleep_time = next_frame_time - current_time
                
                if sleep_time > 0:
                    # Sleep until next frame time
                    time.sleep(sleep_time)
                else:
                    # We're falling behind - reset timing to avoid spiral
                    if sleep_time < -self.interval:
                        self.logger.warning(
                            f"Fell behind by {-sleep_time*1000:.2f}ms - resetting timing"
                        )
                        next_frame_time = time.time()
                    
                    # Warn if we can't keep up
                    if self.telemetry_count % self.fps == 0:  # Once per second
                        self.logger.warning(
                            f"Cannot maintain {self.fps} fps - loop took {loop_time*1000:.2f}ms "
                            f"(target: {self.interval*1000:.2f}ms)"
                        )
                
            except KeyboardInterrupt:
                self.logger.info("⚠ Interrupted by user")
                self.running = False
                break
            except Exception as e:
                self.logger.error(f"Error in telemetry loop: {e}")
                next_frame_time = time.time() + self.interval
                time.sleep(self.interval)
        
        # Final stats
        if self.start_time:
            total_elapsed = time.time() - self.start_time
            final_fps = self.telemetry_count / total_elapsed if total_elapsed > 0 else 0
            self.logger.info(
                f"Stopped - Forwarded {self.telemetry_count} telemetry packets | "
                f"Average FPS: {final_fps:.2f} (target: {self.fps})"
            )
    
    def stop(self):
        """Stop the telemetry forwarder and cleanup resources."""
        self.running = False
        if self.udp_socket:
            try:
                self.udp_socket.close()
            except:
                pass
        self.logger.info("Stopped")

