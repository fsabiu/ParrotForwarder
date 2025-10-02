"""
TelemetryForwarder - Handles telemetry data reading and forwarding

Reads drone telemetry at specified FPS and forwards via JSON over UDP.
"""

import logging
import time
import threading
import json
import socket
from datetime import datetime

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
    Forwards telemetry as JSON over UDP.
    """
    
    def __init__(self, drone, fps=10, remote_host=None, remote_port=5000, name="TelemetryForwarder"):
        """
        Initialize the telemetry forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Frames per second for telemetry updates
            remote_host: Remote host IP address to send telemetry to
            remote_port: Remote port for telemetry (default: 5000)
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.telemetry_count = 0
        self.logger = logging.getLogger(f"{__name__}.{name}")
        
        # UDP forwarding configuration
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.udp_socket = None
        self.forwarding_enabled = remote_host is not None
        
        # Debug logging
        self.logger.info(f"DEBUG: TelemetryForwarder.__init__ - remote_host={remote_host}, remote_port={remote_port}, forwarding_enabled={self.forwarding_enabled}")
        
        # Initialize UDP socket if forwarding is enabled
        if self.forwarding_enabled:
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Set socket to non-blocking to avoid delays
                self.udp_socket.setblocking(False)
                self.logger.info(f"✓ UDP socket initialized - sending to {remote_host}:{remote_port}")
            except Exception as e:
                self.logger.error(f"✗ Failed to create UDP socket: {e}")
                self.forwarding_enabled = False
        else:
            self.logger.info("Telemetry forwarding DISABLED (no remote_host specified)")
        
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
                
                # Debug: log position data on first packet to verify
                if self.telemetry_count == 1:
                    self.logger.info(
                        f"DEBUG: Position data - "
                        f"GPS fixed: {telemetry.get('gps_fixed', False)}, "
                        f"Lat: {telemetry.get('latitude')}, "
                        f"Lon: {telemetry.get('longitude')}, "
                        f"Alt: {telemetry.get('altitude')}"
                    )
            
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
            self.logger.error(f"Error getting telemetry: {e}")
        
        return telemetry
    
    def forward_telemetry(self, telemetry):
        """
        Forward telemetry data via UDP as JSON.
        
        Args:
            telemetry: Dictionary containing telemetry data
        """
        if not self.forwarding_enabled:
            self.logger.warning("forward_telemetry called but forwarding is DISABLED")
            return
        
        try:
            # Serialize telemetry to JSON
            json_data = json.dumps(telemetry, default=str)  # default=str handles any non-serializable types
            message = json_data.encode('utf-8')
            
            # Send via UDP
            self.udp_socket.sendto(message, (self.remote_host, self.remote_port))
            self.packets_sent += 1
            
            # Log EVERY packet sent for debugging
            # self.logger.info(
            #     f"✓ Sent packet #{self.packets_sent} to {self.remote_host}:{self.remote_port} "
            #     f"({len(message)} bytes) - Battery: {telemetry.get('battery_percent', 'N/A')}%"
            # )
            
        except BlockingIOError:
            # Socket buffer full - skip this packet (non-blocking socket)
            self.logger.warning(f"⚠ BlockingIOError - socket buffer full, packet #{self.packets_sent} skipped")
        except Exception as e:
            self.send_errors += 1
            self.logger.error(f"✗ Error sending packet #{self.packets_sent}: {e}")
    
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
                    f"Count={self.telemetry_count}"
                )
                
                # Add forwarding stats if enabled
                if self.forwarding_enabled:
                    perf_msg += f" | UDP: sent={self.packets_sent}, errors={self.send_errors}"
                
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

