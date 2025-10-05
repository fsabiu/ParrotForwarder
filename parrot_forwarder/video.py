#!/usr/bin/env python3
"""
VideoForwarder - Forward drone video stream through local MediaMTX
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
    Thread-based video forwarder that streams drone video to MediaMTX server.
    """
    
    def __init__(self, drone, drone_ip, srt_port=8890, klv_port=12345):
        """
        Initialize the video forwarder.
        
        Args:
            drone: Olympe drone instance
            drone_ip: IP address of the drone
            srt_port: SRT port for direct streaming (default: 8890)
            klv_port: Local UDP port to listen for KLV telemetry data (default: 12345)
        """
        super().__init__(daemon=True)
        #self.drone = drone
        self.drone_ip = drone_ip
        self.srt_port = srt_port
        self.klv_port = klv_port
        # Direct SRT listener - no MediaMTX intermediary
        self.srt_url = f"srt://0.0.0.0:{srt_port}?mode=listener"
        self.ffmpeg_process = None
        self._stop_event = threading.Event()
        #self._streaming_setup = False

    
    def run(self):
        """Main thread execution - forward video stream and KLV data to MediaMTX."""
        
        # Get the drone's RTSP stream URL
        drone_rtsp_url = f"rtsp://{self.drone_ip}/live"
        
        # Local UDP URL where TelemetryForwarder is sending KLV data
        klv_udp_url = f"udp://127.0.0.1:{self.klv_port}"
        
        # Wait for drone to be ready before starting FFmpeg
        logger.info("Waiting for drone video stream to be available...")
        self._wait_for_drone_video_ready(drone_rtsp_url)
        
        logger.info(f"Streaming video from {drone_rtsp_url} via SRT")
        logger.info(f"NOTE: Testing video-only first, KLV will be added after verification")

        # VIDEO-ONLY TEST - Simple SRT output
        cmd = [
            "ffmpeg",
            
            # --- INPUT: VIDEO FROM DRONE ---
            "-probesize", "2M",
            "-analyzeduration", "2M",
            "-fflags", "nobuffer",
            "-flags", "low_delay",
            "-rtsp_transport", "udp",
            "-i", drone_rtsp_url,
            
            # --- VIDEO PROCESSING ---
            "-c:v", "copy",            # Copy video without re-encoding
            "-an",                     # No audio
            
            # --- FIX: Force keyframes for better client compatibility ---
            "-bsf:v", "h264_mp4toannexb",  # Ensure Annex B format for MPEG-TS
            
            # --- OUTPUT OPTIONS ---
            "-f", "mpegts",            # MPEG-TS format
            "-muxrate", "10M",         # Limit mux rate
            "-mpegts_flags", "initial_discontinuity",
            self.srt_url               # SRT output
        ]

        logger.info(f"Starting FFmpeg SRT streamer (video-only): {' '.join(cmd)}")
        logger.info(f"Stream available at: srt://<your-ip>:{self.srt_port}")
        
        try:
            self.ffmpeg_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True
            )

            logger.info(f"✓ SRT stream started on port {self.srt_port}")
            logger.info(f"  Input: {drone_rtsp_url}")
            logger.info(f"  Clients can connect: srt://<your-ip>:{self.srt_port}")

            # Monitor FFmpeg output
            while not self._stop_event.is_set() and self.ffmpeg_process.poll() is None:
                try:
                    line = self.ffmpeg_process.stdout.readline()
                    if line:
                        logger.debug(line.strip())
                except:
                    break
                    
        except Exception as e:
            logger.error(f"Error in video forwarding: {e}")
        finally:
            self.stop()
    
    def _wait_for_drone_video_ready(self, drone_rtsp_url, timeout=30):
        """
        Wait for the drone's video stream to be available.
        
        Args:
            drone_rtsp_url: RTSP URL of the drone's video stream
            timeout: Maximum time to wait in seconds
        """
        import socket
        import urllib.parse
        
        # Parse the RTSP URL to get host and port
        parsed = urllib.parse.urlparse(drone_rtsp_url)
        host = parsed.hostname
        port = parsed.port or 554  # Default RTSP port
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Try to connect to the drone's RTSP port
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(2)
                result = sock.connect_ex((host, port))
                sock.close()
                
                if result == 0:
                    logger.info("✓ Drone video stream is available")
                    return
                    
            except Exception:
                pass
            
            time.sleep(1)
        
        logger.warning("⚠ Drone video stream not available - proceeding anyway")

    def stop(self):
        """Stop the video forwarder."""
        logger.info("Stopping video forwarder...")
        self._stop_event.set()
        
        if self.ffmpeg_process:
            logger.info("Stopping FFmpeg process...")
            self.ffmpeg_process.send_signal(signal.SIGINT)
            try:
                self.ffmpeg_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                logger.warning("FFmpeg did not stop gracefully, killing...")
                self.ffmpeg_process.kill()
            self.ffmpeg_process = None
        
        logger.info("✓ Video forwarder stopped")


if __name__ == "__main__":
    print("VideoForwarder is designed to be used as part of ParrotForwarder")
    print("Usage: python -m parrot_forwarder.main --help")
    sys.exit(1)
