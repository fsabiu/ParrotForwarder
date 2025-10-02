#!/usr/bin/env python3
"""
UDP H.264 video receiver for ParrotForwarder.
Receives H.264 stream over UDP, decodes frames, displays statistics, and saves every 10th frame.
"""

import socket
import logging
import argparse
import os
import time
import struct
import cv2
import numpy as np
from collections import defaultdict
import subprocess
import threading
from queue import Queue

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class H264Decoder:
    """Decodes H.264 frames using ffmpeg subprocess"""
    
    def __init__(self):
        self.process = None
        self.frame_queue = Queue(maxsize=60)
        self.running = False
        self.decode_thread = None
        
    def start(self):
        """Start the ffmpeg decoder process"""
        try:
            # Start ffmpeg process to decode H.264 to raw BGR frames
            self.process = subprocess.Popen([
                'ffmpeg',
                '-f', 'h264',           # Input format
                '-i', 'pipe:0',          # Read from stdin
                '-f', 'rawvideo',        # Output raw video
                '-pix_fmt', 'bgr24',     # BGR format for OpenCV
                '-an',                    # No audio
                '-sn',                    # No subtitles
                'pipe:1'                  # Write to stdout
            ], 
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
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
        # Assume 1920x1080 initially, will adjust if needed
        width, height = 1920, 1080
        frame_size = width * height * 3
        
        while self.running:
            try:
                # Try to read a frame
                frame_data = self.process.stdout.read(frame_size)
                
                if len(frame_data) == 0:
                    # End of stream
                    break
                
                if len(frame_data) == frame_size:
                    # Convert to numpy array
                    frame = np.frombuffer(frame_data, dtype=np.uint8).reshape((height, width, 3))
                    
                    # Put in queue (non-blocking, drop if full)
                    if not self.frame_queue.full():
                        self.frame_queue.put(frame)
                else:
                    # Partial frame, might need to adjust size
                    pass
                    
            except Exception as e:
                if self.running:
                    logger.error(f"Error reading frame: {e}")
                break
    
    def decode_frame(self, h264_data):
        """Send H.264 data to decoder"""
        if self.process and self.process.stdin:
            try:
                self.process.stdin.write(h264_data)
                self.process.stdin.flush()
            except Exception as e:
                logger.error(f"Error writing to decoder: {e}")
    
    def get_frame(self, timeout=0.1):
        """Get next decoded frame"""
        try:
            return self.frame_queue.get(timeout=timeout)
        except:
            return None
    
    def stop(self):
        """Stop the decoder"""
        self.running = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                except:
                    pass


class H264Receiver:
    """Handles UDP H.264 frame reception and reassembly"""
    
    def __init__(self, output_dir, save_interval=10):
        self.output_dir = output_dir
        self.save_interval = save_interval
        self.frame_chunks = defaultdict(dict)
        self.frame_total_chunks = {}
        self.frame_types = {}
        self.received_frames = 0
        self.decoded_frames = 0
        self.saved_frames = 0
        self.frame_times = []
        self.last_stats_time = time.time()
        self.decoder = H264Decoder()
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        logger.info(f"Saving frames to: {output_dir}")
    
    def start(self):
        """Start the receiver"""
        return self.decoder.start()
    
    def process_packet(self, data):
        """
        Process incoming UDP packet and reassemble H.264 frames
        Packet format: [frame_id:4][total_chunks:2][chunk_id:2][frame_type:1][reserved:1][data:N]
        """
        try:
            if len(data) < 10:
                return
            
            # Parse packet header
            frame_id, total_chunks, chunk_id, frame_type, _ = struct.unpack('!IHHBB', data[:10])
            chunk_data = data[10:]
            
            # Store chunk and metadata
            self.frame_chunks[frame_id][chunk_id] = chunk_data
            self.frame_total_chunks[frame_id] = total_chunks
            self.frame_types[frame_id] = frame_type
            
            # Check if frame is complete
            if len(self.frame_chunks[frame_id]) == total_chunks:
                self._assemble_frame(frame_id)
                
                # Clean up old incomplete frames
                if len(self.frame_chunks) > 100:
                    old_frame_ids = sorted(self.frame_chunks.keys())[:-100]
                    for old_id in old_frame_ids:
                        del self.frame_chunks[old_id]
                        if old_id in self.frame_total_chunks:
                            del self.frame_total_chunks[old_id]
                        if old_id in self.frame_types:
                            del self.frame_types[old_id]
        
        except Exception as e:
            logger.error(f"Error processing packet: {e}")
    
    def _assemble_frame(self, frame_id):
        """Assemble complete H.264 frame from chunks"""
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
            frame_type = self.frame_types.pop(frame_id, 0)
            
            self.received_frames += 1
            
            # Log first frame
            if self.received_frames == 1:
                logger.info(f"✓ First H.264 frame assembled ({len(frame_data)} bytes)")
            
            # Send to decoder
            self.decoder.decode_frame(frame_data)
            
        except Exception as e:
            logger.error(f"Error assembling frame {frame_id}: {e}")
    
    def process_decoded_frames(self):
        """Process decoded frames from the decoder"""
        frame = self.decoder.get_frame(timeout=0.01)
        
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
                    f"📊 Received: {self.received_frames} | "
                    f"Decoded: {self.decoded_frames} | "
                    f"FPS: {fps:.2f} | "
                    f"Saved: {self.saved_frames}"
                )
    
    def get_final_stats(self):
        """Return final statistics"""
        return {
            'received_frames': self.received_frames,
            'decoded_frames': self.decoded_frames,
            'saved_frames': self.saved_frames
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
    
    args = parser.parse_args()
    
    logger.info("=" * 60)
    logger.info("Starting H.264 Video Stream UDP Receiver")
    logger.info("=" * 60)
    logger.info(f"Listening on UDP port {args.port}")
    logger.info(f"Saving every {args.save_interval}th frame to: {args.output_dir}")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', args.port))
    sock.settimeout(0.01)  # Non-blocking with short timeout
    
    # Create H.264 receiver
    receiver = H264Receiver(args.output_dir, args.save_interval)
    
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
        logger.info(f"  H.264 frames received: {stats['received_frames']}")
        logger.info(f"  Frames decoded: {stats['decoded_frames']}")
        logger.info(f"  Frames saved: {stats['saved_frames']}")
        
        if stats['decoded_frames'] > 0 and elapsed > 0:
            avg_fps = stats['decoded_frames'] / elapsed
            logger.info(f"  Average FPS: {avg_fps:.2f}")
        
        logger.info(f"  Output directory: {args.output_dir}")
        logger.info("=" * 60)
        
    finally:
        sock.close()


if __name__ == "__main__":
    main()

