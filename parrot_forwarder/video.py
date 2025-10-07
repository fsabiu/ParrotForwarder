#!/usr/bin/env python3
"""
VideoForwarder using GStreamer - Mux video and KLV data streams
"""

import subprocess
import signal
import logging
import time
import sys
import threading
import olympe

logger = logging.getLogger("VideoForwarder")


class VideoForwarder(threading.Thread):
    """
    GStreamer-based video forwarder that muxes drone video with KLV telemetry.
    Uses GStreamer's mpegtsmux for proper data stream support.
    """
    
    def __init__(self, drone_ip, srt_port=8890, klv_port=12345, stats_interval=30, use_high_latency=True):
        """
        Initialize the video forwarder.
        
        Args:
            drone_ip: IP address of the drone
            srt_port: Port for SRT output stream
            klv_port: Local UDP port for KLV telemetry data
            stats_interval: Seconds between status reports (default: 30)
            use_high_latency: Use high-latency pipeline for poor networks (default: True)
                            Set to False for low-latency on good networks
        """
        super().__init__(daemon=True)
        self.drone_ip = drone_ip
        self.srt_port = srt_port
        self.klv_port = klv_port
        self.srt_url = f"srt://0.0.0.0:{srt_port}?mode=listener"
        self.use_high_latency = use_high_latency
        self.gst_process = None
        self._stop_event = threading.Event()
        
        # Statistics tracking
        self.stats_interval = stats_interval
        self.start_time = None
        self.last_stats_time = None
        self.gst_warnings = 0
        self.gst_errors = 0
        self.stderr_thread = None
    
    def _monitor_gstreamer_stderr(self):
        """Monitor GStreamer stderr output for errors and warnings."""
        if not self.gst_process:
            return
        
        try:
            for line in iter(self.gst_process.stderr.readline, ''):
                if not line:
                    break
                
                line = line.strip()
                if not line:
                    continue
                
                # Count warnings and errors
                line_lower = line.lower()
                if 'warning' in line_lower:
                    self.gst_warnings += 1
                    # Only log first few warnings to avoid spam
                    if self.gst_warnings <= 3:
                        logger.warning(f"GStreamer: {line}")
                elif 'error' in line_lower or 'critical' in line_lower:
                    self.gst_errors += 1
                    logger.error(f"GStreamer: {line}")
                elif 'state change' in line_lower and 'playing' in line_lower:
                    logger.info("GStreamer pipeline state: PLAYING")
                    
        except Exception as e:
            logger.debug(f"Error reading GStreamer stderr: {e}")
    
    def _build_low_latency_pipeline(self, drone_rtsp_url):
        """
        Build LOW-LATENCY pipeline for good network conditions.
        
        - Lower latency (~200ms total)
        - Smaller buffers
        - Best for: USB connection, strong WiFi, low packet loss
        - Latency: ~0.2 seconds
        
        Args:
            drone_rtsp_url: RTSP URL of drone video stream
            
        Returns:
            str: GStreamer pipeline string
        """
        return (
            # RTSP source - minimal latency
            f"rtspsrc location={drone_rtsp_url} protocols=udp latency=50 ! "
            "application/x-rtp,media=video,encoding-name=H264 ! "
            "rtph264depay ! "
            "h264parse ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            "queue max-size-time=200000000 leaky=downstream ! "  # 200ms buffer
            "mux. "
            
            # KLV data source
            f"udpsrc port={self.klv_port} ! "
            "meta/x-klv,parsed=true ! "
            "queue max-size-time=200000000 leaky=downstream ! "
            "mux. "
            
            # MPEG-TS muxer
            "mpegtsmux name=mux alignment=7 ! "
            
            # SRT sink - low latency
            f"srtsink uri=\"{self.srt_url}\" latency=200 mode=listener"
        )
    
    def _build_high_latency_pipeline(self, drone_rtsp_url):
        """
        Build HIGH-LATENCY pipeline for poor network conditions.
        
        - Higher latency (~1000ms total)
        - Larger buffers
        - Better packet loss recovery
        - Best for: WiFi with interference, packet drops, jitter
        - Latency: ~1.0 second
        
        Args:
            drone_rtsp_url: RTSP URL of drone video stream
            
        Returns:
            str: GStreamer pipeline string
        """
        return (
            # RTSP source with increased buffering and error recovery
            f"rtspsrc location={drone_rtsp_url} protocols=udp latency=300 buffer-mode=auto retry=5 timeout=5000000 ! "
            "application/x-rtp,media=video,encoding-name=H264 ! "
            
            # RTP depayloader
            "rtph264depay ! "
            
            # H.264 parser with periodic config resend for recovery
            "h264parse config-interval=-1 ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            
            # Large video queue - 500ms buffer
            "queue max-size-buffers=0 max-size-bytes=0 max-size-time=500000000 leaky=downstream ! "
            "mux. "
            
            # KLV data with matching buffer
            f"udpsrc port={self.klv_port} ! "
            "meta/x-klv,parsed=true ! "
            "queue max-size-buffers=0 max-size-bytes=0 max-size-time=500000000 leaky=downstream ! "
            "mux. "
            
            # MPEG-TS muxer
            "mpegtsmux name=mux alignment=7 ! "
            
            # SRT sink with high latency for network resilience
            f"srtsink uri=\"{self.srt_url}\" latency=1000 mode=listener "
            "wait-for-connection=false pbkeylen=0"
        )
    
    def _log_status(self):
        """Log periodic status update."""
        if self.start_time is None:
            return
        
        current_time = time.time()
        
        # Check if it's time to report
        if self.last_stats_time is None or (current_time - self.last_stats_time) >= self.stats_interval:
            uptime = current_time - self.start_time
            uptime_str = time.strftime("%H:%M:%S", time.gmtime(uptime))
            
            # Check process health
            if self.gst_process and self.gst_process.poll() is None:
                status = "✓ STREAMING"
            else:
                status = "✗ STOPPED"
            
            # Format status message
            status_msg = (
                f"{status} | Uptime: {uptime_str} | "
                f"Port: {self.srt_port} | "
                f"Issues: {self.gst_errors} errors, {self.gst_warnings} warnings"
            )
            
            if self.gst_errors == 0:
                logger.info(status_msg)
            else:
                logger.warning(status_msg)
            
            self.last_stats_time = current_time
    
    def run(self):
        """Main thread execution - forward video stream and KLV data via GStreamer."""
        
        drone_rtsp_url = f"rtsp://{self.drone_ip}/live"
        
        # Note: Skipping availability check as GStreamer will handle connection
        logger.info("Starting GStreamer (will connect to drone RTSP stream)...")
        
        logger.info(f"Streaming video from {drone_rtsp_url} via SRT")
        logger.info(f"Muxing with KLV data from localhost:{self.klv_port}")
        
        # Select pipeline based on network quality
        if self.use_high_latency:
            logger.info("Using HIGH-LATENCY pipeline (better for poor networks)")
            pipeline = self._build_high_latency_pipeline(drone_rtsp_url)
        else:
            logger.info("Using LOW-LATENCY pipeline (better for good networks)")
            pipeline = self._build_low_latency_pipeline(drone_rtsp_url)
        
        # Use system GStreamer (not Anaconda's old version)
        cmd = ["/usr/bin/gst-launch-1.0", "-e"] + pipeline.split()
        
        logger.info(f"Starting GStreamer pipeline")
        logger.info(f"Stream available at: srt://<your-ip>:{self.srt_port}")
        logger.info(f"  Input 0: Video (H.264) from RTSP")
        logger.info(f"  Input 1: Data (KLV) from TS stream on UDP:{self.klv_port}")
        
        try:
            self.gst_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Start monitoring stderr in separate thread
            self.stderr_thread = threading.Thread(
                target=self._monitor_gstreamer_stderr,
                daemon=True,
                name="GStreamerStderrMonitor"
            )
            self.stderr_thread.start()
            
            logger.info(f"✓ SRT stream started on port {self.srt_port}")
            logger.info(f"  Input: {drone_rtsp_url}")
            logger.info(f"  Clients can connect: srt://<your-ip>:{self.srt_port}")
            
            # Initialize timing for status reports
            self.start_time = time.time()
            self.last_stats_time = self.start_time
            
            # Monitor GStreamer process
            check_interval = 1  # Check every second
            while not self._stop_event.is_set():
                # Check if process is still running
                if self.gst_process.poll() is not None:
                    # Process terminated unexpectedly
                    logger.error(f"✗ GStreamer process terminated unexpectedly (exit code: {self.gst_process.returncode})")
                    
                    # Try to get remaining output
                    try:
                        remaining_stderr = self.gst_process.stderr.read()
                        if remaining_stderr:
                            logger.error(f"Final GStreamer output: {remaining_stderr}")
                    except:
                        pass
                    
                    break
                
                # Log periodic status
                self._log_status()
                
                time.sleep(check_interval)
            
            # Final status
            if self.start_time:
                total_uptime = time.time() - self.start_time
                uptime_str = time.strftime("%H:%M:%S", time.gmtime(total_uptime))
                logger.info(f"Video streaming session ended - Total uptime: {uptime_str}")
                
        except Exception as e:
            logger.error(f"Error starting GStreamer: {e}")
    
    def _wait_for_drone_video_ready(self, rtsp_url, timeout=30):
        """
        Wait for drone RTSP stream to be available.
        
        Args:
            rtsp_url: RTSP URL to check
            timeout: Maximum time to wait in seconds
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self._stop_event.is_set():
                return
                
            try:
                # Quick check if RTSP stream responds
                result = subprocess.run(
                    ["/usr/bin/gst-launch-1.0", f"rtspsrc location={rtsp_url} protocols=udp", "!", 
                     "fakesink", "-e"],
                    timeout=5,
                    capture_output=True,
                    text=True
                )
                
                if result.returncode == 0:
                    logger.info("✓ Drone video stream is available")
                    return
            except (subprocess.TimeoutExpired, Exception):
                pass
            
            time.sleep(1)
        
        logger.warning("⚠ Drone video stream not available - proceeding anyway")

    def stop(self):
        """Stop the video forwarder."""
        logger.info("Stopping video forwarder...")
        self._stop_event.set()
        
        if self.gst_process:
            logger.info("Stopping GStreamer process...")
            self.gst_process.send_signal(signal.SIGINT)
            try:
                self.gst_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("GStreamer did not stop gracefully, killing...")
                self.gst_process.kill()
            self.gst_process = None
        
        logger.info("✓ Video forwarder stopped")


if __name__ == "__main__":
    print("VideoForwarder is designed to be used as part of ParrotForwarder")
    print("Usage: python -m parrot_forwarder.main --help")

