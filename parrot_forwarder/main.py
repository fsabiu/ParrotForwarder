"""
ParrotForwarder - Main coordinator for telemetry and video forwarding

Manages both TelemetryForwarder and VideoForwarder threads.
"""

import logging
import time
import olympe

from .telemetry import TelemetryForwarder
from .video import VideoForwarder


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
        
    def connect(self, max_retries=None, retry_interval=5):
        """
        Connect to the drone with retry logic.
        
        Args:
            max_retries: Maximum number of connection attempts (None = infinite)
            retry_interval: Seconds to wait between retries
        """
        self.drone = olympe.Drone(self.drone_ip)
        
        attempt = 0
        while True:
            attempt += 1
            
            if max_retries and attempt > max_retries:
                raise ConnectionError(f"Failed to connect to drone at {self.drone_ip} after {max_retries} attempts")
            
            try:
                self.logger.info(f"Connecting to drone at {self.drone_ip}... (attempt {attempt})")
                
                if self.drone.connect():
                    self.logger.info("✓ Connected to drone")
                    # Wait for initial telemetry
                    time.sleep(1)
                    return
                else:
                    self.logger.warning(f"⚠ Connection attempt {attempt} failed")
                    
            except KeyboardInterrupt:
                self.logger.info("\n⚠ Connection interrupted by user")
                raise
            except Exception as e:
                self.logger.error(f"✗ Connection attempt {attempt} error: {e}")
            
            # Wait before retry (with KeyboardInterrupt handling)
            if max_retries is None or attempt < max_retries:
                try:
                    self.logger.info(f"Retrying in {retry_interval} seconds... (Ctrl+C to cancel)")
                    time.sleep(retry_interval)
                except KeyboardInterrupt:
                    self.logger.info("\n⚠ Retry interrupted by user")
                    raise
        
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
    
    def run(self, duration=None, max_retries=None, retry_interval=5):
        """
        Run the forwarder for a specified duration or until interrupted.
        
        Args:
            duration: Duration in seconds (None = run indefinitely)
            max_retries: Maximum connection retry attempts (None = infinite)
            retry_interval: Seconds between connection retries
        """
        try:
            self.connect(max_retries=max_retries, retry_interval=retry_interval)
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
                    self.logger.info("\n⚠ Interrupted by user")
            
        except KeyboardInterrupt:
            self.logger.info("\n⚠ Shutting down gracefully...")
        except Exception as e:
            self.logger.error(f"Error: {e}")
            raise
        
        finally:
            self.stop_forwarding()
            self.disconnect()

