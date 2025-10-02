#!/usr/bin/env python3
"""
H.264 video stream sender for Parrot Anafi via USB.
Records H.264 stream to a pipe and forwards it over UDP.
This approach is more efficient and avoids frame-by-frame processing issues.
"""

import olympe
import logging
import time
import socket
import threading
import argparse
import struct
import os
import subprocess

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


class H264StreamSender:
    """Handles H.264 stream forwarding over UDP"""
    
    def __init__(self, remote_host, remote_port, pipe_path="/tmp/drone_h264.pipe"):
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.pipe_path = pipe_path
        self.running = False
        self.bytes_sent = 0
        self.packets_sent = 0
        self.last_stats_time = time.time()
        self.sender_thread = None
        
        # Create UDP socket
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        logger.info(f"H.264 UDP sender configured for {remote_host}:{remote_port}")
        
    def start_forwarding(self):
        """Start the UDP forwarding thread"""
        self.running = True
        self.sender_thread = threading.Thread(target=self._forward_stream, daemon=True)
        self.sender_thread.start()
        logger.info("Stream forwarding started")
    
    def _forward_stream(self):
        """Read from pipe and forward over UDP"""
        try:
            # Open the named pipe for reading
            logger.info(f"Opening pipe: {self.pipe_path}")
            with open(self.pipe_path, 'rb') as pipe:
                logger.info("✓ Pipe opened, starting to forward stream...")
                
                chunk_id = 0
                
                while self.running:
                    # Read chunk from pipe
                    data = pipe.read(MAX_PACKET_SIZE)
                    
                    if not data:
                        # End of stream
                        logger.info("End of stream reached")
                        break
                    
                    # Send chunk over UDP with sequence number
                    # Protocol: [chunk_id:4][timestamp:8][data:N]
                    timestamp = int(time.time() * 1000000)  # microseconds
                    packet = struct.pack('!IQ', chunk_id, timestamp) + data
                    
                    try:
                        self.sock.sendto(packet, (self.remote_host, self.remote_port))
                        self.packets_sent += 1
                        self.bytes_sent += len(data)
                        chunk_id += 1
                        
                        # Log first packet
                        if self.packets_sent == 1:
                            logger.info(f"✓ First packet sent ({len(data)} bytes)")
                        
                        # Periodic stats
                        current_time = time.time()
                        if current_time - self.last_stats_time >= 5.0:
                            elapsed = current_time - self.last_stats_time
                            mbps = (self.bytes_sent * 8) / (elapsed * 1000000)
                            logger.info(f"  Sent {self.packets_sent} packets | Bitrate: {mbps:.2f} Mbps")
                            self.bytes_sent = 0
                            self.last_stats_time = current_time
                            
                    except Exception as e:
                        logger.error(f"Failed to send packet: {e}")
                        
        except Exception as e:
            logger.error(f"Error in forwarding thread: {e}")
            import traceback
            logger.error(traceback.format_exc())
    
    def stop(self):
        """Stop forwarding"""
        logger.info("Stopping stream forwarding...")
        self.running = False
        if self.sender_thread:
            self.sender_thread.join(timeout=2)
    
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
    
    # Create named pipe
    pipe_path = "/tmp/drone_h264.pipe"
    if os.path.exists(pipe_path):
        os.remove(pipe_path)
    os.mkfifo(pipe_path)
    logger.info(f"Created named pipe: {pipe_path}")
    
    drone = None
    stream_sender = H264StreamSender(args.host, args.port, pipe_path)
    
    try:
        # Create drone connection object
        drone = olympe.Drone(args.drone_ip)
        
        logger.info("Connecting to drone...")
        if not drone.connect():
            logger.error("✗ Failed to connect to the drone")
            return 1
        
        logger.info("✓ Connected to drone")
        logger.info("-" * 60)
        
        # Start the UDP forwarding thread
        stream_sender.start_forwarding()
        
        # Start recording to the named pipe
        logger.info("Starting video recording to pipe...")
        drone.streaming.start()
        
        # Set up recording to pipe in H.264 format
        recording = drone.streaming.set_output_files(
            video=pipe_path,
            metadata=None
        )
        
        drone.streaming.play()
        
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
        packets_sent = stream_sender.packets_sent
        
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
        stream_sender.stop()
        
    except Exception as e:
        logger.error(f"✗ Error occurred: {str(e)}")
        logger.exception("Full exception details:")
        return 1
        
    finally:
        # Ensure cleanup
        stream_sender.stop()
        stream_sender.close()
        
        if drone is not None:
            try:
                logger.info("Disconnecting from drone...")
                drone.disconnect()
                logger.info("✓ Disconnected successfully")
            except:
                pass
        
        # Clean up pipe
        try:
            if os.path.exists(pipe_path):
                os.remove(pipe_path)
        except:
            pass
    
    logger.info("=" * 60)
    logger.info("H.264 streaming completed")
    logger.info("=" * 60)
    return 0


if __name__ == "__main__":
    exit(main())

