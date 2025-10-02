#!/usr/bin/env python3
"""
UDP video receiver for ParrotForwarder.
Receives video frames over UDP, displays statistics, and saves every 10th frame.
"""

import socket
import logging
import argparse
import os
import time
import struct
import cv2
import numpy as np
from datetime import datetime
from collections import defaultdict

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class VideoReceiver:
    """Handles UDP video frame reception and reassembly"""
    
    def __init__(self, output_dir, save_interval=10):
        self.output_dir = output_dir
        self.save_interval = save_interval
        self.frame_chunks = defaultdict(dict)  # {frame_id: {chunk_id: data}}
        self.frame_total_chunks = {}  # {frame_id: total_chunks}
        self.completed_frames = 0
        self.saved_frames = 0
        self.last_frame_time = None
        self.frame_times = []
        self.last_stats_time = time.time()
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Saving frames to: {output_dir}")
    
    def process_packet(self, data):
        """
        Process incoming UDP packet and reassemble frames
        Packet format: [frame_id:4][total_chunks:2][chunk_id:2][data:N]
        """
        try:
            # Parse packet header
            if len(data) < 8:
                logger.warning("Packet too small, ignoring")
                return
            
            frame_id, total_chunks, chunk_id = struct.unpack('!IHH', data[:8])
            chunk_data = data[8:]
            
            # Store chunk
            self.frame_chunks[frame_id][chunk_id] = chunk_data
            self.frame_total_chunks[frame_id] = total_chunks
            
            # Check if frame is complete
            if len(self.frame_chunks[frame_id]) == total_chunks:
                self._assemble_frame(frame_id)
                
                # Clean up old incomplete frames (keep only last 100)
                if len(self.frame_chunks) > 100:
                    old_frame_ids = sorted(self.frame_chunks.keys())[:-100]
                    for old_id in old_frame_ids:
                        del self.frame_chunks[old_id]
                        if old_id in self.frame_total_chunks:
                            del self.frame_total_chunks[old_id]
        
        except Exception as e:
            logger.error(f"Error processing packet: {e}")
    
    def _assemble_frame(self, frame_id):
        """Assemble complete frame from chunks and process it"""
        try:
            # Get all chunks in order
            total_chunks = self.frame_total_chunks[frame_id]
            frame_data = b''.join(
                self.frame_chunks[frame_id][i] 
                for i in range(total_chunks)
            )
            
            # Clean up
            del self.frame_chunks[frame_id]
            del self.frame_total_chunks[frame_id]
            
            # Decode JPEG
            nparr = np.frombuffer(frame_data, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if img is not None:
                self.completed_frames += 1
                current_time = time.time()
                
                # Track frame timing for FPS calculation
                self.frame_times.append(current_time)
                # Keep only last 60 frames for FPS calculation
                if len(self.frame_times) > 60:
                    self.frame_times.pop(0)
                
                # Log first frame
                if self.completed_frames == 1:
                    height, width = img.shape[:2]
                    logger.info(f"✓ First frame received! Resolution: {width}x{height}")
                
                # Save every Nth frame
                if self.completed_frames % self.save_interval == 0:
                    self._save_frame(img)
                
                # Calculate and display FPS periodically
                if current_time - self.last_stats_time >= 1.0:
                    self._display_stats()
                    self.last_stats_time = current_time
            
        except Exception as e:
            logger.error(f"Error assembling frame {frame_id}: {e}")
    
    def _save_frame(self, img):
        """Save frame to disk"""
        try:
            filename = f"frame_{self.saved_frames + 1:05d}.jpg"
            filepath = os.path.join(self.output_dir, filename)
            cv2.imwrite(filepath, img)
            self.saved_frames += 1
            logger.info(f"  💾 Saved frame #{self.completed_frames} as {filename}")
        except Exception as e:
            logger.error(f"Error saving frame: {e}")
    
    def _display_stats(self):
        """Display reception statistics"""
        if len(self.frame_times) >= 2:
            time_diff = self.frame_times[-1] - self.frame_times[0]
            if time_diff > 0:
                fps = (len(self.frame_times) - 1) / time_diff
                logger.info(
                    f"📊 Frames: {self.completed_frames} | "
                    f"FPS: {fps:.2f} | "
                    f"Saved: {self.saved_frames}"
                )
    
    def get_final_stats(self):
        """Return final statistics"""
        return {
            'completed_frames': self.completed_frames,
            'saved_frames': self.saved_frames
        }


def main():
    parser = argparse.ArgumentParser(
        description='Receive video stream from ParrotForwarder over UDP',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5001,
        help='UDP port to listen on'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./video_frames',
        help='Directory to save frames'
    )
    parser.add_argument(
        '--save-interval',
        type=int,
        default=10,
        help='Save every Nth frame (e.g., 10 = save 1 out of every 10 frames)'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting Video Stream UDP Receiver")
    logger.info("=" * 60)
    logger.info(f"Listening on UDP port {args.port}")
    logger.info(f"Saving every {args.save_interval}th frame to: {args.output_dir}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', args.port))
    
    # Create video receiver
    receiver = VideoReceiver(args.output_dir, args.save_interval)
    
    start_time = time.time()
    
    try:
        while True:
            # Receive UDP packet
            data, addr = sock.recvfrom(65535)
            
            # Process the packet
            receiver.process_packet(data)
            
    except KeyboardInterrupt:
        logger.info("\n" + "=" * 60)
        logger.info("Stopping receiver...")
        
        # Display final statistics
        elapsed = time.time() - start_time
        stats = receiver.get_final_stats()
        
        logger.info("=" * 60)
        logger.info("Final Statistics:")
        logger.info(f"  Total runtime: {elapsed:.2f} seconds")
        logger.info(f"  Frames received: {stats['completed_frames']}")
        logger.info(f"  Frames saved: {stats['saved_frames']}")
        
        if stats['completed_frames'] > 0 and elapsed > 0:
            avg_fps = stats['completed_frames'] / elapsed
            logger.info(f"  Average FPS: {avg_fps:.2f}")
        
        logger.info(f"  Output directory: {args.output_dir}")
        logger.info("=" * 60)
        
    finally:
        sock.close()


if __name__ == "__main__":
    main()

