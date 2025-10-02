#!/usr/bin/env python3
"""
UDP H.264 video stream receiver for ParrotForwarder.
Receives continuous H.264 stream over UDP, decodes frames, and saves periodically.
"""

import socket
import logging
import argparse
import os
import time
import struct
import cv2
import numpy as np
import subprocess
import threading
from queue import Queue, Empty

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class H264StreamDecoder:
    """Decodes continuous H.264 stream using ffmpeg subprocess"""
    
    def __init__(self, width=1920, height=1080):
        self.width = width
        self.height = height
        self.process = None
        self.frame_queue = Queue(maxsize=30)
        self.running = False
        self.decode_thread = None
        self.h264_pipe = None
        
    def start(self):
        """Start the ffmpeg decoder process"""
        try:
            # Start ffmpeg process to decode H.264 to raw BGR frames
            self.process = subprocess.Popen([
                'ffmpeg',
                '-hide_banner',
                '-loglevel', 'error',
                '-f', 'h264',           # Input format
                '-i', 'pipe:0',          # Read from stdin
                '-f', 'rawvideo',        # Output raw video
                '-pix_fmt', 'bgr24',     # BGR format for OpenCV
                '-s', f'{self.width}x{self.height}',  # Size hint
                'pipe:1'                  # Write to stdout
            ], 
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=10**8
            )
            
            self.running = True
            self.decode_thread = threading.Thread(target=self._read_frames, daemon=True)
            self.decode_thread.start()
            
            logger.info("✓ H.264 decoder started")
            return True
            
        except FileNotFoundError:
            logger.error("✗ ffmpeg not found. Please install ffmpeg.")
            return False
        except Exception as e:
            logger.error(f"✗ Failed to start decoder: {e}")
            return False
    
    def _read_frames(self):
        """Read decoded frames from ffmpeg stdout"""
        frame_size = self.width * self.height * 3
        
        while self.running:
            try:
                # Read a frame
                frame_data = self.process.stdout.read(frame_size)
                
                if len(frame_data) == 0:
                    # End of stream
                    break
                
                if len(frame_data) == frame_size:
                    # Convert to numpy array
                    frame = np.frombuffer(frame_data, dtype=np.uint8).reshape((self.height, self.width, 3))
                    
                    # Put in queue (non-blocking, drop if full)
                    try:
                        self.frame_queue.put(frame, block=False)
                    except:
                        # Queue full, drop frame
                        pass
                        
            except Exception as e:
                if self.running:
                    logger.error(f"Error reading frame: {e}")
                break
    
    def write_h264_data(self, data):
        """Send H.264 data to decoder"""
        if self.process and self.process.stdin and self.running:
            try:
                self.process.stdin.write(data)
                self.process.stdin.flush()
            except Exception as e:
                if self.running:
                    logger.error(f"Error writing to decoder: {e}")
    
    def get_frame(self, timeout=0.01):
        """Get next decoded frame"""
        try:
            return self.frame_queue.get(timeout=timeout)
        except Empty:
            return None
    
    def stop(self):
        """Stop the decoder"""
        self.running = False
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass


class H264StreamReceiver:
    """Handles UDP H.264 stream reception"""
    
    def __init__(self, output_dir, save_interval=10, width=1920, height=1080):
        self.output_dir = output_dir
        self.save_interval = save_interval
        self.packets_received = 0
        self.bytes_received = 0
        self.decoded_frames = 0
        self.saved_frames = 0
        self.frame_times = []
        self.last_stats_time = time.time()
        self.decoder = H264StreamDecoder(width, height)
        self.last_chunk_id = -1
        self.missing_chunks = 0
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Saving frames to: {output_dir}")
    
    def start(self):
        """Start the receiver"""
        return self.decoder.start()
    
    def process_packet(self, data):
        """
        Process incoming UDP packet
        Packet format: [chunk_id:4][timestamp:8][data:N]
        """
        try:
            if len(data) < 12:
                return
            
            # Parse packet header
            chunk_id, timestamp = struct.unpack('!IQ', data[:12])
            h264_data = data[12:]
            
            self.packets_received += 1
            self.bytes_received += len(h264_data)
            
            # Check for missing chunks
            if self.last_chunk_id >= 0:
                expected = self.last_chunk_id + 1
                if chunk_id != expected:
                    missing = chunk_id - expected
                    self.missing_chunks += missing
                    if missing > 0 and missing < 100:  # Only log reasonable gaps
                        logger.warning(f"⚠ Missing {missing} chunks (got {chunk_id}, expected {expected})")
            
            self.last_chunk_id = chunk_id
            
            # Log first packet
            if self.packets_received == 1:
                logger.info(f"✓ First packet received ({len(h264_data)} bytes)")
            
            # Send to decoder
            self.decoder.write_h264_data(h264_data)
            
        except Exception as e:
            logger.error(f"Error processing packet: {e}")
    
    def process_decoded_frames(self):
        """Process decoded frames from the decoder"""
        frame = self.decoder.get_frame(timeout=0.001)
        
        if frame is not None:
            self.decoded_frames += 1
            current_time = time.time()
            
            # Track frame timing for FPS calculation
            self.frame_times.append(current_time)
            if len(self.frame_times) > 60:
                self.frame_times.pop(0)
            
            # Log first decoded frame
            if self.decoded_frames == 1:
                height, width = frame.shape[:2]
                logger.info(f"✓ First frame decoded! Resolution: {width}x{height}")
            
            # Save every Nth frame
            if self.decoded_frames % self.save_interval == 0:
                self._save_frame(frame)
            
            # Display stats periodically
            if current_time - self.last_stats_time >= 1.0:
                self._display_stats()
                self.last_stats_time = current_time
    
    def _save_frame(self, img):
        """Save frame to disk"""
        try:
            filename = f"frame_{self.saved_frames + 1:05d}.jpg"
            filepath = os.path.join(self.output_dir, filename)
            cv2.imwrite(filepath, img)
            self.saved_frames += 1
            logger.info(f"  💾 Saved frame #{self.decoded_frames} as {filename}")
        except Exception as e:
            logger.error(f"Error saving frame: {e}")
    
    def _display_stats(self):
        """Display reception statistics"""
        if len(self.frame_times) >= 2:
            time_diff = self.frame_times[-1] - self.frame_times[0]
            if time_diff > 0:
                fps = (len(self.frame_times) - 1) / time_diff
                logger.info(
                    f"📊 Packets: {self.packets_received} | "
                    f"Decoded: {self.decoded_frames} | "
                    f"FPS: {fps:.2f} | "
                    f"Saved: {self.saved_frames}"
                )
    
    def get_final_stats(self):
        """Return final statistics"""
        return {
            'packets_received': self.packets_received,
            'bytes_received': self.bytes_received,
            'decoded_frames': self.decoded_frames,
            'saved_frames': self.saved_frames,
            'missing_chunks': self.missing_chunks
        }
    
    def stop(self):
        """Stop the receiver"""
        self.decoder.stop()


def main():
    parser = argparse.ArgumentParser(
        description='Receive H.264 video stream from ParrotForwarder over UDP',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5002,
        help='UDP port to listen on'
    )
    parser.add_argument(
        '--output-dir',
        type=str,
        default='./h264_frames',
        help='Directory to save frames'
    )
    parser.add_argument(
        '--save-interval',
        type=int,
        default=10,
        help='Save every Nth frame (e.g., 10 = save 1 out of every 10 frames)'
    )
    parser.add_argument(
        '--width',
        type=int,
        default=1920,
        help='Expected video width'
    )
    parser.add_argument(
        '--height',
        type=int,
        default=1080,
        help='Expected video height'
    )
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting H.264 Video Stream UDP Receiver")
    logger.info("=" * 60)
    logger.info(f"Listening on UDP port {args.port}")
    logger.info(f"Expected resolution: {args.width}x{args.height}")
    logger.info(f"Saving every {args.save_interval}th frame to: {args.output_dir}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', args.port))
    sock.settimeout(0.001)  # 1ms timeout for non-blocking
    
    # Create H.264 receiver
    receiver = H264StreamReceiver(args.output_dir, args.save_interval, args.width, args.height)
    
    if not receiver.start():
        logger.error("Failed to start receiver")
        return 1
    
    start_time = time.time()
    
    try:
        while True:
            try:
                # Receive UDP packet (non-blocking)
                data, addr = sock.recvfrom(65535)
                receiver.process_packet(data)
            except socket.timeout:
                pass
            
            # Process any decoded frames
            receiver.process_decoded_frames()
            
    except KeyboardInterrupt:
        logger.info("\n" + "=" * 60)
        logger.info("Stopping receiver...")
        
        # Stop decoder
        receiver.stop()
        
        # Display final statistics
        elapsed = time.time() - start_time
        stats = receiver.get_final_stats()
        
        logger.info("=" * 60)
        logger.info("Final Statistics:")
        logger.info(f"  Total runtime: {elapsed:.2f} seconds")
        logger.info(f"  Packets received: {stats['packets_received']}")
        logger.info(f"  Bytes received: {stats['bytes_received'] / (1024*1024):.2f} MB")
        logger.info(f"  Missing chunks: {stats['missing_chunks']}")
        logger.info(f"  Frames decoded: {stats['decoded_frames']}")
        logger.info(f"  Frames saved: {stats['saved_frames']}")
        
        if stats['decoded_frames'] > 0 and elapsed > 0:
            avg_fps = stats['decoded_frames'] / elapsed
            logger.info(f"  Average FPS: {avg_fps:.2f}")
        
        if stats['bytes_received'] > 0 and elapsed > 0:
            mbps = (stats['bytes_received'] * 8) / (elapsed * 1000000)
            logger.info(f"  Average bitrate: {mbps:.2f} Mbps")
        
        logger.info(f"  Output directory: {args.output_dir}")
        logger.info("=" * 60)
        
    finally:
        sock.close()


if __name__ == "__main__":
    main()

