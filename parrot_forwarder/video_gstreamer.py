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
    
    def __init__(self, drone_ip, srt_port=8890, klv_port=12345):
        """
        Initialize the video forwarder.
        
        Args:
            drone_ip: IP address of the drone
            srt_port: Port for SRT output stream
            klv_port: Local UDP port for KLV telemetry data
        """
        super().__init__(daemon=True)
        self.drone_ip = drone_ip
        self.srt_port = srt_port
        self.klv_port = klv_port
        self.srt_url = f"srt://0.0.0.0:{srt_port}?mode=listener"
        self.gst_process = None
        self._stop_event = threading.Event()

    
    def run(self):
        """Main thread execution - forward video stream and KLV data via GStreamer."""
        
        drone_rtsp_url = f"rtsp://{self.drone_ip}/live"
        
        # Wait for drone to be ready before starting GStreamer
        logger.info("Waiting for drone video stream to be available...")
        self._wait_for_drone_video_ready(drone_rtsp_url)
        
        logger.info(f"Streaming video from {drone_rtsp_url} via SRT")
        logger.info(f"Muxing with KLV data from localhost:{self.klv_port}")
        
        # GStreamer pipeline:
        # 1. rtspsrc: Read RTSP video from drone
        # 2. rtph264depay: Depacketize RTP H.264
        # 3. h264parse: Parse H.264 stream
        # 4. udpsrc: Read raw KLV data from Python
        # 5. mpegtsmux: Mux video and KLV data into single TS
        # 6. srtsink: Output to SRT
        
        pipeline = (
            # Video source from drone
            f"rtspsrc location={drone_rtsp_url} protocols=udp latency=200 ! "
            "application/x-rtp,media=video,encoding-name=H264 ! "
            "rtph264depay ! "
            "h264parse ! "
            "video/x-h264,stream-format=byte-stream,alignment=au ! "
            "queue max-size-buffers=0 max-size-time=0 max-size-bytes=0 ! "
            "mux. "
            
            # KLV data source (raw KLV from Python)
            f"udpsrc port={self.klv_port} ! "
            "meta/x-klv,parsed=true ! "
            "queue ! "
            "mux. "
            
            # Mux and output
            "mpegtsmux name=mux alignment=7 ! "
            f"srtsink uri=\"{self.srt_url}\" latency=200 mode=listener"
        )
        
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
            
            logger.info(f"✓ SRT stream started on port {self.srt_port}")
            logger.info(f"  Input: {drone_rtsp_url}")
            logger.info(f"  Clients can connect: srt://<your-ip>:{self.srt_port}")
            
            # Monitor GStreamer output
            while not self._stop_event.is_set():
                if self.gst_process.poll() is not None:
                    # Process terminated
                    stdout, stderr = self.gst_process.communicate()
                    logger.error(f"GStreamer process terminated unexpectedly")
                    logger.error(f"STDOUT: {stdout}")
                    logger.error(f"STDERR: {stderr}")
                    break
                time.sleep(1)
                
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

