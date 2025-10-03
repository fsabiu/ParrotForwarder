#!/usr/bin/env python3
"""
Simple UDP telemetry receiver for testing ParrotForwarder.
Receives and displays JSON telemetry packets from the drone.
"""

import socket
import json
import logging
import argparse
from datetime import datetime

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description='Receive telemetry from ParrotForwarder',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--port',
        type=int,
        default=5000,
        help='UDP port to listen on'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print full telemetry data'
    )
    
    args = parser.parse_args()
    
    # Create UDP socket
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('0.0.0.0', args.port))
    
    logger.info(f"Listening for telemetry on UDP port {args.port}...")
    logger.info("Press Ctrl+C to stop")
    logger.info("=" * 60)
    
    packet_count = 0
    last_stats_time = datetime.now()
    
    try:
        while True:
            # Receive UDP packet
            data, addr = sock.recvfrom(65535)
            packet_count += 1
            
            try:
                # Parse JSON telemetry
                telemetry = json.loads(data.decode('utf-8'))
                
                # Print summary or full data
                if args.verbose:
                    logger.info(f"Telemetry #{packet_count} from {addr[0]}:")
                    logger.info(json.dumps(telemetry, indent=2))
                else:
                    # Print compact summary with GPS coordinates
                    lat = telemetry.get('latitude', None)
                    lon = telemetry.get('longitude', None)
                    alt_msl = telemetry.get('altitude', None)
                    alt_agl = telemetry.get('altitude_agl', None)
                    
                    logger.info(
                        f"#{packet_count:05d} | "
                        f"Battery: {telemetry.get('battery_percent', 'N/A')}% | "
                        f"GPS: {telemetry.get('gps_fixed', 'N/A')} | "
                        f"Lat: {lat if lat else 'N/A'} | "
                        f"Lon: {lon if lon else 'N/A'} | "
                        f"Alt(MSL): {alt_msl if alt_msl else 'N/A'}m | "
                        f"Alt(AGL): {alt_agl if alt_agl else 'N/A'}m | "
                        f"State: {telemetry.get('flying_state', 'N/A')}"
                    )
                
                # Show stats every 5 seconds
                now = datetime.now()
                if (now - last_stats_time).seconds >= 5:
                    logger.info(f"--- Received {packet_count} packets total ---")
                    last_stats_time = now
                    
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON: {e}")
            except Exception as e:
                logger.error(f"Error processing packet: {e}")
                
    except KeyboardInterrupt:
        logger.info("\nStopping receiver...")
        logger.info(f"Total packets received: {packet_count}")
    finally:
        sock.close()


if __name__ == "__main__":
    main()

