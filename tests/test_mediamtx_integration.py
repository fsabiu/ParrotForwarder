#!/usr/bin/env python3
"""
Test script for MediaMTX integration

This script tests the new video forwarding implementation without requiring
a drone connection. It simulates the video forwarder setup and MediaMTX connection.
"""

import sys
import os
import time
import logging
import subprocess
import tempfile

# Add the project root to the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parrot_forwarder.video import VideoForwarder

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(name)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)


class MockDrone:
    """Mock drone class for testing."""
    
    def __init__(self):
        self.streaming = MockStreaming()
    
    def get_state(self, state_class):
        """Mock get_state method."""
        return None


class MockStreaming:
    """Mock streaming class for testing."""
    
    def __init__(self):
        self.callbacks = {}
    
    def set_callbacks(self, **kwargs):
        """Mock set_callbacks method."""
        self.callbacks.update(kwargs)
        logger.info("Mock streaming callbacks set")
    
    def start(self):
        """Mock start method."""
        logger.info("Mock streaming started")
    
    def stop(self):
        """Mock stop method."""
        logger.info("Mock streaming stopped")


def test_mediamtx_connection():
    """Test MediaMTX server connection."""
    logger.info("Testing MediaMTX server connection...")
    
    try:
        # Test if MediaMTX is running by checking if port 8554 is open
        import socket
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex(('localhost', 8554))
        sock.close()
        
        if result == 0:
            logger.info("✓ MediaMTX server is running on port 8554")
            return True
        else:
            logger.warning("⚠ MediaMTX server is not accessible on port 8554")
            return False
            
    except Exception as e:
        logger.error(f"✗ Error testing MediaMTX connection: {e}")
        return False


def test_ffmpeg_availability():
    """Test if FFmpeg is available."""
    logger.info("Testing FFmpeg availability...")
    
    try:
        result = subprocess.run(['ffmpeg', '-version'], 
                              capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            logger.info("✓ FFmpeg is available")
            return True
        else:
            logger.error("✗ FFmpeg is not working properly")
            return False
    except FileNotFoundError:
        logger.error("✗ FFmpeg is not installed")
        return False
    except Exception as e:
        logger.error(f"✗ Error testing FFmpeg: {e}")
        return False


def test_video_forwarder_initialization():
    """Test VideoForwarder initialization."""
    logger.info("Testing VideoForwarder initialization...")
    
    try:
        mock_drone = MockDrone()
        
        # Test with default parameters
        forwarder = VideoForwarder(
            drone=mock_drone,
            fps=30,
            mediamtx_host='localhost',
            mediamtx_port=8554,
            stream_path='test_stream'
        )
        
        logger.info("✓ VideoForwarder initialized successfully")
        logger.info(f"  RTSP URL: {forwarder.rtsp_url}")
        
        # Test setup_streaming (this will try to create FFmpeg process)
        try:
            forwarder.setup_streaming()
            logger.info("✓ VideoForwarder setup_streaming completed")
            
            # Clean up
            forwarder.cleanup_ffmpeg()
            logger.info("✓ FFmpeg cleanup completed")
            
        except Exception as e:
            logger.warning(f"⚠ setup_streaming failed (expected if MediaMTX not running): {e}")
        
        return True
        
    except Exception as e:
        logger.error(f"✗ Error initializing VideoForwarder: {e}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("MediaMTX Integration Test")
    logger.info("=" * 60)
    
    tests = [
        ("FFmpeg Availability", test_ffmpeg_availability),
        ("MediaMTX Connection", test_mediamtx_connection),
        ("VideoForwarder Initialization", test_video_forwarder_initialization),
    ]
    
    results = []
    for test_name, test_func in tests:
        logger.info(f"\n--- {test_name} ---")
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"✗ Test '{test_name}' failed with exception: {e}")
            results.append((test_name, False))
    
    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Results Summary")
    logger.info("=" * 60)
    
    passed = 0
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status} - {test_name}")
        if result:
            passed += 1
    
    logger.info(f"\nPassed: {passed}/{len(results)} tests")
    
    if passed == len(results):
        logger.info("🎉 All tests passed! MediaMTX integration is ready.")
    else:
        logger.warning("⚠ Some tests failed. Check the logs above for details.")
    
    return passed == len(results)


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
