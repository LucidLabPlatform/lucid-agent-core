"""
MQTT Client for Agent Core
Handles connection, LWT, and status publishing
"""

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, Callable, Optional

import paho.mqtt.client as mqtt
from lucid_agent_core.mqtt_topics import TopicSchema

logger = logging.getLogger(__name__)


class AgentMQTTClient:
    """MQTT client for agent lifecycle"""
    
    def __init__(self, device_id: str, host: str, port: int, 
                 username: str, password: str, version: str, heartbeat_interval: int = 30):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.version = version
        
        # Topic schema
        self.topics = TopicSchema(self.username)
        
        # Topic structure
        self.client_id = f"lucid.agent.{self.username}"
        self.base_topic = f"lucid/agents/{self.username}"
        self.status_topic = self.topics.status()
        
        # MQTT client
        self.client = None

        # Heartbeat configuration (seconds)
        self._heartbeat_interval = heartbeat_interval
        self._heartbeat_thread: Optional[threading.Thread] = None
        self._stop_heartbeat = threading.Event()
    
    def _get_timestamp(self) -> str:
        """Get current UTC timestamp in ISO format"""
        return datetime.now(timezone.utc).isoformat()
    
    def _create_status_payload(self, state: str) -> str:
        """Create status message payload"""
        payload = {
            "state": state,
            "ts": self._get_timestamp(),
            "version": self.version
        }
        return json.dumps(payload)
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connection is established"""
        if rc == 0:
            logger.info(f"Agent {self.device_id} connected to broker")
            self._publish_status("online")
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected"""
        # Stop heartbeat when broker disconnects us
        self._stop_heartbeat.set()

        if rc != 0:
            logger.warning(f"Unexpected disconnection (code {rc})")
        else:
            logger.info("Disconnected cleanly")
    
    def _on_message(self, client, userdata, msg):
        """Callback when a message is received"""
        # No message handling for minimal agent-only version
        pass
    
    def _publish_status(self, state: str):
        """Publish agent status"""
        payload = self._create_status_payload(state)
        self.client.publish(
            self.status_topic,
            payload=payload,
            qos=1,
            retain=True
        )
        logger.info(f"Published {state} status to {self.status_topic}")
    
    def connect(self) -> bool:
        """Connect to MQTT broker with LWT configured"""
        logger.info(f"Initializing agent: {self.device_id}")
        logger.info(f"Client ID: {self.client_id}")
        logger.info(f"Broker: {self.host}:{self.port}")
        
        try:
            # Create MQTT client
            self.client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            
            # Set credentials
            self.client.username_pw_set(self.username, self.password)
            
            # Configure Last Will and Testament (LWT)
            lwt_payload = self._create_status_payload("offline")
            self.client.will_set(
                self.status_topic,
                payload=lwt_payload,
                qos=1,
                retain=True
            )
            logger.info(f"LWT configured for {self.status_topic}")
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            
            # Connect to broker
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()

            # Start heartbeat loop to periodically refresh status
            self._stop_heartbeat.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop,
                name="AgentMQTTHeartbeat",
                daemon=True,
            )
            self._heartbeat_thread.start()

            return True
        
        except Exception as e:
            logger.error(f"Failed to connect: {e}", exc_info=True)
            return False
    
    def disconnect(self):
        """Disconnect from broker cleanly"""
        if self.client:
            logger.info("Disconnecting from broker")

            # Stop heartbeat loop
            self._stop_heartbeat.set()

            # Publish offline status before clean disconnect
            # (LWT only triggers on unexpected disconnect)
            self._publish_status("offline")
            
            self.client.loop_stop()
            self.client.disconnect()
    
    def is_connected(self) -> bool:
        """Check if client is connected"""
        return bool(self.client and self.client.is_connected())

    def _heartbeat_loop(self):
        """Periodically publish 'online' status as heartbeat (retained)."""
        logger.info(
            f"Starting MQTT heartbeat loop (interval={self._heartbeat_interval}s)"
        )
        while not self._stop_heartbeat.is_set():
            try:
                if self.client and self.client.is_connected():
                    self._publish_status("online")
            except Exception as e:
                logger.error(f"Error in MQTT heartbeat loop: {e}", exc_info=True)
            # Wait with interruption support
            self._stop_heartbeat.wait(self._heartbeat_interval)
    
    def publish(self, topic: str, payload, qos: int = 0, retain: bool = False):
        """
        Publish a message to a topic
        
        Args:
            topic: MQTT topic
            payload: Message payload (dict will be JSON serialized)
            qos: Quality of Service level
            retain: Whether to retain the message
        """
        if not self.client:
            logger.error("Cannot publish - client not initialized")
            return
        
        # Serialize dict to JSON
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        
        self.client.publish(topic, payload, qos=qos, retain=retain)
        logger.debug(f"Published to {topic}")
