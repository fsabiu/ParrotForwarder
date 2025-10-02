"""
VideoForwarder - Handles H.264 video stream forwarding

Forwards H.264 encoded video frames directly from the drone over UDP.
Uses zero-copy forwarding with minimal CPU overhead.
"""

import logging
import time
import threading
import socket
import struct


class VideoForwarder(threading.Thread):
    """
    Handles H.264 video stream forwarding from the drone.
    
    Receives H.264 encoded frames directly from the drone (no re-encoding)
    and forwards them over UDP with simple framing protocol.
    
    Frame format: [4 bytes: frame_size (big-endian)][H.264 NAL units]
    """
    
    def __init__(self, drone, fps=30, remote_host=None, remote_port=5004, name="VideoForwarder"):
        """
        Initialize the video forwarder.
        
        Args:
            drone: Olympe Drone instance
            fps: Target frames per second for video forwarding
            remote_host: Remote host IP address to send video to
            remote_port: Remote port for video (default: 5004)
            name: Thread name
        """
        super().__init__(name=name, daemon=True)
        self.drone = drone
        self.fps = fps
        self.interval = 1.0 / fps
        self.running = False
        self.logger = logging.getLogger(f"{__name__}.{name}")
        
        # UDP forwarding configuration
        self.remote_host = remote_host
        self.remote_port = remote_port
        self.udp_socket = None
        self.forwarding_enabled = remote_host is not None
        
        # Debug logging
        self.logger.info(f"DEBUG: VideoForwarder.__init__ - remote_host={remote_host}, remote_port={remote_port}, forwarding_enabled={self.forwarding_enabled}")
        
        # Initialize UDP socket if forwarding is enabled
        if self.forwarding_enabled:
            try:
                self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                # Set socket to non-blocking to avoid delays
                self.udp_socket.setblocking(False)
                # Increase socket buffer for video (4MB)
                self.udp_socket.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4 * 1024 * 1024)
                self.logger.info(f"✓ UDP socket initialized - sending to {remote_host}:{remote_port}")
            except Exception as e:
                self.logger.error(f"✗ Failed to create UDP socket: {e}")
                self.forwarding_enabled = False
        else:
            self.logger.info("Video forwarding DISABLED (no remote_host specified)")
        
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
        
        # H.264 SPS/PPS caching for late joiners
        self.cached_sps_pps = []  # Cache SPS/PPS frames
        self.last_sps_pps_send = 0  # Last time we sent SPS/PPS
        self.sps_pps_interval = 5.0  # Resend SPS/PPS every 5 seconds
        self.has_sent_initial_sps_pps = False
        
    def h264_frame_callback(self, h264_frame):
        """
        Callback for receiving H.264 encoded frames from Olympe.
        This runs in Olympe's video thread - keep it fast!
        
        Args:
            h264_frame: H.264 VideoFrame from Olympe
        """
        self.frames_received += 1
        
        try:
            # Check frame info for SPS/PPS on first frame
            if self.frames_received == 1:
                try:
                    frame_info = h264_frame.info()
                    self.logger.info(f"DEBUG: First frame info keys: {list(frame_info.keys())}")
                    
                    # Check 'coded' key for codec-specific info
                    if 'coded' in frame_info:
                        coded_info = frame_info['coded']
                        self.logger.info(f"DEBUG: Coded info type: {type(coded_info)}")
                        if hasattr(coded_info, 'keys'):
                            self.logger.info(f"DEBUG: Coded info keys: {list(coded_info.keys())}")
                            
                            # Check the 'frame' sub-dict
                            if 'frame' in coded_info:
                                frame_dict = coded_info['frame']
                                self.logger.info(f"DEBUG: Frame dict type: {type(frame_dict)}")
                                if hasattr(frame_dict, 'keys'):
                                    self.logger.info(f"DEBUG: Frame dict keys: {list(frame_dict.keys())}")
                                    
                                    # Check the 'info' sub-dict
                                    if 'info' in frame_dict:
                                        info_dict = frame_dict['info']
                                        self.logger.info(f"DEBUG: Info dict type: {type(info_dict)}")
                                        if hasattr(info_dict, 'keys'):
                                            self.logger.info(f"DEBUG: Info dict keys: {list(info_dict.keys())}")
                                            # Check for sps/pps HERE
                                            if 'sps' in info_dict:
                                                sps = info_dict['sps']
                                                self.logger.info(f"DEBUG: ✓✓✓ FOUND SPS! Type: {type(sps)}, Len: {len(sps) if hasattr(sps, '__len__') else 'N/A'}")
                                            if 'pps' in info_dict:
                                                pps = info_dict['pps']  
                                                self.logger.info(f"DEBUG: ✓✓✓ FOUND PPS! Type: {type(pps)}, Len: {len(pps) if hasattr(pps, '__len__') else 'N/A'}")
                        else:
                            self.logger.info(f"DEBUG: Coded info value: {coded_info}")
                    
                    # Check 'format' key 
                    if 'format' in frame_info:
                        format_info = frame_info['format']
                        self.logger.info(f"DEBUG: Format info type: {type(format_info)}")
                        if hasattr(format_info, 'keys'):
                            self.logger.info(f"DEBUG: Format info keys: {list(format_info.keys())}")
                        else:
                            self.logger.info(f"DEBUG: Format info value: {format_info}")
                            
                except Exception as e:
                    self.logger.warning(f"Could not inspect frame info: {e}")
                    import traceback
                    self.logger.warning(f"Traceback: {traceback.format_exc()}")
            
            # Get H.264 data as 1D numpy array (bytes)
            # Note: Olympe manages the frame lifecycle automatically in callbacks
            # We should NOT manually ref/unref unless passing to another thread
            h264_data = h264_frame.as_ndarray()
            
            if h264_data is not None and len(h264_data) > 0:
                # CRITICAL: Make a complete copy IMMEDIATELY
                # The frame buffer is only valid during this callback
                h264_bytes = h264_data.tobytes()  # Creates a copy
                frame_size = len(h264_bytes)
                self.bytes_received += frame_size
                
                # Check NAL type BEFORE rate limiting
                # SPS/PPS must ALWAYS be sent immediately, regardless of FPS
                nal_type = self.get_nal_type(h264_bytes)
                
                # Debug: log first 20 frames' NAL types AND first bytes
                if self.frames_received <= 20:
                    nal_type_str = {
                        1: 'P-frame', 5: 'IDR-frame', 6: 'SEI', 
                        7: 'SPS', 8: 'PPS', 9: 'AUD'
                    }.get(nal_type, f'type-{nal_type}' if nal_type else 'unknown')
                    # Show first 8 bytes in hex
                    first_bytes = ' '.join(f'{b:02x}' for b in h264_bytes[:8])
                    self.logger.info(f"DEBUG: Frame #{self.frames_received} - NAL type: {nal_type_str} | Size: {frame_size}B | Start: {first_bytes}")
                
                # Forward immediately if it's SPS or PPS
                if self.forwarding_enabled:
                    if nal_type in (7, 8):  # SPS or PPS - ALWAYS forward immediately
                        self.forward_h264_frame(h264_bytes, frame_size)
                        return
                    
                    # For other frames, apply rate limiting
                    current_time = time.time()
                    time_since_last = current_time - self.last_forward_time
                    
                    if time_since_last < self.interval:
                        self.frames_dropped += 1
                        return
                    
                    self.last_forward_time = current_time
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
            # H.264 NAL units start with 0x00 0x00 0x00 0x01 (4-byte start code)
            # or 0x00 0x00 0x01 (3-byte start code)
            # The NAL type is in the first byte after the start code, in bits 0-4
            
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
    
    def is_sps_or_pps(self, h264_bytes):
        """
        Check if H.264 data contains SPS (7) or PPS (8) NAL units.
        
        Args:
            h264_bytes: bytes containing H.264 data
            
        Returns:
            bool: True if this is SPS or PPS
        """
        nal_type = self.get_nal_type(h264_bytes)
        return nal_type in (7, 8)  # 7=SPS, 8=PPS
    
    def cache_sps_pps(self, h264_bytes):
        """
        Cache SPS/PPS frames for resending to late joiners.
        
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
    
    def send_cached_sps_pps(self):
        """Send cached SPS/PPS frames to ensure decoder can initialize."""
        if not self.cached_sps_pps or not self.forwarding_enabled:
            return
        
        try:
            for sps_pps_data in self.cached_sps_pps:
                self.udp_socket.sendto(sps_pps_data, (self.remote_host, self.remote_port))
                self.bytes_sent += len(sps_pps_data)
            
            if not self.has_sent_initial_sps_pps:
                self.logger.info(f"✓ Sent initial SPS/PPS to {self.remote_host}:{self.remote_port}")
                self.has_sent_initial_sps_pps = True
            
            self.last_sps_pps_send = time.time()
            
        except Exception as e:
            self.logger.warning(f"Error sending SPS/PPS: {e}")
    
    def forward_h264_frame(self, h264_bytes, frame_size):
        """
        Forward an H.264 frame via UDP with SPS/PPS handling.
        
        Handles SPS/PPS caching and periodic resending for late joiners.
        
        Args:
            h264_bytes: bytes containing H.264 data
            frame_size: size of the frame in bytes
        """
        try:
            # Get NAL type for all frames (for debugging)
            nal_type = self.get_nal_type(h264_bytes)
            
            # Check if this is SPS or PPS
            if nal_type in (7, 8):  # SPS or PPS
                self.cache_sps_pps(h264_bytes)
                # Always send SPS/PPS immediately
                self.udp_socket.sendto(h264_bytes, (self.remote_host, self.remote_port))
                self.bytes_sent += len(h264_bytes)
                return
            
            # Periodically resend SPS/PPS for late joiners
            current_time = time.time()
            if (self.cached_sps_pps and 
                current_time - self.last_sps_pps_send >= self.sps_pps_interval):
                self.send_cached_sps_pps()
            
            # Send the frame (raw H.264 data) - check socket is still valid
            if self.udp_socket and self.forwarding_enabled:
                self.udp_socket.sendto(h264_bytes, (self.remote_host, self.remote_port))
            else:
                return  # Socket closed, stop forwarding
            
            # Track statistics
            self.frames_forwarded += 1
            self.bytes_sent += len(h264_bytes)
            self.frame_sizes.append(frame_size)
            if len(self.frame_sizes) > self.max_frame_sizes:
                self.frame_sizes.pop(0)
            
            # Log first few frames and every 100th frame for debugging
            if self.frames_forwarded <= 10 or self.frames_forwarded % 100 == 0:
                nal_type_str = {
                    1: 'P-frame', 
                    5: 'IDR-frame', 
                    6: 'SEI', 
                    7: 'SPS', 
                    8: 'PPS',
                    9: 'AUD'
                }.get(nal_type, f'type-{nal_type}' if nal_type else 'unknown')
                self.logger.info(
                    f"✓ Forwarded H.264 frame #{self.frames_forwarded} ({nal_type_str}) to {self.remote_host}:{self.remote_port} "
                    f"({frame_size} bytes)"
                )
            
        except BlockingIOError:
            # Socket buffer full - frame dropped
            self.send_errors += 1
            if self.send_errors <= 5 or self.send_errors % 100 == 0:
                self.logger.warning(f"⚠ BlockingIOError - socket buffer full, frame dropped (total: {self.send_errors})")
        except Exception as e:
            self.send_errors += 1
            if self.send_errors <= 5:
                import traceback
                self.logger.error(f"✗ Error forwarding frame: {e}")
                self.logger.error(f"Traceback: {traceback.format_exc()}")
    
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
            
            # Add bandwidth and frame size info if forwarding
            if self.forwarding_enabled:
                perf_msg += (
                    f" | Bandwidth: {bandwidth_mbps:.2f} Mbps | "
                    f"Frame: avg={avg_frame_size/1024:.1f}KB, min={min_frame_size/1024:.1f}KB, max={max_frame_size/1024:.1f}KB | "
                    f"UDP: sent={self.frames_forwarded}, errors={self.send_errors}"
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
                        f"High UDP send error rate: {error_rate:.1f}% ({self.send_errors}/{self.frames_forwarded})"
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
        """Set up H.264 video streaming callbacks."""
        try:
            self.logger.info("Setting up H.264 video stream callbacks...")
            # Use bytestream format (with start codes) for standard H.264
            self.drone.streaming.set_callbacks(
                h264_bytestream_cb=self.h264_frame_callback,
                start_cb=self.start_callback,
                end_cb=self.stop_callback,
                flush_h264_cb=self.flush_h264_callback
            )
            self.logger.info("Using H.264 bytestream format (receiver will add SPS/PPS)")
            self.logger.info("Starting H.264 video stream...")
            self.drone.streaming.start()
            self.logger.info("✓ H.264 video streaming started - forwarding raw encoded frames")
            
            # Try to get session metadata which might contain SPS/PPS
            try:
                import time
                time.sleep(0.5)  # Wait for stream to initialize
                session_metadata = self.drone.streaming.get_session_metadata()
                self.logger.info(f"DEBUG: Session metadata type: {type(session_metadata)}")
                if session_metadata:
                    self.logger.info(f"DEBUG: Session metadata keys: {list(session_metadata.keys()) if hasattr(session_metadata, 'keys') else 'N/A'}")
            except Exception as e:
                self.logger.info(f"DEBUG: Could not get session metadata: {e}")
                
        except Exception as e:
            import traceback
            self.logger.error(f"✗ Failed to setup video streaming: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            raise
    
    def run(self):
        """Main thread execution loop for statistics monitoring."""
        self.logger.info(f"Started - Target FPS: {self.fps} (H.264 bytestream forwarding)")
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
            
            if self.forwarding_enabled:
                self.logger.info(
                    f"Stopped - Received {self.frames_received} frames ({final_received_fps:.2f} fps) | "
                    f"Forwarded {self.frames_forwarded} frames ({final_forwarded_fps:.2f} fps, {fps_ratio:.1f}% of target) | "
                    f"Dropped {self.frames_dropped} frames | "
                    f"Average bandwidth: {total_bandwidth:.2f} Mbps | "
                    f"Total data sent: {self.bytes_sent / (1024*1024):.2f} MB"
                )
                
                if self.frames_forwarded > 0:
                    self.logger.info(f"Final performance: {fps_ratio:.1f}% of target ({self.fps} fps)")
            else:
                self.logger.info(f"Stopped - Received {self.frames_received} frames ({final_received_fps:.2f} fps)")
    
    def stop(self):
        """Stop the video forwarder and cleanup resources."""
        self.running = False
        if self.udp_socket:
            try:
                self.udp_socket.close()
                self.logger.info("UDP socket closed")
            except:
                pass
        self.logger.info("Stopped")
