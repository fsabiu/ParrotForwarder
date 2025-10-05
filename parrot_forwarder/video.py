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
    
    def __init__(self, drone, drone_ip, mediamtx_host="localhost", mediamtx_port=8554, stream_path="parrot_stream"):
        """
        Initialize the video forwarder.
        
        Args:
            drone: Olympe drone instance
            drone_ip: IP address of the drone
            mediamtx_host: MediaMTX server host (default: localhost)
            mediamtx_port: MediaMTX RTSP port (default: 8554)
            stream_path: Stream path on MediaMTX server (default: parrot_stream)
        """
        super().__init__(daemon=True)
        #self.drone = drone
        self.drone_ip = drone_ip
        self.mediamtx_host = mediamtx_host
        self.mediamtx_port = mediamtx_port
        self.stream_path = stream_path
        self.rtsp_url = f"rtsp://{mediamtx_host}:{mediamtx_port}/{stream_path}"
        self.ffmpeg_process = None
        self._stop_event = threading.Event()
        #self._streaming_setup = False

    
    def run(self):
        """Main thread execution - forward video stream to MediaMTX."""
        
        # Get the drone's RTSP stream URL
        # The drone typically provides an RTSP stream that we can forward
        drone_rtsp_url = f"rtsp://{self.drone_ip}/live"
        
        # Wait for drone to be ready before starting FFmpeg
        logger.info("Waiting for drone video stream to be available...")
        self._wait_for_drone_video_ready(drone_rtsp_url)

        cmd = [
            "ffmpeg",
            
            # --- INPUT OPTIONS ---
            "-probesize", "2M",
            "-analyzeduration", "2M",
            "-fflags", "nobuffer",      # Drastically reduces input buffer latency
            "-flags", "low_delay",     # Hint for decoders/demuxers
            "-rtsp_transport", "udp",  # Explicitly listen via UDP (default, but good to be clear)
            "-i", drone_rtsp_url,
            
            # --- VIDEO PROCESSING ---
            "-c:v", "copy",             # <--- THE MAGIC KEY! Stream copy the video.
            "-an",                      # Disable audio
            
            # --- OUTPUT OPTIONS ---
            "-f", "rtsp",
            "-rtsp_transport", "tcp",   # Use reliable TCP for the output to MediaMTX
            self.rtsp_url
        ]

        logger.info(f"Starting FFmpeg forwarder: {' '.join(cmd)}")
        
        try:
            self.ffmpeg_process = subprocess.Popen(
                cmd, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT, 
                text=True
            )

            logger.info(f"Video forwarding started: {drone_rtsp_url} → {self.rtsp_url}")

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
