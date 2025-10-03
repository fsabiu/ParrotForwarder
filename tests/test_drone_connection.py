#!/usr/bin/env python3
"""
Test script to verify Parrot Anafi connection via USB and check telemetry.
Logs all drone state information and connection status.
"""

import olympe
from olympe.messages.ardrone3.Piloting import TakeOff, Landing
from olympe.messages.ardrone3.PilotingState import FlyingStateChanged, AlertStateChanged
from olympe.messages.ardrone3.GPSSettingsState import GPSFixStateChanged
from olympe.messages.ardrone3.PilotingState import PositionChanged, SpeedChanged, AltitudeChanged, AttitudeChanged
from olympe.messages.common.CommonState import BatteryStateChanged
import logging
import time

# Configure detailed logging
logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] %(levelname)s - %(message)s',
    datefmt='%H:%M:%S'
)

logger = logging.getLogger(__name__)

# Drone IP address (USB connection)
DRONE_IP = "192.168.53.1"

def main():
    logger.info("=" * 60)
    logger.info("Starting Parrot Anafi USB Connection Test")
    logger.info("=" * 60)
    logger.info(f"Attempting to connect to drone at {DRONE_IP}")
    
    try:
        # Create drone connection object
        drone = olympe.Drone(DRONE_IP)
        
        logger.info("Connecting to drone...")
        connection_status = drone.connect()
        
        if connection_status:
            logger.info("✓ Successfully connected to the drone!")
            logger.info("-" * 60)
            
            # Wait a moment for all telemetry to arrive
            time.sleep(1)
            
            # Get battery information
            logger.info("BATTERY TELEMETRY:")
            battery_state = drone.get_state(BatteryStateChanged)
            if battery_state:
                logger.info(f"  Battery Level: {battery_state['percent']}%")
            else:
                logger.warning("  Could not retrieve battery state")
            
            # Get GPS information
            logger.info("-" * 60)
            logger.info("GPS TELEMETRY:")
            gps_fix = drone.get_state(GPSFixStateChanged)
            if gps_fix:
                logger.info(f"  GPS Fixed: {gps_fix['fixed']}")
            else:
                logger.warning("  Could not retrieve GPS fix state")
            
            # Get position if available
            position = drone.get_state(PositionChanged)
            if position:
                logger.info(f"  Latitude: {position.get('latitude', 'N/A')}")
                logger.info(f"  Longitude: {position.get('longitude', 'N/A')}")
                logger.info(f"  Altitude: {position.get('altitude', 'N/A')} m")
            else:
                logger.info("  Position not available (GPS not fixed yet)")
            
            # Get altitude
            logger.info("-" * 60)
            logger.info("ALTITUDE TELEMETRY:")
            altitude = drone.get_state(AltitudeChanged)
            if altitude:
                logger.info(f"  Altitude: {altitude.get('altitude', 'N/A')} m")
            else:
                logger.info("  Altitude not available")
            
            # Get attitude (orientation)
            logger.info("-" * 60)
            logger.info("ATTITUDE TELEMETRY:")
            attitude = drone.get_state(AttitudeChanged)
            if attitude:
                logger.info(f"  Roll: {attitude.get('roll', 'N/A')} rad")
                logger.info(f"  Pitch: {attitude.get('pitch', 'N/A')} rad")
                logger.info(f"  Yaw: {attitude.get('yaw', 'N/A')} rad")
            else:
                logger.info("  Attitude not available")
            
            # Get speed
            logger.info("-" * 60)
            logger.info("SPEED TELEMETRY:")
            speed = drone.get_state(SpeedChanged)
            if speed:
                logger.info(f"  Speed X: {speed.get('speedX', 'N/A')} m/s")
                logger.info(f"  Speed Y: {speed.get('speedY', 'N/A')} m/s")
                logger.info(f"  Speed Z: {speed.get('speedZ', 'N/A')} m/s")
            else:
                logger.info("  Speed not available")
            
            # Get flying state
            logger.info("-" * 60)
            logger.info("FLYING STATE:")
            flying_state = drone.get_state(FlyingStateChanged)
            if flying_state:
                logger.info(f"  State: {flying_state['state']}")
            else:
                logger.warning("  Could not retrieve flying state")
            
            # Get additional telemetry data
            logger.info("-" * 60)
            logger.info("ADDITIONAL TELEMETRY:")
            logger.info("-" * 60)
            
            # Import additional messages for comprehensive telemetry
            from olympe.messages.ardrone3.PilotingState import NavigateHomeStateChanged
            from olympe.messages.ardrone3.SettingsState import MotorFlightsStatusChanged
            from olympe.messages.common.SettingsState import ProductNameChanged, ProductVersionChanged
            
            # Product info
            product_name = drone.get_state(ProductNameChanged)
            if product_name:
                logger.info(f"  Drone Name: {product_name.get('name', 'N/A')}")
            
            product_version = drone.get_state(ProductVersionChanged)
            if product_version:
                logger.info(f"  Software Version: {product_version.get('software', 'N/A')}")
                logger.info(f"  Hardware Version: {product_version.get('hardware', 'N/A')}")
            
            # Motor/Flight stats
            motor_stats = drone.get_state(MotorFlightsStatusChanged)
            if motor_stats:
                logger.info(f"  Total Flights: {motor_stats.get('nbFlights', 'N/A')}")
                logger.info(f"  Total Flight Time: {motor_stats.get('totalFlightDuration', 'N/A')} seconds")
                logger.info(f"  Last Flight Duration: {motor_stats.get('lastFlightDuration', 'N/A')} seconds")
            
            # RTH (Return to Home) state
            rth_state = drone.get_state(NavigateHomeStateChanged)
            if rth_state:
                logger.info(f"  RTH State: {rth_state.get('state', 'N/A')}")
                logger.info(f"  RTH Reason: {rth_state.get('reason', 'N/A')}")
            
            logger.info("-" * 60)
            logger.info("✓ Telemetry data retrieved successfully")
            
            # Disconnect
            logger.info("-" * 60)
            logger.info("Disconnecting from drone...")
            drone.disconnect()
            logger.info("✓ Disconnected successfully")
            
        else:
            logger.error("✗ Failed to connect to the drone")
            logger.error(f"  Check if drone is powered on and connected via USB")
            logger.error(f"  Verify network interface usb0 exists at 192.168.53.91")
            return 1
            
    except Exception as e:
        logger.error(f"✗ Error occurred: {str(e)}")
        logger.exception("Full exception details:")
        return 1
    
    logger.info("=" * 60)
    logger.info("Test completed successfully")
    logger.info("=" * 60)
    return 0

if __name__ == "__main__":
    exit(main())

