"""
ParrotForwarder - Main coordinator for telemetry and video forwarding

Manages both TelemetryForwarder and VideoForwarder threads.
"""

import logging
import time
import signal
import olympe

from .telemetry import TelemetryForwarder
from .video import VideoForwarder


class ParrotForwarder:
    """
    Main controller for Parrot Anafi telemetry and video forwarding.
    Manages both telemetry and video forwarding threads.
    """
    
    def __init__(self, drone_ip, telemetry_fps=10, video_fps=30, 
                 remote_host=None, telemetry_port=5000, 
                 mediamtx_host='localhost', mediamtx_port=8554, stream_path='parrot_stream'):
        """
        Initialize the Parrot forwarder.
        
        Args:
            drone_ip: IP address of the drone
            telemetry_fps: Frames per second for telemetry forwarding
            video_fps: Frames per second for video forwarding
            remote_host: Remote host IP to forward telemetry to
            telemetry_port: UDP port for telemetry (default: 5000)
            mediamtx_host: MediaMTX server host for video streaming (default: localhost)
            mediamtx_port: MediaMTX RTSP port (default: 8554)
            stream_path: Stream path on MediaMTX server (default: parrot_stream)
        """
        self.logger = logging.getLogger(f"{__name__}.ParrotForwarder")
        
        self.drone_ip = drone_ip
        self.telemetry_fps = telemetry_fps
        self.video_fps = video_fps
        self.remote_host = remote_host
        self.telemetry_port = telemetry_port
        self.mediamtx_host = mediamtx_host
        self.mediamtx_port = mediamtx_port
        self.stream_path = stream_path
        self.drone = None
        self.telemetry_forwarder = None
        self.video_forwarder = None
        self._shutdown_requested = False
        
        # Debug: log what we received
        self.logger.info(f"DEBUG: ParrotForwarder init - remote_host={remote_host}, type={type(remote_host)}")
        
        # Set up signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        if not self._shutdown_requested:
            self.logger.info(f"\n⚠ Received signal {signum}, initiating graceful shutdown...")
            self._shutdown_requested = True
        else:
            self.logger.warning(f"\n⚠ Force shutdown requested (signal {signum})")
            # Force exit on second signal
            import sys
            sys.exit(1)
        
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
                    # Wait for initial telemetry and verify drone is ready
                    self._wait_for_drone_ready()
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
    
    def _wait_for_drone_ready(self, timeout=30):
        """
        Wait for the drone to be ready with telemetry data available.
        
        Args:
            timeout: Maximum time to wait in seconds
        """
        self.logger.info("Waiting for drone telemetry to initialize...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to get basic telemetry to verify drone is ready
                from olympe.messages.common.CommonState import BatteryStateChanged
                battery = self.drone.get_state(BatteryStateChanged)
                
                if battery is not None:
                    self.logger.info("✓ Drone telemetry is ready")
                    return
                    
            except Exception as e:
                # Telemetry not ready yet, continue waiting
                pass
            
            time.sleep(0.5)
        
        self.logger.warning("⚠ Drone telemetry initialization timeout - proceeding anyway")
        
    def start_forwarding(self):
        """Start both telemetry and video forwarding."""
        self.logger.info("=" * 60)
        self.logger.info("Starting Parrot Forwarder")
        self.logger.info(f"  Drone IP: {self.drone_ip}")
        self.logger.info(f"  Telemetry FPS: {self.telemetry_fps}")
        self.logger.info(f"  Video FPS: {self.video_fps} (streaming at original drone framerate)")
        if self.remote_host:
            self.logger.info(f"  Telemetry Remote Host: {self.remote_host}")
            self.logger.info(f"  Telemetry Port: {self.telemetry_port}")
        else:
            self.logger.info("  Telemetry Forwarding: DISABLED (no remote host specified)")
        self.logger.info(f"  MediaMTX Host: {self.mediamtx_host}")
        self.logger.info(f"  MediaMTX Port: {self.mediamtx_port}")
        self.logger.info(f"  Stream Path: {self.stream_path}")
        self.logger.info("=" * 60)
        
        # Create forwarders
        self.logger.info(f"DEBUG: Creating TelemetryForwarder with remote_host={self.remote_host}, port={self.telemetry_port}")
        self.telemetry_forwarder = TelemetryForwarder(
            self.drone, 
            self.telemetry_fps,
            self.remote_host,
            self.telemetry_port
        )
        self.video_forwarder = VideoForwarder(
            self.drone, 
            self.drone_ip,
            self.mediamtx_host,
            self.mediamtx_port,
            self.stream_path
        )
        
        # Set up video streaming
        #self.video_forwarder.setup_streaming()
        
        # Wait for video stream to initialize
        self.logger.info("Waiting for video stream to initialize...")
        time.sleep(1)
        
        # Start forwarder threads
        self.telemetry_forwarder.start()
        self.video_forwarder.start()
        
        self.logger.info("✓ Both forwarders started")
        
        # Give forwarders a moment to initialize
        time.sleep(1)
        
    def stop_forwarding(self):
        """Stop both telemetry and video forwarding."""
        self.logger.info("Stopping forwarders...")
        
        # Note: Video streaming is handled directly via RTSP/FFmpeg,
        # so we don't need to stop the drone's streaming API
        
        # Stop forwarder threads
        if self.telemetry_forwarder:
            self.telemetry_forwarder.stop()
        
        if self.video_forwarder:
            self.video_forwarder.stop()
        
        # Wait for threads to finish with shorter timeout
        if self.telemetry_forwarder and self.telemetry_forwarder.is_alive():
            self.telemetry_forwarder.join(timeout=1)
            if self.telemetry_forwarder.is_alive():
                self.logger.warning("Telemetry forwarder thread did not stop cleanly")
        
        if self.video_forwarder and self.video_forwarder.is_alive():
            self.video_forwarder.join(timeout=3)  # Give video forwarder more time for FFmpeg cleanup
            if self.video_forwarder.is_alive():
                self.logger.warning("Video forwarder thread did not stop cleanly")
        
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
                for _ in range(duration):
                    if self._shutdown_requested:
                        break
                    time.sleep(1)
            else:
                self.logger.info("Running indefinitely (Ctrl+C to stop)...")
                try:
                    while not self._shutdown_requested:
                        time.sleep(1)
                except KeyboardInterrupt:
                    self.logger.info("\n⚠ Interrupted by user")
            
        except KeyboardInterrupt:
            self.logger.info("\n⚠ Shutting down gracefully...")
        except Exception as e:
            import traceback
            self.logger.error(f"Error: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        
        finally:
            self.stop_forwarding()
            self.disconnect()

