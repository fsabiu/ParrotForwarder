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
        description='Parrot Anafi Telemetry and Video Forwarder - Unified SRT stream with KLV metadata',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument(
        '--drone-ip',
        type=str,
        default='192.168.53.1',
        help='IP address of the Parrot Anafi drone'
    )
    parser.add_argument(
        '--srt-port',
        type=int,
        default=8890,
        help='SRT port for video stream output'
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
        '--no-auto-reconnect',
        action='store_true',
        help='Disable automatic reconnection on drone disconnect'
    )
    parser.add_argument(
        '--health-check-interval',
        type=int,
        default=5,
        help='Seconds between connection health checks (default: 5)'
    )
    parser.add_argument(
        '--video-stats-interval',
        type=int,
        default=30,
        help='Seconds between video status reports (default: 30)'
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
    
    logger.info("Unified stream: Video (H.264) + Telemetry (KLV/MISB 0601)")
    logger.info("Using GStreamer for native KLV muxing")
    logger.info(f"Output: SRT stream on port {args.srt_port}")
    logger.info(f"Client: ffplay 'srt://<your-ip>:{args.srt_port}'")
    
    # Create and run forwarder
    try:
        forwarder = ParrotForwarder(
            drone_ip=args.drone_ip,
            telemetry_fps=args.telemetry_fps,
            video_fps=args.video_fps,
            srt_port=args.srt_port,
            auto_reconnect=not args.no_auto_reconnect,
            health_check_interval=args.health_check_interval,
            video_stats_interval=args.video_stats_interval
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
        import traceback
        logger.error(f"Fatal error: {e}")
        logger.error(f"Traceback: {traceback.format_exc()}")
        return 1
    
    return 0


if __name__ == '__main__':
    sys.exit(main())

