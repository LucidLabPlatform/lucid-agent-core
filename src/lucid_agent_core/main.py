"""
LUCID Agent Core
Connects to MQTT broker and publishes agent status
"""

import argparse
import logging
import signal
import sys
import time

from lucid_agent_core import config
from lucid_agent_core import mqtt_client


def _get_version():
    """Package version from installed metadata (authoritative)."""
    return config.get_package_version()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global instance for signal handling
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

    parser = argparse.ArgumentParser(
        prog="lucid-agent-core",
        description="LUCID Agent Core: connects to MQTT broker and publishes agent status.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {_get_version()}")
    parser.parse_args()

    config.load_config()

    logger.info("=" * 60)
    logger.info("LUCID Agent Core")
    logger.info("=" * 60)
    logger.info(f"Username: {config.AGENT_USERNAME}")

    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Create and connect agent
    agent = mqtt_client.AgentMQTTClient(
        config.MQTT_HOST,
        config.MQTT_PORT,
        config.AGENT_USERNAME,
        config.AGENT_PASSWORD,
        config.AGENT_VERSION,
        config.AGENT_HEARTBEAT,
    )
    
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
