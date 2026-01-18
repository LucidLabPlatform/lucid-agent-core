"""
Agent Core v0 - Step 1.2
Minimal agent that proves MQTT broker + ACLs work correctly
"""

import logging
import signal
import sys
import time

from mqtt_client import AgentMQTTClient
from config import DEVICE_ID, HOST, PORT, USERNAME, PASSWORD, VERSION

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global agent instance for signal handling
agent = None


def signal_handler(signum, frame):
    """Handle shutdown signals gracefully"""
    logger.info(f"Received signal {signum}, shutting down...")
    if agent:
        agent.disconnect()
    sys.exit(0)


def main():
    """Main entry point"""
    global agent
    
    logger.info("=" * 60)
    logger.info("LUCID Agent Core v0 - Step 1.2")
    logger.info("=" * 60)
    logger.info(f"Device ID: {DEVICE_ID}")
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Create and connect agent
    agent = AgentMQTTClient(DEVICE_ID, HOST, PORT, USERNAME, PASSWORD, VERSION)
    
    if not agent.connect():
        logger.error("Failed to connect to broker. Exiting.")
        sys.exit(1)
    
    # Wait for connection to establish
    time.sleep(1)
    
    if not agent.is_connected():
        logger.error("Agent failed to connect. Exiting.")
        sys.exit(1)
    
    logger.info("=" * 60)
    logger.info("Agent is online and running")
    logger.info("Press Ctrl+C to stop (will trigger LWT)")
    logger.info("=" * 60)
    
    # Keep agent alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
        agent.disconnect()


if __name__ == "__main__":
    main()
