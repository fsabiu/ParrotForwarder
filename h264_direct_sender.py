#!/usr/bin/env python3
"""
Direct H.264 video stream sender for Parrot Anafi via USB.
Uses Olympe's raw H.264 callback to capture and forward encoded data.
"""

import olympe
import logging
import time
import socket
import threading
import argparse
import struct
import os

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

# Drone IP address (USB connection)
DRONE_IP = "192.168.53.1"

# UDP packet size
MAX_PACKET_SIZE = 60000


class H264DirectSender:
    """Handles direct H.264 frame capture and UDP transmission"""
    
    def __init__(self, remote_host, remote_port):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.running = False
        self.bytes_sent = 0
        self.packets_sent = 0
        self.last_stats_time = time.time()
        self.lock = threading.Lock()
        
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info(f"H.264 UDP sender configured for {remote_host}:{remote_port}")
    
    def h264_frame_cb(self, h264_frame):
        """
        Callback for H.264 frames from Olympe
        This is the raw H.264 callback that should work better
        """
        if not self.running:
            return
        
        try:
            # Get frame info
            frame_info = h264_frame.info()
            
            # Try to get the H.264 data using different methods
            frame_data = None
            
            # Method 1: Try to get as bytes directly
            try:
                frame_data = bytes(h264_frame)
            except:
                pass
            
            # Method 2: Try to get as ctypes pointer and convert
            if frame_data is None:
                try:
                    import ctypes
                    ptr = h264_frame.as_ctypes_pointer()
                    if hasattr(h264_frame, 'vmeta_size'):
                        size = h264_frame.vmeta_size
                        frame_data = ctypes.string_at(ptr, size)
                except:
                    pass
            
            # Method 3: Try to get as ndarray and convert
            if frame_data is None:
                try:
                    import numpy as np
                    arr = h264_frame.as_ndarray()
                    if arr is not None:
                        frame_data = arr.tobytes()
                except:
                    pass
            
            if frame_data and len(frame_data) > 0:
                with self.lock:
                    self.packets_sent += 1
                    
                    # Log first packet
                    if self.packets_sent == 1:
                        logger.info(f"✓ First H.264 frame received ({len(frame_data)} bytes)")
                        logger.info(f"  Frame info: {frame_info}")
                    
                    # Send the H.264 frame
                    self._send_frame(frame_data)
                    self.bytes_sent += len(frame_data)
                    
                    # Periodic stats
                    current_time = time.time()
                    if current_time - self.last_stats_time >= 5.0:
                        elapsed = current_time - self.last_stats_time
                        mbps = (self.bytes_sent * 8) / (elapsed * 1000000)
                        logger.info(f"  Sent {self.packets_sent} packets | Bitrate: {mbps:.2f} Mbps")
                        self.bytes_sent = 0
                        self.last_stats_time = current_time
            else:
                logger.warning("Could not extract H.264 data from frame")
            
        except Exception as e:
            logger.warning(f"  Could not process H.264 frame: {e}")
            import traceback
            logger.warning(f"  Traceback: {traceback.format_exc()}")
    
    def _send_frame(self, frame_data):
        """
        Send H.264 frame over UDP with fragmentation support
        Protocol: [packet_id:4][timestamp:8][data:N]
        """
        frame_size = len(frame_data)
        
        # Calculate number of chunks needed
        chunk_size = MAX_PACKET_SIZE - 12  # Header size
        total_chunks = (frame_size + chunk_size - 1) // chunk_size
        
        packet_id = self.packets_sent
        timestamp = int(time.time() * 1000000)  # microseconds
        
        # Send each chunk
        for chunk_id in range(total_chunks):
            start = chunk_id * chunk_size
            end = min(start + chunk_size, frame_size)
            chunk_data = frame_data[start:end]
            
            # Build packet: packet_id (4) + timestamp (8) + chunk_id (2) + total_chunks (2) + data
            packet = struct.pack('!IQHH', packet_id, timestamp, chunk_id, total_chunks) + chunk_data
            
            try:
                self.sock.sendto(packet, (self.remote_host, self.remote_port))
            except Exception as e:
                logger.error(f"Failed to send packet: {e}")
                break
    
    def start(self):
        """Start sending"""
        self.running = True
        logger.info("H.264 sender started")
    
    def stop(self):
        """Stop sending"""
        self.running = False
        logger.info(f"H.264 sender stopped - {self.packets_sent} packets sent")
    
    def flush(self, *args, **kwargs):
        """Flush callback"""
        pass
    
    def close(self):
        """Close the UDP socket"""
        self.sock.close()


def main():
    parser = argparse.ArgumentParser(
        description='Stream H.264 video from Parrot Anafi drone over UDP',
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
        default=5002,
        help='Remote UDP port to send video to'
    )
    parser.add_argument(
        '--drone-ip',
        type=str,
        default=DRONE_IP,
        help='Drone IP address (USB connection)'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Streaming duration in seconds (0 for infinite)'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting H.264 Video Stream UDP Sender (Direct)")
    logger.info("=" * 60)
    logger.info(f"Connecting to drone at {args.drone_ip}")
    logger.info(f"Sending H.264 stream to {args.host}:{args.port}")
    
    drone = None
    h264_sender = H264DirectSender(args.host, args.port)
    
    try:
        # Create drone connection object
        drone = olympe.Drone(args.drone_ip)
        
        logger.info("Connecting to drone...")
        if not drone.connect():
            logger.error("✗ Failed to connect to the drone")
            return 1
        
        logger.info("✓ Connected to drone")
        logger.info("-" * 60)
        
        # Set up video streaming with H.264 callback
        logger.info("Setting up H.264 video stream...")
        
        # Register the H.264 frame callback
        drone.streaming.set_callbacks(
            h264_cb=h264_sender.h264_frame_cb,
            start_cb=h264_sender.start,
            end_cb=h264_sender.stop,
            flush_raw_cb=h264_sender.flush
        )
        
        # Start streaming
        logger.info("Starting video stream...")
        drone.streaming.start()
        
        logger.info("✓ H.264 streaming started")
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
        
        with h264_sender.lock:
            packets_sent = h264_sender.packets_sent
        
        if packets_sent > 0:
            logger.info(f"✓ H.264 streaming completed!")
            logger.info(f"  Total packets sent: {packets_sent}")
            logger.info(f"  Duration: {elapsed:.2f} seconds")
        else:
            logger.warning("⚠ No packets sent")
        
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
        h264_sender.close()
        if drone is not None:
            try:
                logger.info("Disconnecting from drone...")
                drone.disconnect()
                logger.info("✓ Disconnected successfully")
            except:
                pass
    
    logger.info("=" * 60)
    logger.info("H.264 streaming completed")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())
