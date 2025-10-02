"""
CLI - Command-line interface for ParrotForwarder

Handles argument parsing and application entry point.
"""

import argparse
import logging
import sys

from .main import ParrotForwarder


# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
    datefmt='%H:%M:%S'
)

# Suppress verbose Olympe SDK logs by default
logging.getLogger('olympe').setLevel(logging.WARNING)
logging.getLogger('ulog').setLevel(logging.WARNING)

logger = logging.getLogger(__name__)


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description='Parrot Anafi Telemetry and Video Forwarder',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--drone-ip',
        type=str,
        default='192.168.53.1',
        help='IP address of the Parrot Anafi drone'
    )
    parser.add_argument(
        '--remote-host',
        type=str,
        default=None,
        help='Remote host IP address to forward data to (required for forwarding)'
    )
    parser.add_argument(
        '--telemetry-port',
        type=int,
        default=5000,
        help='UDP port for telemetry forwarding'
    )
    parser.add_argument(
        '--video-port',
        type=int,
        default=5004,
        help='UDP/RTP port for video forwarding'
    )
    parser.add_argument(
        '--telemetry-fps',
        type=int,
        default=10,
        help='Frames per second for telemetry forwarding'
    )
    parser.add_argument(
        '--video-fps',
        type=int,
        default=30,
        help='Frames per second for video forwarding'
    )
    parser.add_argument(
        '--duration',
        type=int,
        default=None,
        help='Duration to run in seconds (default: run indefinitely)'
    )
    parser.add_argument(
        '--max-retries',
        type=int,
        default=None,
        help='Maximum connection retry attempts (default: infinite)'
    )
    parser.add_argument(
        '--retry-interval',
        type=int,
        default=5,
        help='Seconds to wait between connection retries (default: 5)'
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Enable verbose SDK logging (shows all Olympe logs)'
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Enable verbose SDK logging if requested
    if args.verbose:
        logging.getLogger('olympe').setLevel(logging.INFO)
        logging.getLogger('ulog').setLevel(logging.INFO)
        logger.info("Verbose SDK logging enabled")
    
    # Debug: log parsed arguments
    logger.info(f"DEBUG: Parsed args - remote_host={args.remote_host}, telemetry_port={args.telemetry_port}")
    
    # Validate arguments
    if args.remote_host is None:
        logger.warning("No --remote-host specified. Running in monitoring mode (no forwarding).")
    
    # Create and run forwarder
    try:
        forwarder = ParrotForwarder(
            drone_ip=args.drone_ip,
            telemetry_fps=args.telemetry_fps,
            video_fps=args.video_fps,
            remote_host=args.remote_host,
            telemetry_port=args.telemetry_port,
            video_port=args.video_port
        )
        
        forwarder.run(
            duration=args.duration,
            max_retries=args.max_retries,
            retry_interval=args.retry_interval
        )
        
    except KeyboardInterrupt:
        logger.info("\n✓ Exited cleanly")
        return 0
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

