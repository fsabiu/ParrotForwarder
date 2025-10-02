#!/usr/bin/env python3
"""
Video stream sender for Parrot Anafi via USB.
Captures frames from the drone and sends them over UDP to a remote receiver.
"""

import olympe
from olympe.video.renderer import PdrawRenderer
import logging
import time
import socket
import cv2
import numpy as np
import threading
import argparse
import struct

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

# Drone IP address (USB connection)
DRONE_IP = "192.168.53.1"

# Maximum UDP packet size (leave some room for headers)
MAX_PACKET_SIZE = 65000


class VideoSender:
    """Handles frame capture and UDP transmission"""
    
    def __init__(self, remote_host, remote_port, quality=85, max_width=1280):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.quality = quality
        self.max_width = max_width
        self.frame_count = 0
        self.sent_count = 0
        self.lock = threading.Lock()
        self.running = False
        
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info(f"UDP sender configured for {remote_host}:{remote_port}")
        
    def yuv_frame_cb(self, yuv_frame):
        """
        Callback for YUV frames from Olympe
        Converts to JPEG and sends via UDP
        """
        if not self.running:
            return
            
        with self.lock:
            self.frame_count += 1
            
            # Log first frame
            if self.frame_count == 1:
                logger.info(f"✓ First frame received!")
            
            try:
                # Reference the frame
                yuv_frame.ref()
                
                # Get the YUV data as ndarray
                yuv_data = yuv_frame.as_ndarray()
                
                if yuv_data is not None:
                    # Get dimensions from the array
                    height, width = yuv_data.shape[:2]
                    
                    # Convert YUV (I420) to BGR for OpenCV
                    bgr_frame = cv2.cvtColor(yuv_data, cv2.COLOR_YUV2BGR_I420)
                    
                    # Resize if needed to reduce bandwidth
                    if width > self.max_width:
                        scale = self.max_width / width
                        new_width = self.max_width
                        new_height = int(height * scale)
                        bgr_frame = cv2.resize(bgr_frame, (new_width, new_height))
                    
                    # Encode as JPEG
                    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), self.quality]
                    result, encoded_frame = cv2.imencode('.jpg', bgr_frame, encode_param)
                    
                    if result:
                        frame_data = encoded_frame.tobytes()
                        frame_size = len(frame_data)
                        
                        # Send frame over UDP with fragmentation if needed
                        self._send_frame(frame_data)
                        self.sent_count += 1
                        
                        if self.sent_count == 1:
                            logger.info(f"✓ First frame sent ({frame_size} bytes)")
                        elif self.sent_count % 30 == 0:
                            logger.info(f"  Sent {self.sent_count} frames")
                
                # Unreference the frame
                yuv_frame.unref()
                
            except Exception as e:
                logger.warning(f"  Could not process/send frame: {e}")
                try:
                    yuv_frame.unref()
                except:
                    pass
    
    def _send_frame(self, frame_data):
        """
        Send frame data over UDP with fragmentation support
        Protocol: [frame_id:4][total_chunks:2][chunk_id:2][data:N]
        """
        frame_size = len(frame_data)
        
        # Calculate number of chunks needed
        chunk_size = MAX_PACKET_SIZE - 8  # 4 bytes frame_id + 2 bytes total_chunks + 2 bytes chunk_id
        total_chunks = (frame_size + chunk_size - 1) // chunk_size
        
        frame_id = self.sent_count
        
        # Send each chunk
        for chunk_id in range(total_chunks):
            start = chunk_id * chunk_size
            end = min(start + chunk_size, frame_size)
            chunk_data = frame_data[start:end]
            
            # Build packet: frame_id (4 bytes) + total_chunks (2 bytes) + chunk_id (2 bytes) + data
            packet = struct.pack('!IHH', frame_id, total_chunks, chunk_id) + chunk_data
            
            try:
                self.sock.sendto(packet, (self.remote_host, self.remote_port))
            except Exception as e:
                logger.error(f"Failed to send packet: {e}")
                break
    
    def start(self):
        """Called when streaming starts"""
        logger.info("Video sender started")
        self.running = True
        self.frame_count = 0
        self.sent_count = 0
        
    def stop(self):
        """Called when streaming stops"""
        logger.info(f"Video sender stopped - {self.sent_count} frames sent")
        self.running = False
        
    def flush(self, *args, **kwargs):
        """Called to flush pending frames"""
        pass
    
    def close(self):
        """Close the UDP socket"""
        self.sock.close()


def main():
    parser = argparse.ArgumentParser(
        description='Stream video from Parrot Anafi drone over UDP',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--host',
        type=str,
        required=True,
        help='Remote host IP address to send video to'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5001,
        help='Remote UDP port to send video to'
    )
    parser.add_argument(
        '--drone-ip',
        type=str,
        default=DRONE_IP,
        help='Drone IP address (USB connection)'
    )
    parser.add_argument(
        '--quality',
        type=int,
        default=85,
        help='JPEG quality (1-100, higher is better)'
    )
    parser.add_argument(
        '--max-width',
        type=int,
        default=1280,
        help='Maximum frame width (frames will be scaled down if larger)'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Streaming duration in seconds (0 for infinite)'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting Video Stream UDP Sender")
    logger.info("=" * 60)
    logger.info(f"Connecting to drone at {args.drone_ip}")
    logger.info(f"Sending video to {args.host}:{args.port}")
    logger.info(f"JPEG Quality: {args.quality}, Max Width: {args.max_width}px")
    
    drone = None
    video_sender = VideoSender(args.host, args.port, args.quality, args.max_width)
    
    try:
        # Create drone connection object
        drone = olympe.Drone(args.drone_ip)
        
        logger.info("Connecting to drone...")
        if not drone.connect():
            logger.error("✗ Failed to connect to the drone")
            return 1
        
        logger.info("✓ Connected to drone")
        logger.info("-" * 60)
        
        # Set up video streaming with callback
        logger.info("Setting up video stream...")
        
        # Register the YUV frame callback
        drone.streaming.set_callbacks(
            raw_cb=video_sender.yuv_frame_cb,
            start_cb=video_sender.start,
            end_cb=video_sender.stop,
            flush_raw_cb=video_sender.flush
        )
        
        # Start streaming
        logger.info("Starting video stream...")
        drone.streaming.start()
        
        logger.info("✓ Video streaming started")
        logger.info(f"Streaming for {args.duration if args.duration > 0 else 'infinite'} seconds...")
        logger.info("Press Ctrl+C to stop")
        logger.info("-" * 60)
        
        # Let the stream run
        start_time = time.time()
        
        try:
            while True:
                time.sleep(0.1)
                if args.duration > 0 and (time.time() - start_time) >= args.duration:
                    break
        except KeyboardInterrupt:
            logger.info("\nInterrupted by user")
        
        # Get final stats
        logger.info("-" * 60)
        elapsed = time.time() - start_time
        
        with video_sender.lock:
            frame_count = video_sender.frame_count
            sent_count = video_sender.sent_count
        
        if sent_count > 0:
            fps = sent_count / elapsed
            logger.info(f"✓ Video streaming completed!")
            logger.info(f"  Total frames processed: {frame_count}")
            logger.info(f"  Total frames sent: {sent_count}")
            logger.info(f"  Duration: {elapsed:.2f} seconds")
            logger.info(f"  Average FPS: {fps:.2f}")
        else:
            logger.warning("⚠ No frames sent")
        
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
        video_sender.close()
        if drone is not None:
            try:
                logger.info("Disconnecting from drone...")
                drone.disconnect()
                logger.info("✓ Disconnected successfully")
            except:
                pass
    
    logger.info("=" * 60)
    logger.info("Video streaming completed")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())

