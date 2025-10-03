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
        self.re_encode = True

    def setup_streaming(self):
        """Set up video streaming from the drone."""
        if not self._streaming_setup:
            logger.info("Setting up video streaming...")
            try:
                # Note: We don't use drone.streaming.start() here because it causes
                # H264/AVCC format compatibility issues with the Olympe video decoder.
                # Instead, we use direct RTSP streaming via FFmpeg which handles
                # the format conversion automatically.
                self._streaming_setup = True
                logger.info("✓ Video streaming setup complete (using direct RTSP)")
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
        
        # Base command for input
        cmd = [
            "ffmpeg",
            "-rtsp_transport", "tcp",  # Use TCP for a more reliable input connection
            "-i", drone_rtsp_url,
        ]

        if self.re_encode:
            # Re-encoding command: inserts keyframes for smooth viewing, but uses more CPU.
            cmd.extend([
                "-c:v", "libx264",        # Use the H.264 encoder
                "-preset", "ultrafast",   # Prioritize speed to reduce latency
                "-tune", "zerolatency",   # Optimize for real-time streaming
                "-g", "30",               # Insert a keyframe every 30 frames (e.g., every second for 30fps)
                "-an",                    # No audio
            ])
        else:
            # Original copy command: very low CPU, but inherits keyframe issues from the source.
            cmd.extend([
                "-c", "copy",
            ])

        # Output command
        cmd.extend([
            "-f", "rtsp",
            "-rtsp_transport", "tcp",
            self.rtsp_url
        ])

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
        
        # Note: We don't need to stop drone streaming since we're using direct RTSP
        # and not the Olympe streaming API
        
        logger.info("✓ Video forwarder stopped")


if __name__ == "__main__":
    print("VideoForwarder is designed to be used as part of ParrotForwarder")
    print("Usage: python -m parrot_forwarder.main --help")
    sys.exit(1)
