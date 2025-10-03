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
        self.drone = drone
        self.drone_ip = drone_ip
        self.mediamtx_host = mediamtx_host
        self.mediamtx_port = mediamtx_port
        self.stream_path = stream_path
        self.rtsp_url = f"rtsp://{mediamtx_host}:{mediamtx_port}/{stream_path}"
        self.ffmpeg_process = None
        self._stop_event = threading.Event()
        self._streaming_setup = False

    def setup_streaming(self):
        """Set up video streaming from the drone."""
        if not self._streaming_setup:
            logger.info("Setting up video streaming...")
            try:
                # Start video streaming from drone
                self.drone.streaming.start()
                self._streaming_setup = True
                logger.info("✓ Video streaming setup complete")
            except Exception as e:
                logger.error(f"Failed to setup video streaming: {e}")
                raise
    
    def run(self):
        """Main thread execution - forward video stream to MediaMTX."""
        if not self._streaming_setup:
            logger.error("Video streaming not setup. Call setup_streaming() first.")
            return
        
        # Get the drone's RTSP stream URL
        # The drone typically provides an RTSP stream that we can forward
        drone_rtsp_url = f"rtsp://{self.drone_ip}/live"
        
        cmd = [
            "ffmpeg",
            "-re",
            "-an",
            "-rtsp_transport", "tcp",
            "-i", drone_rtsp_url,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-tune", "zerolatency",
            "-profile:v", "baseline", 
            "-crf", "28",
            # better efficiency (if your client supports it)
            "-maxrate", "1000",
            "-bufsize", "2000",
            "-g", "30",                   # force I-frame every 0.5s
            "-keyint_min", "30",
            "-c:a", "aac",
            "-f", "rtsp",
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
        
        # Stop drone streaming
        if self.drone and hasattr(self.drone, 'streaming'):
            try:
                self.drone.streaming.stop()
            except Exception as e:
                logger.debug(f"Note: Error stopping drone stream: {e}")
        
        logger.info("✓ Video forwarder stopped")


if __name__ == "__main__":
    print("VideoForwarder is designed to be used as part of ParrotForwarder")
    print("Usage: python -m parrot_forwarder.main --help")
    sys.exit(1)
