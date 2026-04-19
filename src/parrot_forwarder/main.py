"""
ParrotForwarder - Main coordinator for telemetry and video forwarding

Manages both TelemetryForwarder and VideoForwarder threads.
"""

import logging
import time
import signal
import socket
from typing import Any, Callable, Optional


def _default_drone_factory(ip: str) -> Any:
    """Default drone factory - lazily imports Olympe so hosts without it
    (dev laptops, CI) can still construct a :class:`ParrotForwarder` when
    a test injects its own ``drone_factory``.
    """
    import olympe

    return olympe.Drone(ip)


class ParrotForwarder:
    """
    Main controller for Parrot Anafi telemetry and video forwarding.
    Manages both telemetry and video forwarding threads.
    """
    
    def __init__(self, drone_ip, telemetry_fps=10, video_fps=30,
                 srt_port=8890, klv_port_start=12345, auto_reconnect=True,
                 health_check_interval=5, video_stats_interval=30,
                 video_ip: str | None = None,
                 drone_factory: Optional[Callable[[str], Any]] = None,
                 install_signal_handlers: bool = True):
        """
        Initialize the Parrot forwarder.

        Args:
            drone_ip: IP address of the drone
            telemetry_fps: Frames per second for telemetry forwarding
            video_fps: Frames per second for video forwarding
            srt_port: SRT port for video stream (default: 8890)
            klv_port_start: Starting port for KLV telemetry (default: 12345, will find next available)
            auto_reconnect: Enable automatic reconnection on drone disconnect (default: True)
            health_check_interval: Seconds between connection health checks (default: 5)
            video_stats_interval: Seconds between video status reports (default: 30)
            video_ip: Optional RTSP endpoint when video is exposed on a
                different address than control/telemetry.
            drone_factory: Callable ``(ip) -> drone`` used to build the Olympe
                handle. Defaults to an internal factory that lazily imports
                Olympe. Tests inject ``MockDrone`` (or a partially-applied
                factory) to exercise the forwarder without hardware.
            install_signal_handlers: If False, skip installing SIGINT/SIGTERM
                handlers. Tests that construct :class:`ParrotForwarder` in
                a non-main thread (or where signal installation is unwanted)
                set this to False.
        """
        self.logger = logging.getLogger(f"{__name__}.ParrotForwarder")
        
        self.drone_ip = drone_ip
        self.video_ip = video_ip or drone_ip
        self.telemetry_fps = telemetry_fps
        self.video_fps = video_fps
        self.srt_port = srt_port
        self.drone = None
        self.telemetry_forwarder = None
        self.video_forwarder = None
        self._shutdown_requested = False
        self._is_forwarding = False
        
        # Auto-reconnect settings
        self.auto_reconnect = auto_reconnect
        self.health_check_interval = health_check_interval
        
        # Stats settings
        self.video_stats_interval = video_stats_interval
        
        # Dependency injection point for the Olympe Drone.
        self._drone_factory: Callable[[str], Any] = drone_factory or _default_drone_factory

        # Find available port for KLV telemetry
        self.klv_port = self._find_free_port(klv_port_start)
        self.logger.info(f"KLV telemetry port selected: {self.klv_port}")

        # Set up signal handlers for graceful shutdown
        if install_signal_handlers:
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
    
    def _is_port_free(self, port):
        """
        Check if a UDP port is free.
        
        Args:
            port: Port number to check
            
        Returns:
            bool: True if port is free, False otherwise
        """
        try:
            # Try to bind to the port
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1', port))
            sock.close()
            return True
        except OSError:
            return False
    
    def _find_free_port(self, start_port, max_attempts=100):
        """
        Find a free UDP port starting from start_port.
        
        Args:
            start_port: Starting port number
            max_attempts: Maximum number of ports to try
            
        Returns:
            int: Free port number
            
        Raises:
            RuntimeError: If no free port found within max_attempts
        """
        for offset in range(max_attempts):
            port = start_port + offset
            if self._is_port_free(port):
                if offset > 0:
                    self.logger.info(f"Port {start_port} was in use, using port {port} instead")
                return port
        
        raise RuntimeError(f"Could not find free port starting from {start_port} after {max_attempts} attempts")
        
    def connect(self, max_retries=None, retry_interval=5):
        """
        Connect to the drone with retry logic.
        
        Args:
            max_retries: Maximum number of connection attempts (None = infinite)
            retry_interval: Seconds to wait between retries
        """
        self.drone = self._drone_factory(self.drone_ip)
        
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
    
    def is_drone_connected(self):
        """
        Check if the drone is currently connected.
        
        Returns:
            bool: True if drone is connected and responsive, False otherwise
        """
        if not self.drone:
            return False
        
        try:
            connection_state = getattr(self.drone, "connection_state", None)
            if callable(connection_state):
                return bool(connection_state())

            # Fallback for older/partial mock implementations that expose the
            # connection only through a private flag.
            if hasattr(self.drone, '_connected'):
                return bool(self.drone._connected)
            
            # Last-resort probe when the runtime does not expose a dedicated
            # connection-state API.
            from olympe.messages.common.CommonState import BatteryStateChanged
            battery = self.drone.get_state(BatteryStateChanged)
            
            return battery is not None
            
        except Exception as e:
            self.logger.debug(f"Connection check failed: {e}")
            return False
        
    def start_forwarding(self):
        """Start both telemetry and video forwarding."""
        if self._is_forwarding:
            self.logger.warning("Forwarders already running, skipping start")
            return
        
        self.logger.info("=" * 60)
        self.logger.info("Starting Parrot Forwarder")
        self.logger.info(f"  Control IP: {self.drone_ip}")
        self.logger.info(f"  Video IP: {self.video_ip}")
        self.logger.info(f"  Telemetry FPS: {self.telemetry_fps}")
        self.logger.info(f"  Telemetry Format: KLV (MISB 0601) -> localhost:{self.klv_port}")
        self.logger.info(f"  Video FPS: {self.video_fps} (streaming at original drone framerate)")
        self.logger.info(f"  Output: Unified SRT stream (video + KLV) on port {self.srt_port}")
        self.logger.info(f"  Client command: ffplay 'srt://<your-ip>:{self.srt_port}'")
        self.logger.info(f"  NOTE: Using GStreamer for native KLV muxing")
        if self.auto_reconnect:
            self.logger.info(f"  Auto-reconnect: ENABLED (health check every {self.health_check_interval}s)")
        else:
            self.logger.info(f"  Auto-reconnect: DISABLED")
        self.logger.info("=" * 60)
        
        # Lazy import: the telemetry and video modules pull in Olympe and
        # GStreamer respectively, which are Linux-only. Deferring the import
        # keeps ``parrot_forwarder.main`` importable on dev hosts.
        from .telemetry import TelemetryForwarder
        from .video import VideoForwarder

        # Create forwarders
        self.telemetry_forwarder = TelemetryForwarder(
            self.drone,
            self.telemetry_fps,
            self.klv_port
        )
        self.video_forwarder = VideoForwarder(
            self.video_ip,
            self.srt_port,
            self.klv_port,
            self.video_stats_interval,
            use_high_latency=True
        )
        
        # Wait for video stream to initialize
        self.logger.info("Waiting for video stream to initialize...")
        time.sleep(1)
        
        # Start forwarder threads
        self.telemetry_forwarder.start()
        self.video_forwarder.start()
        
        self.logger.info("✓ Both forwarders started")
        self._is_forwarding = True
        
        # Give forwarders a moment to initialize
        time.sleep(1)
        
    def stop_forwarding(self):
        """Stop both telemetry and video forwarding."""
        if not self._is_forwarding:
            self.logger.debug("Forwarders not running, skipping stop")
            return
        
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
        
        self._is_forwarding = False
        self.telemetry_forwarder = None
        self.video_forwarder = None
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
        With auto_reconnect enabled, monitors connection and automatically reconnects.
        
        Args:
            duration: Duration in seconds (None = run indefinitely)
            max_retries: Maximum connection retry attempts for initial connection (None = infinite)
            retry_interval: Seconds between connection retries
        """
        start_time = time.time()
        connection_attempts = 0
        last_health_check = 0
        
        try:
            # Initial connection
            self.connect(max_retries=max_retries, retry_interval=retry_interval)
            self.start_forwarding()
            connection_attempts = 0
            
            # Main monitoring loop
            if duration:
                self.logger.info(f"Running for {duration} seconds...")
            else:
                self.logger.info("Running indefinitely (Ctrl+C to stop)...")
            
            while not self._shutdown_requested:
                current_time = time.time()
                
                # Check if duration expired
                if duration and (current_time - start_time) >= duration:
                    self.logger.info("Duration expired, shutting down...")
                    break
                
                # Perform health check at intervals
                if self.auto_reconnect and (current_time - last_health_check) >= self.health_check_interval:
                    last_health_check = current_time
                    
                    if not self.is_drone_connected():
                        self.logger.warning("⚠ Drone connection lost! Attempting to reconnect...")
                        connection_attempts += 1
                        
                        # Stop forwarders before reconnecting
                        self.stop_forwarding()
                        self.disconnect()
                        
                        # Wait a moment before reconnecting
                        time.sleep(2)
                        
                        # Attempt reconnection
                        try:
                            self.logger.info(f"Reconnection attempt #{connection_attempts}...")
                            self.connect(max_retries=3, retry_interval=retry_interval)
                            self.start_forwarding()
                            
                            self.logger.info(f"✓ Successfully reconnected to drone (attempt #{connection_attempts})")
                            connection_attempts = 0
                            
                        except KeyboardInterrupt:
                            raise
                        except Exception as e:
                            self.logger.error(f"Reconnection attempt #{connection_attempts} failed: {e}")
                            self.logger.info(f"Will retry in {retry_interval} seconds...")
                            time.sleep(retry_interval)
                            continue
                
                # Sleep for a short interval
                time.sleep(1)
            
        except KeyboardInterrupt:
            self.logger.info("\n⚠ Shutting down gracefully...")
        except Exception as e:
            import traceback
            self.logger.error(f"Fatal error: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise
        
        finally:
            self.stop_forwarding()
            self.disconnect()
            
            # Print summary
            if connection_attempts > 0:
                self.logger.info(f"Session summary: {connection_attempts} reconnection(s) performed")
