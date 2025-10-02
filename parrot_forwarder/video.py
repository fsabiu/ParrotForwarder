"""
VideoForwarder - Handles video stream reading and forwarding

Reads video frames from drone at specified FPS and prepares for forwarding.
"""

import logging
import time
import threading
import cv2
import numpy as np


class VideoForwarder(threading.Thread):
    """
    Handles reading and forwarding video frames from the drone.
    Runs in a separate thread and processes video frames.
    """
    
    def __init__(self, drone, fps=30, name="VideoForwarder"):
        """
        Initialize the video forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Target frames per second for video forwarding
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.frame_count = 0
        self.forwarded_count = 0
        self.last_forward_time = time.time()
        self.logger = logging.getLogger(f"{__name__}.{name}")
        self.lock = threading.Lock()
        self.latest_frame = None
        
        # Performance tracking
        self.start_time = None
        self.last_stats_time = None
        self.stats_interval = 5.0  # Report stats every 5 seconds
        self.loop_times = []
        self.max_loop_times = 100  # Keep last 100 loop times for stats
        self.frames_received_last_sec = 0
        self.last_frame_count = 0
        
    def yuv_frame_callback(self, yuv_frame):
        """
        Callback for receiving YUV frames from Olympe.
        This runs in Olympe's video thread.
        
        Args:
            yuv_frame: YUV frame from Olympe
        """
        with self.lock:
            self.frame_count += 1
            
            try:
                # Reference the frame
                yuv_frame.ref()
                
                # Convert YUV to BGR
                yuv_data = yuv_frame.as_ndarray()
                if yuv_data is not None:
                    bgr_frame = cv2.cvtColor(yuv_data, cv2.COLOR_YUV2BGR_I420)
                    self.latest_frame = bgr_frame.copy()
                
                # Unreference the frame
                yuv_frame.unref()
                
            except Exception as e:
                self.logger.error(f"Error processing frame: {e}")
                try:
                    yuv_frame.unref()
                except:
                    pass
    
    def forward_frame(self, frame):
        """
        Forward a video frame to external system.
        This is a placeholder - will be implemented later.
        
        Args:
            frame: BGR frame (numpy array)
        """
        # TODO: Implement actual forwarding (H.264 UDP/RTP)
        self.forwarded_count += 1
    
    def log_performance_stats(self):
        """Log performance statistics."""
        current_time = time.time()
        
        if self.start_time is None:
            self.start_time = current_time
            self.last_stats_time = current_time
            self.last_frame_count = self.frame_count
            return
        
        # Check if it's time to report stats
        if current_time - self.last_stats_time >= self.stats_interval:
            elapsed = current_time - self.start_time
            
            # Calculate actual forwarding FPS
            forwarded_fps = self.forwarded_count / elapsed if elapsed > 0 else 0
            
            # Calculate incoming frame rate from drone
            frames_received = self.frame_count - self.last_frame_count
            incoming_fps = frames_received / self.stats_interval
            self.last_frame_count = self.frame_count
            
            # Calculate loop time statistics
            if self.loop_times:
                avg_loop_time = sum(self.loop_times) / len(self.loop_times)
                min_loop_time = min(self.loop_times)
                max_loop_time = max(self.loop_times)
                
                # Check if we're meeting target FPS
                fps_ratio = (forwarded_fps / self.fps) * 100 if self.fps > 0 else 0
                
                status = "✓" if fps_ratio >= 95 else "⚠" if fps_ratio >= 80 else "✗"
                
                self.logger.info(
                    f"{status} PERFORMANCE: "
                    f"Target={self.fps:.1f} fps, Forwarded={forwarded_fps:.2f} fps ({fps_ratio:.1f}%) | "
                    f"Incoming={incoming_fps:.1f} fps, Received={self.frame_count} | "
                    f"Loop: avg={avg_loop_time*1000:.2f}ms, min={min_loop_time*1000:.2f}ms, max={max_loop_time*1000:.2f}ms"
                )
                
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
            
            self.last_stats_time = current_time
    
    def start_callback(self):
        """Called when video streaming starts."""
        self.logger.info("Video stream started")
    
    def stop_callback(self):
        """Called when video streaming stops."""
        self.logger.info(f"Video stream stopped - Processed {self.frame_count} frames")
    
    def flush_callback(self, *args, **kwargs):
        """Called to flush pending frames."""
        pass
    
    def setup_streaming(self):
        """Set up video streaming callbacks."""
        self.logger.info("Setting up video stream callbacks...")
        self.drone.streaming.set_callbacks(
            raw_cb=self.yuv_frame_callback,
            start_cb=self.start_callback,
            end_cb=self.stop_callback,
            flush_raw_cb=self.flush_callback
        )
        self.drone.streaming.start()
        self.logger.info("Video streaming started")
    
    def run(self):
        """Main thread execution loop with precise timing."""
        self.logger.info(f"Started - Target FPS: {self.fps} (interval: {self.interval*1000:.2f}ms)")
        self.running = True
        self.start_time = time.time()
        self.last_stats_time = self.start_time
        
        # Wait for frames to start arriving
        time.sleep(1)
        
        # Use target time instead of sleep-based timing for better precision
        next_frame_time = time.time()
        
        while self.running:
            try:
                loop_start = time.time()
                
                # Get latest frame
                with self.lock:
                    frame = self.latest_frame
                
                # Forward frame if available
                if frame is not None:
                    self.forward_frame(frame)
                
                # Track loop time
                loop_time = time.time() - loop_start
                self.loop_times.append(loop_time)
                if len(self.loop_times) > self.max_loop_times:
                    self.loop_times.pop(0)
                
                # Log performance stats periodically
                self.log_performance_stats()
                
                # Calculate next target time
                next_frame_time += self.interval
                current_time = time.time()
                sleep_time = next_frame_time - current_time
                
                if sleep_time > 0:
                    # Sleep until next frame time
                    time.sleep(sleep_time)
                else:
                    # We're falling behind - reset timing to avoid spiral
                    if sleep_time < -self.interval:
                        self.logger.warning(
                            f"Fell behind by {-sleep_time*1000:.2f}ms - resetting timing"
                        )
                        next_frame_time = time.time()
                    
                    # Warn if we can't keep up
                    if self.forwarded_count > 0 and self.forwarded_count % self.fps == 0:  # Once per second
                        self.logger.warning(
                            f"Cannot maintain {self.fps} fps - loop took {loop_time*1000:.2f}ms "
                            f"(target: {self.interval*1000:.2f}ms)"
                        )
                
            except KeyboardInterrupt:
                self.logger.info("⚠ Interrupted by user")
                self.running = False
                break
            except Exception as e:
                self.logger.error(f"Error in video forwarding loop: {e}")
                next_frame_time = time.time() + self.interval
                time.sleep(self.interval)
        
        # Final stats
        if self.start_time:
            total_elapsed = time.time() - self.start_time
            final_fps = self.forwarded_count / total_elapsed if total_elapsed > 0 else 0
            self.logger.info(
                f"Stopped - Forwarded {self.forwarded_count} frames, Received {self.frame_count} frames | "
                f"Average forwarding FPS: {final_fps:.2f} (target: {self.fps})"
            )
    
    def stop(self):
        """Stop the video forwarder."""
        self.running = False
        self.logger.info("Stopped")

