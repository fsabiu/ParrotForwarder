#!/usr/bin/env python3
"""
ParrotForwarder - Real-time telemetry and video forwarding from Parrot Anafi

This script reads telemetry and video streams from a Parrot Anafi drone
and prepares them for forwarding to external systems.

Architecture:
- TelemetryForwarder: Reads and forwards telemetry data at specified FPS
- VideoForwarder: Reads and forwards video frames at specified FPS
"""

import olympe
from olympe.messages.ardrone3.PilotingState import (
    FlyingStateChanged, AlertStateChanged, PositionChanged, 
    SpeedChanged, AltitudeChanged, AttitudeChanged
)
from olympe.messages.ardrone3.GPSSettingsState import GPSFixStateChanged
from olympe.messages.common.CommonState import BatteryStateChanged
import logging
import time
import threading
import argparse
import json
from datetime import datetime
import cv2
import numpy as np
import socket

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


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
            self.logger.info(
                f"✓ Sent packet #{self.packets_sent} to {self.remote_host}:{self.remote_port} "
                f"({len(message)} bytes) - Battery: {telemetry.get('battery_percent', 'N/A')}%"
            )
            
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
        
        # Close UDP socket
        if self.udp_socket:
            try:
                self.udp_socket.close()
                self.logger.info("UDP socket closed")
            except:
                pass


class VideoForwarder(threading.Thread):
    """
    Handles reading and forwarding video frames from the drone.
    Runs in a separate thread and processes video frames.
    """
    
    def __init__(self, drone, fps=30, name="VideoForwarder"):
        """
        Initialize the video forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Target frames per second for video forwarding
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.frame_count = 0
        self.forwarded_count = 0
        self.last_forward_time = time.time()
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self.lock = threading.Lock()
        self.latest_frame = None
        
        # Performance tracking
        self.start_time = None
        self.last_stats_time = None
        self.stats_interval = 5.0  # Report stats every 5 seconds
        self.loop_times = []
        self.max_loop_times = 100  # Keep last 100 loop times for stats
        self.frames_received_last_sec = 0
        self.last_frame_count = 0
        
    def yuv_frame_callback(self, yuv_frame):
        """
        Callback for receiving YUV frames from Olympe.
        This runs in Olympe's video thread.
        
        Args:
            yuv_frame: YUV frame from Olympe
        """
        with self.lock:
            self.frame_count += 1
            
            try:
                # Reference the frame
                yuv_frame.ref()
                
                # Convert YUV to BGR
                yuv_data = yuv_frame.as_ndarray()
                if yuv_data is not None:
                    bgr_frame = cv2.cvtColor(yuv_data, cv2.COLOR_YUV2BGR_I420)
                    self.latest_frame = bgr_frame.copy()
                
                # Unreference the frame
                yuv_frame.unref()
                
            except Exception as e:
                self.logger.error(f"Error processing frame: {e}")
                try:
                    yuv_frame.unref()
                except:
                    pass
    
    def forward_frame(self, frame):
        """
        Forward a video frame to external system.
        This is a placeholder - will be implemented later.
        
        Args:
            frame: BGR frame (numpy array)
        """
        # TODO: Implement actual forwarding (RTMP, WebRTC, UDP, etc.)
        self.forwarded_count += 1
    
    def log_performance_stats(self):
        """Log performance statistics."""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
            self.last_stats_time = current_time
            self.last_frame_count = self.frame_count
            return
        
        # Check if it's time to report stats
        if current_time - self.last_stats_time >= self.stats_interval:
            elapsed = current_time - self.start_time
            
            # Calculate actual forwarding FPS
            forwarded_fps = self.forwarded_count / elapsed if elapsed > 0 else 0
            
            # Calculate incoming frame rate from drone
            frames_received = self.frame_count - self.last_frame_count
            incoming_fps = frames_received / self.stats_interval
            self.last_frame_count = self.frame_count
            
            # Calculate loop time statistics
            if self.loop_times:
                avg_loop_time = sum(self.loop_times) / len(self.loop_times)
                min_loop_time = min(self.loop_times)
                max_loop_time = max(self.loop_times)
                
                # Check if we're meeting target FPS
                fps_ratio = (forwarded_fps / self.fps) * 100 if self.fps > 0 else 0
                
                status = "✓" if fps_ratio >= 95 else "⚠" if fps_ratio >= 80 else "✗"
                
                self.logger.info(
                    f"{status} PERFORMANCE: "
                    f"Target={self.fps:.1f} fps, Forwarded={forwarded_fps:.2f} fps ({fps_ratio:.1f}%) | "
                    f"Incoming={incoming_fps:.1f} fps, Received={self.frame_count} | "
                    f"Loop: avg={avg_loop_time*1000:.2f}ms, min={min_loop_time*1000:.2f}ms, max={max_loop_time*1000:.2f}ms"
                )
                
                # Warn if we're falling behind
                if fps_ratio < 95:
                    self.logger.warning(
                        f"Video forwarding is running at {fps_ratio:.1f}% of target FPS! "
                        f"Target: {self.fps} fps, Actual: {forwarded_fps:.2f} fps"
                    )
                
                # Warn if incoming frame rate is too low
                if incoming_fps < self.fps * 0.8:
                    self.logger.warning(
                        f"Incoming frame rate ({incoming_fps:.1f} fps) is lower than target ({self.fps} fps)"
                    )
            
            self.last_stats_time = current_time
    
    def start_callback(self):
        """Called when video streaming starts."""
        self.logger.info("Video stream started")
    
    def stop_callback(self):
        """Called when video streaming stops."""
        self.logger.info(f"Video stream stopped - Processed {self.frame_count} frames")
    
    def flush_callback(self, *args, **kwargs):
        """Called to flush pending frames."""
        pass
    
    def setup_streaming(self):
        """Set up video streaming callbacks."""
        self.logger.info("Setting up video stream callbacks...")
        self.drone.streaming.set_callbacks(
            raw_cb=self.yuv_frame_callback,
            start_cb=self.start_callback,
            end_cb=self.stop_callback,
            flush_raw_cb=self.flush_callback
        )
        self.drone.streaming.start()
        self.logger.info("Video streaming started")
    
    def run(self):
        """Main thread execution loop with precise timing."""
        self.logger.info(f"Started - Target FPS: {self.fps} (interval: {self.interval*1000:.2f}ms)")
        self.running = True
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        
        # Wait for frames to start arriving
        time.sleep(1)
        
        # Use target time instead of sleep-based timing for better precision
        next_frame_time = time.time()
        
        while self.running:
            try:
                loop_start = time.time()
                
                # Get latest frame
                with self.lock:
                    frame = self.latest_frame
                
                # Forward frame if available
                if frame is not None:
                    self.forward_frame(frame)
                
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
                    if self.forwarded_count > 0 and self.forwarded_count % self.fps == 0:  # Once per second
                        self.logger.warning(
                            f"Cannot maintain {self.fps} fps - loop took {loop_time*1000:.2f}ms "
                            f"(target: {self.interval*1000:.2f}ms)"
                        )
                
            except Exception as e:
                self.logger.error(f"Error in video forwarding loop: {e}")
                next_frame_time = time.time() + self.interval
                time.sleep(self.interval)
        
        # Final stats
        if self.start_time:
            total_elapsed = time.time() - self.start_time
            final_fps = self.forwarded_count / total_elapsed if total_elapsed > 0 else 0
            self.logger.info(
                f"Stopped - Forwarded {self.forwarded_count} frames, Received {self.frame_count} frames | "
                f"Average forwarding FPS: {final_fps:.2f} (target: {self.fps})"
            )
    
    def stop(self):
        """Stop the video forwarder."""
        self.running = False


class ParrotForwarder:
    """
    Main controller for Parrot Anafi telemetry and video forwarding.
    Manages both telemetry and video forwarding threads.
    """
    
    def __init__(self, drone_ip, telemetry_fps=10, video_fps=30, 
                 remote_host=None, telemetry_port=5000, video_port=5004):
        """
        Initialize the Parrot forwarder.
        
        Args:
            drone_ip: IP address of the drone
            telemetry_fps: Frames per second for telemetry forwarding
            video_fps: Frames per second for video forwarding
            remote_host: Remote host IP to forward data to
            telemetry_port: UDP port for telemetry (default: 5000)
            video_port: UDP/RTP port for video (default: 5004)
        """
        self.logger = logging.getLogger(f"{__name__}.ParrotForwarder")
        
        self.drone_ip = drone_ip
        self.telemetry_fps = telemetry_fps
        self.video_fps = video_fps
        self.remote_host = remote_host
        self.telemetry_port = telemetry_port
        self.video_port = video_port
        self.drone = None
        self.telemetry_forwarder = None
        self.video_forwarder = None
        
        # Debug: log what we received
        self.logger.info(f"DEBUG: ParrotForwarder init - remote_host={remote_host}, type={type(remote_host)}")
        
    def connect(self):
        """Connect to the drone."""
        self.logger.info(f"Connecting to drone at {self.drone_ip}...")
        self.drone = olympe.Drone(self.drone_ip)
        
        if not self.drone.connect():
            raise ConnectionError(f"Failed to connect to drone at {self.drone_ip}")
        
        self.logger.info("✓ Connected to drone")
        
        # Wait for initial telemetry
        time.sleep(1)
        
    def start_forwarding(self):
        """Start both telemetry and video forwarding."""
        self.logger.info("=" * 60)
        self.logger.info("Starting Parrot Forwarder")
        self.logger.info(f"  Drone IP: {self.drone_ip}")
        self.logger.info(f"  Telemetry FPS: {self.telemetry_fps}")
        self.logger.info(f"  Video FPS: {self.video_fps}")
        if self.remote_host:
            self.logger.info(f"  Remote Host: {self.remote_host}")
            self.logger.info(f"  Telemetry Port: {self.telemetry_port}")
            self.logger.info(f"  Video Port: {self.video_port}")
        else:
            self.logger.info("  Forwarding: DISABLED (no remote host specified)")
        self.logger.info("=" * 60)
        
        # Create forwarders
        self.logger.info(f"DEBUG: Creating TelemetryForwarder with remote_host={self.remote_host}, port={self.telemetry_port}")
        self.telemetry_forwarder = TelemetryForwarder(
            self.drone, 
            self.telemetry_fps,
            self.remote_host,
            self.telemetry_port
        )
        self.video_forwarder = VideoForwarder(self.drone, self.video_fps)
        
        # Set up video streaming
        self.video_forwarder.setup_streaming()
        
        # Start forwarder threads
        self.telemetry_forwarder.start()
        self.video_forwarder.start()
        
        self.logger.info("✓ Both forwarders started")
        
    def stop_forwarding(self):
        """Stop both telemetry and video forwarding."""
        self.logger.info("Stopping forwarders...")
        
        if self.telemetry_forwarder:
            self.telemetry_forwarder.stop()
        
        if self.video_forwarder:
            self.video_forwarder.stop()
        
        # Wait for threads to finish
        if self.telemetry_forwarder and self.telemetry_forwarder.is_alive():
            self.telemetry_forwarder.join(timeout=2)
        
        if self.video_forwarder and self.video_forwarder.is_alive():
            self.video_forwarder.join(timeout=2)
        
        # Stop video streaming
        if self.drone:
            try:
                self.drone.streaming.stop()
            except:
                pass
        
        self.logger.info("✓ Forwarders stopped")
        
    def disconnect(self):
        """Disconnect from the drone."""
        if self.drone:
            self.logger.info("Disconnecting from drone...")
            try:
                self.drone.disconnect()
                self.logger.info("✓ Disconnected")
            except Exception as e:
                self.logger.error(f"Error during disconnect: {e}")
    
    def run(self, duration=None):
        """
        Run the forwarder for a specified duration or until interrupted.
        
        Args:
            duration: Duration in seconds (None = run indefinitely)
        """
        try:
            self.connect()
            self.start_forwarding()
            
            if duration:
                self.logger.info(f"Running for {duration} seconds...")
                time.sleep(duration)
            else:
                self.logger.info("Running indefinitely (Ctrl+C to stop)...")
                try:
                    while True:
                        time.sleep(1)
                except KeyboardInterrupt:
                    self.logger.info("Interrupted by user")
            
        except Exception as e:
            self.logger.error(f"Error: {e}")
            raise
        
        finally:
            self.stop_forwarding()
            self.disconnect()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description='Parrot Anafi Telemetry and Video Forwarder',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--drone-ip',
        type=str,
        default='192.168.53.1',
        help='IP address of the Parrot Anafi drone'
    )
    parser.add_argument(
        '--remote-host',
        type=str,
        default=None,
        help='Remote host IP address to forward data to (required for forwarding)'
    )
    parser.add_argument(
        '--telemetry-port',
        type=int,
        default=5000,
        help='UDP port for telemetry forwarding'
    )
    parser.add_argument(
        '--video-port',
        type=int,
        default=5004,
        help='UDP/RTP port for video forwarding'
    )
    parser.add_argument(
        '--telemetry-fps',
        type=int,
        default=10,
        help='Frames per second for telemetry forwarding'
    )
    parser.add_argument(
        '--video-fps',
        type=int,
        default=30,
        help='Frames per second for video forwarding'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=None,
        help='Duration to run in seconds (default: run indefinitely)'
    )
    
    args = parser.parse_args()
    
    # Debug: log parsed arguments
    logger.info(f"DEBUG: Parsed args - remote_host={args.remote_host}, telemetry_port={args.telemetry_port}")
    
    # Validate arguments
    if args.remote_host is None:
        logger.warning("No --remote-host specified. Running in monitoring mode (no forwarding).")
    
    # Create and run forwarder
    forwarder = ParrotForwarder(
        drone_ip=args.drone_ip,
        telemetry_fps=args.telemetry_fps,
        video_fps=args.video_fps,
        remote_host=args.remote_host,
        telemetry_port=args.telemetry_port,
        video_port=args.video_port
    )
    
    forwarder.run(duration=args.duration)


if __name__ == "__main__":
    main()

