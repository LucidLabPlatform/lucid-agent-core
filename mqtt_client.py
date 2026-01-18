"""
MQTT Client for Agent Core
Handles connection, LWT, and status publishing
"""

import json
import logging
from datetime import datetime, timezone
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

class AgentMQTTClient:
    """Minimal MQTT client for agent lifecycle management"""
    
    def __init__(self, device_id, host, port, username, password, version):
        self.device_id = device_id
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.version = version
        self.client_id = f"lucid.agent.{self.username}"
        self.status_topic = f"lucid/agents/{self.username}/status"
        self.client = None
    
    def _get_timestamp(self):
        """Get current UTC timestamp in ISO format"""
        return datetime.now(timezone.utc).isoformat()
    
    def _create_status_payload(self, state):
        """Create status message payload"""
        payload = {
            "state": state,
            "ts": self._get_timestamp()
        }
        if state == "online":
            payload["version"] = self.version
        return json.dumps(payload)
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connection is established"""
        if rc == 0:
            logger.info(f"Agent {self.device_id} connected to broker")
            # Publish online status (retained)
            online_payload = self._create_status_payload("online")
            client.publish(
                self.status_topic,
                payload=online_payload,
                qos=1,
                retain=True
            )
            logger.info(f"Published online status to {self.status_topic}")
        else:
            logger.error(f"Connection failed with code {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected"""
        if rc != 0:
            logger.warning(f"Unexpected disconnection (code {rc})")
        else:
            logger.info("Disconnected cleanly")
    
    def connect(self):
        """Connect to MQTT broker with LWT configured"""
        logger.info(f"Initializing agent: {self.device_id}")
        logger.info(f"Client ID: {self.client_id}")
        logger.info(f"Broker: {self.host}:{self.port}")
        
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
        try:
            self.client.connect(self.host, self.port, keepalive=60)
            self.client.loop_start()
            return True
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            return False
    
    def disconnect(self):
        """Disconnect from broker cleanly"""
        if self.client:
            logger.info("Disconnecting from broker")
            # Publish offline status before clean disconnect
            # (LWT only triggers on unexpected disconnect)
            offline_payload = self._create_status_payload("offline")
            self.client.publish(
                self.status_topic,
                payload=offline_payload,
                qos=1,
                retain=True
            )
            logger.info(f"Published offline status to {self.status_topic}")
            self.client.loop_stop()
            self.client.disconnect()
    
    def is_connected(self):
        """Check if client is connected"""
        return self.client and self.client.is_connected()
