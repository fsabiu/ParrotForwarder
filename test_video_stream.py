#!/usr/bin/env python3
"""
Test script to verify video streaming from Parrot Anafi via USB.
Saves frames to disk for verification (works over SSH).
"""

import olympe
from olympe.video.renderer import PdrawRenderer
import logging
import time
import os
import cv2
import numpy as np
import threading

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

# Drone IP address (USB connection)
DRONE_IP = "192.168.53.1"
OUTPUT_DIR = "/home/gonareva/drone/video_frames"

class FrameRecorder:
    """Handles frame capture using Olympe's callback system"""
    
    def __init__(self, output_dir):
        self.output_dir = output_dir
        self.frame_count = 0
        self.saved_frames = []
        self.last_save_time = time.time()
        self.save_interval = 1.0  # Save one frame per second
        self.lock = threading.Lock()
        os.makedirs(output_dir, exist_ok=True)
        
    def yuv_frame_cb(self, yuv_frame):
        """
        Callback for YUV frames from Olympe
        This is called by Olympe's video streaming system
        """
        with self.lock:
            self.frame_count += 1
            
            # Log first frame
            if self.frame_count == 1:
                logger.info(f"✓ First frame received!")
                yuv_frame.ref()
                info = yuv_frame.info()
                logger.info(f"  Frame info keys: {info.keys()}")
                logger.info(f"  Full info: {info}")
                yuv_frame.unref()
            
            # Save frames periodically
            current_time = time.time()
            if current_time - self.last_save_time >= self.save_interval:
                try:
                    # Reference the frame
                    yuv_frame.ref()
                    
                    # Get the YUV data as ndarray
                    yuv_data = yuv_frame.as_ndarray()
                    
                    if yuv_data is not None:
                        # Get dimensions from the array
                        height, width = yuv_data.shape[:2]
                        
                        # Convert YUV (I420) to BGR for OpenCV
                        # Most Parrot drones use I420 format
                        bgr_frame = cv2.cvtColor(yuv_data, cv2.COLOR_YUV2BGR_I420)
                        
                        # Save the frame
                        filename = f"frame_{len(self.saved_frames)+1:03d}.jpg"
                        filepath = os.path.join(self.output_dir, filename)
                        cv2.imwrite(filepath, bgr_frame)
                        self.saved_frames.append(filepath)
                        
                        logger.info(f"  Frame {len(self.saved_frames)}: {width}x{height} - Saved: {filename}")
                        
                        self.last_save_time = current_time
                    
                    # Unreference the frame
                    yuv_frame.unref()
                    
                except Exception as e:
                    logger.warning(f"  Could not save frame: {e}")
                    import traceback
                    logger.warning(f"  Traceback: {traceback.format_exc()}")
                    try:
                        yuv_frame.unref()
                    except:
                        pass
            
            # Log progress
            if self.frame_count % 30 == 0:
                logger.info(f"  Total frames processed: {self.frame_count}")
    
    def start(self):
        """Called when streaming starts"""
        logger.info("Frame recorder started")
        self.frame_count = 0
        self.saved_frames = []
        
    def stop(self):
        """Called when streaming stops"""
        logger.info(f"Frame recorder stopped - {self.frame_count} frames processed")
        
    def flush(self, *args, **kwargs):
        """Called to flush pending frames"""
        pass

def main():
    logger.info("=" * 60)
    logger.info("Starting Video Stream Test")
    logger.info("=" * 60)
    logger.info(f"Connecting to drone at {DRONE_IP}")
    logger.info(f"Frames will be saved to: {OUTPUT_DIR}")
    
    drone = None
    frame_recorder = FrameRecorder(OUTPUT_DIR)
    
    try:
        # Create drone connection object
        drone = olympe.Drone(DRONE_IP)
        
        logger.info("Connecting to drone...")
        if not drone.connect():
            logger.error("✗ Failed to connect to the drone")
            return 1
        
        logger.info("✓ Connected to drone")
        logger.info("-" * 60)
        
        # Set up video streaming with callback
        logger.info("Setting up video stream with frame callback...")
        
        # Register the YUV frame callback
        drone.streaming.set_callbacks(
            raw_cb=frame_recorder.yuv_frame_cb,
            start_cb=frame_recorder.start,
            end_cb=frame_recorder.stop,
            flush_raw_cb=frame_recorder.flush
        )
        
        # Start streaming
        logger.info("Starting video stream...")
        drone.streaming.start()
        
        logger.info("✓ Video streaming started")
        logger.info("Waiting for frames (10 seconds)...")
        logger.info("-" * 60)
        
        # Let the stream run for 10 seconds
        start_time = time.time()
        timeout = 10
        
        try:
            while time.time() - start_time < timeout:
                time.sleep(0.1)
        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        
        # Get final stats
        logger.info("-" * 60)
        elapsed = time.time() - start_time
        
        with frame_recorder.lock:
            frame_count = frame_recorder.frame_count
            saved_frames = frame_recorder.saved_frames.copy()
        
        if frame_count > 0:
            fps = frame_count / elapsed
            logger.info(f"✓ Video stream test successful!")
            logger.info(f"  Total frames processed: {frame_count}")
            logger.info(f"  Duration: {elapsed:.2f} seconds")
            logger.info(f"  Average FPS: {fps:.2f}")
            logger.info(f"  Frames saved: {len(saved_frames)}")
            
            if saved_frames:
                logger.info(f"\n  Saved frame files:")
                for frame_file in saved_frames:
                    logger.info(f"    - {frame_file}")
        else:
            logger.warning("⚠ No frames received from stream")
            logger.info("  Possible reasons:")
            logger.info("  - Camera may not be active")
            logger.info("  - Drone may need to be powered on longer")
            logger.info("  - Video streaming may require additional setup")
        
        # Stop streaming
        logger.info("-" * 60)
        logger.info("Stopping video stream...")
        drone.streaming.stop()
        
    except Exception as e:
        logger.error(f"✗ Error occurred: {str(e)}")
        logger.exception("Full exception details:")
        return 1
        
    finally:
        # Ensure cleanup
        if drone is not None:
            try:
                logger.info("Disconnecting from drone...")
                drone.disconnect()
                logger.info("✓ Disconnected successfully")
            except:
                pass
    
    logger.info("=" * 60)
    logger.info("Video stream test completed")
    logger.info("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())

