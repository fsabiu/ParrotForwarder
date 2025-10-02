#!/usr/bin/env python3
"""
H.264 video stream sender for Parrot Anafi via USB.
Captures H.264 encoded video from the drone and streams it over UDP.
"""

import olympe
from olympe.video.renderer import PdrawRenderer
import logging
import time
import socket
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


class H264Sender:
    """Handles H.264 stream capture and UDP transmission"""
    
    def __init__(self, remote_host, remote_port):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.frame_count = 0
        self.bytes_sent = 0
        self.lock = threading.Lock()
        self.running = False
        self.last_stats_time = time.time()
        
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info(f"H.264 UDP sender configured for {remote_host}:{remote_port}")
    
    def h264_frame_cb(self, h264_frame):
        """
        Callback for H.264 frames from Olympe
        Sends encoded H.264 data directly over UDP
        """
        if not self.running:
            return
        
        try:
            # Reference the frame
            h264_frame.ref()
            
            # Get H.264 frame data
            frame_data = h264_frame.as_ctypes_pointer()
            frame_size = h264_frame.vmeta_size if hasattr(h264_frame, 'vmeta_size') else 0
            
            # Get the actual H.264 data as bytes
            frame_bytes = bytes(h264_frame)
            frame_size = len(frame_bytes)
            
            if frame_size > 0:
                with self.lock:
                    self.frame_count += 1
                    
                    # Log first frame
                    if self.frame_count == 1:
                        logger.info(f"✓ First H.264 frame received ({frame_size} bytes)")
                    
                    # Send the H.264 frame
                    self._send_frame(frame_bytes)
                    self.bytes_sent += frame_size
                    
                    # Periodic stats
                    current_time = time.time()
                    if current_time - self.last_stats_time >= 5.0:
                        elapsed = current_time - self.last_stats_time
                        mbps = (self.bytes_sent * 8) / (elapsed * 1000000)
                        logger.info(f"  Sent {self.frame_count} frames | Bitrate: {mbps:.2f} Mbps")
                        self.bytes_sent = 0
                        self.last_stats_time = current_time
            
            # Unreference the frame
            h264_frame.unref()
            
        except Exception as e:
            logger.warning(f"  Could not process/send H.264 frame: {e}")
            try:
                h264_frame.unref()
            except:
                pass
    
    def _send_frame(self, frame_data):
        """
        Send H.264 frame over UDP with fragmentation support
        Protocol: [frame_id:4][total_chunks:2][chunk_id:2][frame_type:1][reserved:1][data:N]
        """
        frame_size = len(frame_data)
        
        # Calculate number of chunks needed
        chunk_size = MAX_PACKET_SIZE - 10  # Header size
        total_chunks = (frame_size + chunk_size - 1) // chunk_size
        
        frame_id = self.frame_count
        
        # Detect frame type (I-frame, P-frame, etc.) from NAL unit type
        frame_type = 0
        if len(frame_data) > 4:
            # Find NAL unit type in first few bytes
            nal_type = frame_data[4] & 0x1F if frame_data[3] == 1 else frame_data[3] & 0x1F
            frame_type = nal_type
        
        # Send each chunk
        for chunk_id in range(total_chunks):
            start = chunk_id * chunk_size
            end = min(start + chunk_size, frame_size)
            chunk_data = frame_data[start:end]
            
            # Build packet: frame_id (4) + total_chunks (2) + chunk_id (2) + frame_type (1) + reserved (1) + data
            packet = struct.pack('!IHHBB', frame_id, total_chunks, chunk_id, frame_type, 0) + chunk_data
            
            try:
                self.sock.sendto(packet, (self.remote_host, self.remote_port))
            except Exception as e:
                logger.error(f"Failed to send packet: {e}")
                break
    
    def start(self):
        """Called when streaming starts"""
        logger.info("H.264 sender started")
        self.running = True
        self.frame_count = 0
        self.bytes_sent = 0
        self.last_stats_time = time.time()
        
    def stop(self):
        """Called when streaming stops"""
        logger.info(f"H.264 sender stopped - {self.frame_count} frames sent")
        self.running = False
        
    def flush(self, *args, **kwargs):
        """Called to flush pending frames"""
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
    logger.info("Starting H.264 Video Stream UDP Sender")
    logger.info("=" * 60)
    logger.info(f"Connecting to drone at {args.drone_ip}")
    logger.info(f"Sending H.264 stream to {args.host}:{args.port}")
    
    drone = None
    h264_sender = H264Sender(args.host, args.port)
    
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
            frame_count = h264_sender.frame_count
        
        if frame_count > 0:
            fps = frame_count / elapsed
            logger.info(f"✓ H.264 streaming completed!")
            logger.info(f"  Total frames sent: {frame_count}")
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

