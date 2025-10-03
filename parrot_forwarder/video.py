"""
VideoForwarder - Handles H.264 video stream forwarding via MediaMTX

Forwards H.264 encoded video frames from the drone to MediaMTX server
using RTSP protocol for distribution to remote clients.
"""

import logging
import time
import threading
import subprocess
import os
import signal
import tempfile
import queue
from datetime import datetime


class VideoForwarder(threading.Thread):
    """
    Handles H.264 video stream forwarding from the drone to MediaMTX server.
    
    Receives H.264 encoded frames directly from the drone and forwards them
    to MediaMTX server via RTSP for distribution to remote clients.
    
    Uses FFmpeg to handle the RTSP streaming to MediaMTX.
    """
    
    def __init__(self, drone, fps=30, mediamtx_host='localhost', mediamtx_port=8554, 
                 stream_path='parrot_stream', name="VideoForwarder"):
        """
        Initialize the video forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Target frames per second for video forwarding
            mediamtx_host: MediaMTX server host (default: localhost)
            mediamtx_port: MediaMTX RTSP port (default: 8554)
            stream_path: Stream path on MediaMTX server (default: parrot_stream)
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.logger = logging.getLogger(f"{__name__}.{name}")
        
        # MediaMTX configuration
        self.mediamtx_host = mediamtx_host
        self.mediamtx_port = mediamtx_port
        self.stream_path = stream_path
        self.rtsp_url = f"rtsp://{mediamtx_host}:{mediamtx_port}/{stream_path}"
        
        # Debug logging
        self.logger.info(f"DEBUG: VideoForwarder.__init__ - mediamtx_host={mediamtx_host}, "
                        f"mediamtx_port={mediamtx_port}, stream_path={stream_path}")
        self.logger.info(f"RTSP URL: {self.rtsp_url}")
        
        # FFmpeg process management
        self.ffmpeg_process = None
        self.ffmpeg_input_pipe = None
        self.ffmpeg_ready = False
        
        # Frame tracking
        self.frames_received = 0
        self.frames_forwarded = 0
        self.frames_dropped = 0  # Dropped due to rate limiting
        self.last_forward_time = 0
        
        # Performance tracking
        self.start_time = None
        self.last_stats_time = None
        self.stats_interval = 5.0  # Report stats every 5 seconds
        self.last_frame_count = 0
        
        # Bandwidth tracking
        self.bytes_sent = 0
        self.bytes_received = 0
        self.last_bytes_sent = 0
        self.send_errors = 0
        
        # Frame size tracking
        self.frame_sizes = []
        self.max_frame_sizes = 100  # Keep last 100 frame sizes
        
        # H.264 SPS/PPS caching for stream initialization
        self.cached_sps_pps = []  # Cache SPS/PPS frames
        self.has_sent_initial_sps_pps = False
        
        # Frame queue for buffering
        self.frame_queue = queue.Queue(maxsize=10)  # Small buffer to prevent memory issues
        
    def setup_ffmpeg_stream(self):
        """
        Set up FFmpeg process to stream to MediaMTX server.
        
        Creates a named pipe and FFmpeg process that reads H.264 data
        and streams it to MediaMTX via RTSP.
        """
        try:
            self.logger.info("Setting up FFmpeg stream to MediaMTX...")
            
            # Create a named pipe for H.264 data
            self.pipe_path = tempfile.mktemp(suffix='.h264')
            os.mkfifo(self.pipe_path)
            self.logger.info(f"Created named pipe: {self.pipe_path}")
            
            # FFmpeg command to read H.264 from pipe and stream to MediaMTX
            ffmpeg_cmd = [
                'ffmpeg',
                '-f', 'h264',           # Input format: raw H.264
                '-i', self.pipe_path,   # Input: named pipe
                '-c:v', 'copy',         # Copy video codec (no re-encoding)
                '-f', 'rtsp',           # Output format: RTSP
                '-rtsp_transport', 'tcp',  # Use TCP for reliability
                '-muxdelay', '0.1',     # Reduce muxing delay
                '-muxpreload', '0.1',   # Reduce muxing preload
                self.rtsp_url           # Output: MediaMTX RTSP URL
            ]
            
            self.logger.info(f"FFmpeg command: {' '.join(ffmpeg_cmd)}")
            
            # Start FFmpeg process
            self.ffmpeg_process = subprocess.Popen(
                ffmpeg_cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0  # Unbuffered
            )
            
            # Open the named pipe for writing
            self.ffmpeg_input_pipe = open(self.pipe_path, 'wb')
            self.ffmpeg_ready = True
            
            self.logger.info(f"✓ FFmpeg process started (PID: {self.ffmpeg_process.pid})")
            self.logger.info(f"✓ Streaming to MediaMTX: {self.rtsp_url}")
            
            # Wait a moment for FFmpeg to initialize
            time.sleep(1)
            
        except Exception as e:
            self.logger.error(f"✗ Failed to setup FFmpeg stream: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            self.cleanup_ffmpeg()
            raise
    
    def cleanup_ffmpeg(self):
        """Clean up FFmpeg process and resources."""
        self.ffmpeg_ready = False
        
        # Close input pipe
        if self.ffmpeg_input_pipe:
            try:
                self.ffmpeg_input_pipe.close()
            except:
                pass
            self.ffmpeg_input_pipe = None
        
        # Terminate FFmpeg process
        if self.ffmpeg_process:
            try:
                # Send SIGTERM first
                self.ffmpeg_process.terminate()
                
                # Wait for graceful shutdown
                try:
                    self.ffmpeg_process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    # Force kill if it doesn't stop gracefully
                    self.ffmpeg_process.kill()
                    self.ffmpeg_process.wait()
                
                self.logger.info("✓ FFmpeg process terminated")
            except Exception as e:
                self.logger.warning(f"Error terminating FFmpeg: {e}")
            finally:
                self.ffmpeg_process = None
        
        # Remove named pipe
        if hasattr(self, 'pipe_path') and os.path.exists(self.pipe_path):
            try:
                os.unlink(self.pipe_path)
                self.logger.info(f"✓ Removed named pipe: {self.pipe_path}")
            except Exception as e:
                self.logger.warning(f"Error removing named pipe: {e}")
    
    def h264_frame_callback(self, h264_frame):
        """
        Callback for receiving H.264 encoded frames from Olympe.
        This runs in Olympe's video thread - keep it fast!
        
        Args:
            h264_frame: H.264 VideoFrame from Olympe
        """
        self.frames_received += 1
        
        try:
            # Get H.264 data as 1D numpy array (bytes)
            h264_data = h264_frame.as_ndarray()
            
            if h264_data is not None and len(h264_data) > 0:
                # CRITICAL: Make a complete copy IMMEDIATELY
                # The frame buffer is only valid during this callback
                h264_bytes = h264_data.tobytes()  # Creates a copy
                frame_size = len(h264_bytes)
                self.bytes_received += frame_size
                
                # Check NAL type for SPS/PPS handling
                nal_type = self.get_nal_type(h264_bytes)
                
                # Debug: log first 20 frames' NAL types
                if self.frames_received <= 20:
                    nal_type_str = {
                        1: 'P-frame', 5: 'IDR-frame', 6: 'SEI', 
                        7: 'SPS', 8: 'PPS', 9: 'AUD'
                    }.get(nal_type, f'type-{nal_type}' if nal_type else 'unknown')
                    self.logger.info(f"DEBUG: Frame #{self.frames_received} - NAL type: {nal_type_str} | Size: {frame_size}B")
                
                # Cache SPS/PPS frames
                if nal_type in (7, 8):  # SPS or PPS
                    self.cache_sps_pps(h264_bytes)
                
                # Apply rate limiting for non-SPS/PPS frames
                if nal_type not in (7, 8):  # Not SPS or PPS
                    current_time = time.time()
                    time_since_last = current_time - self.last_forward_time
                    
                    if time_since_last < self.interval:
                        self.frames_dropped += 1
                        return
                    
                    self.last_forward_time = current_time
                
                # Forward frame to FFmpeg
                self.forward_h264_frame(h264_bytes, frame_size)
            
        except Exception as e:
            self.logger.error(f"Error in H.264 callback: {e}")
            import traceback
            self.logger.error(f"Traceback: {traceback.format_exc()}")
    
    def get_nal_type(self, h264_bytes):
        """
        Get the NAL unit type from H.264 data.
        
        Args:
            h264_bytes: bytes containing H.264 data
            
        Returns:
            int: NAL unit type (7=SPS, 8=PPS, 5=IDR, 1=P-frame, etc.) or None if invalid
        """
        try:
            if len(h264_bytes) < 5:
                return None
            
            # Find start code
            if h264_bytes[0] == 0 and h264_bytes[1] == 0:
                if h264_bytes[2] == 0 and h264_bytes[3] == 1:
                    # 4-byte start code
                    nal_byte = h264_bytes[4]
                elif h264_bytes[2] == 1:
                    # 3-byte start code
                    nal_byte = h264_bytes[3]
                else:
                    return None
                    
                # NAL type is in bits 0-4 (mask with 0x1F)
                nal_type = nal_byte & 0x1F
                return nal_type
                
            return None
        except Exception as e:
            self.logger.debug(f"Error parsing NAL type: {e}")
            return None
    
    def cache_sps_pps(self, h264_bytes):
        """
        Cache SPS/PPS frames for stream initialization.
        
        Args:
            h264_bytes: bytes containing H.264 SPS/PPS data
        """
        nal_type = self.get_nal_type(h264_bytes)
        
        if nal_type == 7:  # SPS
            # Replace cached SPS (start fresh)
            self.cached_sps_pps = [h264_bytes]
            self.logger.info(f"✓ Cached SPS (Sequence Parameter Set) - {len(h264_bytes)} bytes")
        elif nal_type == 8:  # PPS
            # Add PPS to cache (after SPS)
            self.cached_sps_pps.append(h264_bytes)
            self.logger.info(f"✓ Cached PPS (Picture Parameter Set) - {len(h264_bytes)} bytes")
    
    def send_initial_sps_pps(self):
        """Send cached SPS/PPS frames to initialize the stream."""
        if not self.cached_sps_pps or not self.ffmpeg_ready:
            return
        
        try:
            for sps_pps_data in self.cached_sps_pps:
                self.ffmpeg_input_pipe.write(sps_pps_data)
                self.ffmpeg_input_pipe.flush()
                self.bytes_sent += len(sps_pps_data)
            
            if not self.has_sent_initial_sps_pps:
                self.logger.info(f"✓ Sent initial SPS/PPS to MediaMTX stream")
                self.has_sent_initial_sps_pps = True
            
        except Exception as e:
            self.logger.warning(f"Error sending initial SPS/PPS: {e}")
    
    def forward_h264_frame(self, h264_bytes, frame_size):
        """
        Forward an H.264 frame to MediaMTX via FFmpeg.
        
        Args:
            h264_bytes: bytes containing H.264 data
            frame_size: size of the frame in bytes
        """
        if not self.ffmpeg_ready or not self.ffmpeg_input_pipe:
            return
        
        try:
            # Send initial SPS/PPS if we haven't yet
            if not self.has_sent_initial_sps_pps and self.cached_sps_pps:
                self.send_initial_sps_pps()
            
            # Write frame to FFmpeg input pipe
            self.ffmpeg_input_pipe.write(h264_bytes)
            self.ffmpeg_input_pipe.flush()
            
            # Track statistics
            self.frames_forwarded += 1
            self.bytes_sent += len(h264_bytes)
            self.frame_sizes.append(frame_size)
            if len(self.frame_sizes) > self.max_frame_sizes:
                self.frame_sizes.pop(0)
            
            # Log first few frames and every 100th frame for debugging
            if self.frames_forwarded <= 10 or self.frames_forwarded % 100 == 0:
                nal_type = self.get_nal_type(h264_bytes)
                nal_type_str = {
                    1: 'P-frame', 5: 'IDR-frame', 6: 'SEI', 
                    7: 'SPS', 8: 'PPS', 9: 'AUD'
                }.get(nal_type, f'type-{nal_type}' if nal_type else 'unknown')
                self.logger.info(
                    f"✓ Forwarded H.264 frame #{self.frames_forwarded} ({nal_type_str}) to MediaMTX "
                    f"({frame_size} bytes)"
                )
            
        except Exception as e:
            self.send_errors += 1
            if self.send_errors <= 5:
                self.logger.error(f"✗ Error forwarding frame to MediaMTX: {e}")
                # Check if FFmpeg process is still running
                if self.ffmpeg_process and self.ffmpeg_process.poll() is not None:
                    self.logger.error("FFmpeg process has terminated unexpectedly")
                    self.cleanup_ffmpeg()
    
    def log_performance_stats(self):
        """Log comprehensive performance statistics."""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
            self.last_stats_time = current_time
            self.last_frame_count = self.frames_received
            self.last_bytes_sent = self.bytes_sent
            return
        
        # Check if it's time to report stats
        if current_time - self.last_stats_time >= self.stats_interval:
            elapsed = current_time - self.start_time
            period = current_time - self.last_stats_time
            
            # Calculate FPS metrics
            received_fps = self.frames_received / elapsed if elapsed > 0 else 0
            forwarded_fps = self.frames_forwarded / elapsed if elapsed > 0 else 0
            
            # Calculate incoming frame rate (last period)
            frames_this_period = self.frames_received - self.last_frame_count
            incoming_fps = frames_this_period / period if period > 0 else 0
            self.last_frame_count = self.frames_received
            
            # Calculate bandwidth
            bytes_this_period = self.bytes_sent - self.last_bytes_sent
            bandwidth_mbps = (bytes_this_period * 8 / period / 1_000_000) if period > 0 else 0
            self.last_bytes_sent = self.bytes_sent
            
            # Frame size statistics
            if self.frame_sizes:
                avg_frame_size = sum(self.frame_sizes) / len(self.frame_sizes)
                min_frame_size = min(self.frame_sizes)
                max_frame_size = max(self.frame_sizes)
            else:
                avg_frame_size = min_frame_size = max_frame_size = 0
            
            # Check if we're meeting target FPS
            fps_ratio = (forwarded_fps / self.fps) * 100 if self.fps > 0 else 0
            status = "✓" if fps_ratio >= 95 else "⚠" if fps_ratio >= 80 else "✗"
            
            # Build performance message
            perf_msg = (
                f"{status} PERFORMANCE: "
                f"Target={self.fps:.1f} fps, Forwarded={forwarded_fps:.2f} fps ({fps_ratio:.1f}%) | "
                f"Incoming={incoming_fps:.1f} fps, Received={self.frames_received} | "
                f"Dropped={self.frames_dropped} frames"
            )
            
            # Add bandwidth and frame size info
            perf_msg += (
                f" | Bandwidth: {bandwidth_mbps:.2f} Mbps | "
                f"Frame: avg={avg_frame_size/1024:.1f}KB, min={min_frame_size/1024:.1f}KB, max={max_frame_size/1024:.1f}KB | "
                f"MediaMTX: sent={self.frames_forwarded}, errors={self.send_errors}"
            )
            
            self.logger.info(perf_msg)
            
            # Warn if we're falling behind
            if fps_ratio < 95:
                self.logger.warning(
                    f"Video forwarding is running at {fps_ratio:.1f}% of target FPS! "
                    f"Target: {self.fps} fps, Actual: {forwarded_fps:.2f} fps"
                )
            
            # Warn if incoming frame rate is too low
            if incoming_fps < self.fps * 0.8:
                self.logger.warning(
                    f"Incoming frame rate ({incoming_fps:.1f} fps) is lower than target ({self.fps} fps)"
                )
            
            # Warn about high error rate
            if self.send_errors > 0 and self.frames_forwarded > 0:
                error_rate = (self.send_errors / self.frames_forwarded) * 100
                if error_rate > 1:
                    self.logger.warning(
                        f"High MediaMTX send error rate: {error_rate:.1f}% ({self.send_errors}/{self.frames_forwarded})"
                    )
            
            self.last_stats_time = current_time
    
    def start_callback(self):
        """Called when video streaming starts."""
        self.logger.info("H.264 video stream started")
    
    def stop_callback(self):
        """Called when video streaming stops."""
        self.logger.info(f"H.264 video stream stopped - Received {self.frames_received} frames")
    
    def flush_h264_callback(self, *args, **kwargs):
        """Called to flush pending H.264 frames."""
        pass
    
    def setup_streaming(self):
        """Set up H.264 video streaming callbacks and MediaMTX connection."""
        try:
            self.logger.info("Setting up H.264 video stream callbacks...")
            
            # Set up MediaMTX streaming first
            self.setup_ffmpeg_stream()
            
            # Use bytestream format (with start codes) for standard H.264
            self.drone.streaming.set_callbacks(
                h264_bytestream_cb=self.h264_frame_callback,
                start_cb=self.start_callback,
                end_cb=self.stop_callback,
                flush_h264_cb=self.flush_h264_callback
            )
            self.logger.info("Using H.264 bytestream format")
            self.logger.info("Starting H.264 video stream...")
            self.drone.streaming.start()
            self.logger.info("✓ H.264 video streaming started - forwarding to MediaMTX")
            
        except Exception as e:
            import traceback
            self.logger.error(f"✗ Failed to setup video streaming: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            self.cleanup_ffmpeg()
            raise
    
    def run(self):
        """Main thread execution loop for statistics monitoring."""
        self.logger.info(f"Started - Target FPS: {self.fps} (H.264 MediaMTX forwarding)")
        self.logger.info(f"Stream URL: {self.rtsp_url}")
        self.running = True
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        self.last_forward_time = self.start_time
        
        # This thread just monitors and logs statistics
        # Actual forwarding happens in the h264_frame_callback
        while self.running:
            try:
                # Log performance stats periodically
                self.log_performance_stats()
                
                # Check if FFmpeg process is still running
                if self.ffmpeg_process and self.ffmpeg_process.poll() is not None:
                    self.logger.error("FFmpeg process terminated unexpectedly")
                    self.cleanup_ffmpeg()
                    break
                
                # Sleep until next stats interval
                time.sleep(1)
                
            except KeyboardInterrupt:
                self.logger.info("⚠ Interrupted by user")
                self.running = False
                break
            except Exception as e:
                self.logger.error(f"Error in video monitoring loop: {e}")
                time.sleep(1)
        
        # Final stats
        if self.start_time:
            total_elapsed = time.time() - self.start_time
            final_received_fps = self.frames_received / total_elapsed if total_elapsed > 0 else 0
            final_forwarded_fps = self.frames_forwarded / total_elapsed if total_elapsed > 0 else 0
            fps_ratio = (final_forwarded_fps / self.fps) * 100 if self.fps > 0 else 0
            total_bandwidth = (self.bytes_sent * 8 / total_elapsed / 1_000_000) if total_elapsed > 0 else 0
            
            self.logger.info(
                f"Stopped - Received {self.frames_received} frames ({final_received_fps:.2f} fps) | "
                f"Forwarded {self.frames_forwarded} frames ({final_forwarded_fps:.2f} fps, {fps_ratio:.1f}% of target) | "
                f"Dropped {self.frames_dropped} frames | "
                f"Average bandwidth: {total_bandwidth:.2f} Mbps | "
                f"Total data sent: {self.bytes_sent / (1024*1024):.2f} MB"
            )
            
            if self.frames_forwarded > 0:
                self.logger.info(f"Final performance: {fps_ratio:.1f}% of target ({self.fps} fps)")
                self.logger.info(f"Stream available at: {self.rtsp_url}")
    
    def stop(self):
        """Stop the video forwarder and cleanup resources."""
        self.running = False
        self.cleanup_ffmpeg()
        self.logger.info("Stopped")