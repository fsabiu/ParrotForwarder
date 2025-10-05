#!/usr/bin/env python3
"""
KLV Receiver Test - Listen for KLV telemetry packets on localhost

This test script listens for KLV (MISB 0601) packets sent by TelemetryForwarder
and decodes them to verify the telemetry stream is working correctly.
"""

import socket
import sys
import time
import struct
from datetime import datetime


def decode_klv_packet(data):
    """
    Simple MISB 0601 KLV packet decoder.
    
    Args:
        data: Raw KLV packet bytes
        
    Returns:
        Dictionary with decoded telemetry, or None if decoding fails
    """
    try:
        # MISB 0601 Universal Key (16 bytes)
        MISB_0601_KEY = bytes([
            0x06, 0x0E, 0x2B, 0x34, 0x02, 0x0B, 0x01, 0x01,
            0x0E, 0x01, 0x03, 0x01, 0x01, 0x00, 0x00, 0x00
        ])
        
        # Check if packet starts with MISB 0601 key
        if not data.startswith(MISB_0601_KEY):
            return None
        
        offset = 16  # Skip key
        
        # Parse BER length
        length_byte = data[offset]
        offset += 1
        
        if length_byte < 128:
            value_length = length_byte
        elif length_byte == 0x81:
            value_length = data[offset]
            offset += 1
        elif length_byte == 0x82:
            value_length = struct.unpack('>H', data[offset:offset+2])[0]
            offset += 2
        else:
            return None
        
        # Parse Local Data Set items
        telemetry = {}
        end_offset = offset + value_length
        
        while offset < end_offset:
            tag = data[offset]
            offset += 1
            item_length = data[offset]
            offset += 1
            value_bytes = data[offset:offset+item_length]
            offset += item_length
            
            # Decode based on tag
            if tag == 2:  # Unix timestamp (microseconds)
                telemetry['timestamp_us'] = struct.unpack('>Q', value_bytes)[0]
            elif tag == 13:  # Sensor latitude
                scaled = struct.unpack('>i', value_bytes)[0]
                telemetry['latitude'] = scaled / 1e7
            elif tag == 14:  # Sensor longitude
                scaled = struct.unpack('>i', value_bytes)[0]
                telemetry['longitude'] = scaled / 1e7
            elif tag == 15:  # Sensor true altitude
                scaled = struct.unpack('>H', value_bytes)[0]
                telemetry['altitude'] = scaled / 10.0
            elif tag == 5:  # Platform roll
                scaled = struct.unpack('>h', value_bytes)[0]
                telemetry['roll'] = scaled / 100.0
            elif tag == 6:  # Platform pitch
                scaled = struct.unpack('>h', value_bytes)[0]
                telemetry['pitch'] = scaled / 100.0
            elif tag == 7:  # Platform heading
                scaled = struct.unpack('>H', value_bytes)[0]
                telemetry['heading'] = scaled / 100.0
        
        return telemetry
        
    except Exception as e:
        return None


def listen_for_klv(port=12345, duration=60):
    """
    Listen for KLV packets on specified port.
    
    Args:
        port: UDP port to listen on
        duration: How long to listen in seconds (0 = indefinite)
    """
    print("=" * 70)
    print(f"KLV Telemetry Receiver Test")
    print(f"Listening on localhost:{port}")
    print(f"Duration: {'indefinite' if duration == 0 else f'{duration} seconds'}")
    print("=" * 70)
    print()
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)  # 1 second timeout for checking duration
    
    try:
        sock.bind(('127.0.0.1', port))
        print(f"✓ Successfully bound to port {port}")
        print("Waiting for KLV packets... (Ctrl+C to stop)")
        print()
    except OSError as e:
        print(f"✗ ERROR: Could not bind to port {port}: {e}")
        print(f"  Port may already be in use. Try a different port.")
        sys.exit(1)
    
    packet_count = 0
    start_time = time.time()
    last_packet_time = start_time
    
    try:
        while True:
            # Check duration limit
            if duration > 0 and (time.time() - start_time) >= duration:
                print(f"\n✓ Duration limit reached ({duration}s)")
                break
            
            try:
                # Receive KLV packet
                data, addr = sock.recvfrom(65535)
                packet_count += 1
                current_time = time.time()
                
                # Calculate packet rate
                time_diff = current_time - last_packet_time
                last_packet_time = current_time
                
                print(f"\n{'='*70}")
                print(f"Packet #{packet_count} received from {addr[0]}:{addr[1]}")
                print(f"Size: {len(data)} bytes | Time since last: {time_diff:.3f}s")
                print(f"{'='*70}")
                
                # Try to decode KLV packet
                telemetry = decode_klv_packet(data)
                
                if telemetry:
                    print("\n📦 KLV Packet Decoded:")
                    print(f"  MISB 0601 Universal Key detected")
                    print(f"  Total packet size: {len(data)} bytes")
                    
                    print("\n📍 MISB 0601 Telemetry Data:")
                    
                    # Extract and display telemetry fields
                    if 'timestamp_us' in telemetry:
                        ts = datetime.fromtimestamp(telemetry['timestamp_us'] / 1_000_000)
                        print(f"  Timestamp: {ts.isoformat()} UTC")
                    
                    if 'latitude' in telemetry:
                        print(f"  Latitude: {telemetry['latitude']:.7f}°")
                    
                    if 'longitude' in telemetry:
                        print(f"  Longitude: {telemetry['longitude']:.7f}°")
                    
                    if 'altitude' in telemetry:
                        print(f"  Altitude: {telemetry['altitude']:.2f} m")
                    
                    if 'roll' in telemetry:
                        print(f"  Roll: {telemetry['roll']:.2f}°")
                    
                    if 'pitch' in telemetry:
                        print(f"  Pitch: {telemetry['pitch']:.2f}°")
                    
                    if 'heading' in telemetry:
                        print(f"  Heading: {telemetry['heading']:.2f}°")
                    
                    print(f"\n✓ Packet successfully decoded")
                else:
                    print(f"\n⚠ Could not decode KLV packet")
                    print(f"Raw data (first 100 bytes): {data[:100].hex()}")
                
            except socket.timeout:
                # No packet received, continue waiting
                continue
                
    except KeyboardInterrupt:
        print("\n\n⚠ Interrupted by user")
    finally:
        elapsed = time.time() - start_time
        sock.close()
        
        print("\n" + "=" * 70)
        print("📊 Summary:")
        print(f"  Total packets received: {packet_count}")
        print(f"  Duration: {elapsed:.1f}s")
        if packet_count > 0:
            print(f"  Average rate: {packet_count / elapsed:.2f} packets/sec")
        print("=" * 70)


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='KLV Telemetry Receiver Test - Listen for KLV packets from TelemetryForwarder',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--port',
        type=int,
        default=12345,
        help='UDP port to listen on'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=60,
        help='Duration to listen in seconds (0 = indefinite)'
    )
    
    args = parser.parse_args()
    
    try:
        listen_for_klv(port=args.port, duration=args.duration)
    except Exception as e:
        print(f"\n✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

