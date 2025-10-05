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
        

        # cmd = [
        #     "ffmpeg",
            
        #     # --- INPUT OPTIONS (UDP Fortification) ---
        #     # We are NOT using -rtsp_transport tcp here.
        #     # Instead, we give ffmpeg bigger buffers to handle UDP packet loss.
        #     "-probesize", "5M",         # Analyze up to 5MB of data to find stream info
        #     "-analyzeduration", "5M",   # Analyze up to 5 seconds of data
        #     "-buffer_size", "10M",      # Increase the input buffer size
        #     "-i", drone_rtsp_url,       # Your input stream (will default to UDP)
            
        #     # --- VIDEO PROCESSING OPTIONS (Still critical for cleanup) ---
        #     "-c:v", "libx264",          # Re-encode with x264
        #     "-preset", "ultrafast",     # Lowest CPU usage to guarantee real-time performance
        #     "-tune", "zerolatency",     # Optimize for streaming
        #     "-g", "15",                 # Force a keyframe every 15 frames (~0.5s). This will aggressively clean up any visual errors that get through.
        #     "-an",                      # Disable audio processing
            
        #     # --- OUTPUT OPTIONS (We STILL use TCP here for reliability) ---
        #     "-f", "rtsp",
        #     "-rtsp_transport", "tcp",   # Use TCP for the output to MediaMTX. This part is reliable.
        #     self.rtsp_url
        # ]

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
