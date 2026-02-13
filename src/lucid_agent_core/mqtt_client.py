"""
MQTT client for LUCID Agent Core.

Responsibilities:
- Connect + maintain MQTT session (auth, LWT).
- Subscribe to core command topics.
- Dispatch received commands to bounded worker pool.
- Publish retained presence status.

Business logic (install/uninstall/start/stop) must live in dedicated handlers.
"""

from __future__ import annotations

import json
import logging
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from lucid_agent_core.core.component_installer import handle_install_component
from lucid_agent_core.mqtt_topics import TopicSchema

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class StatusPayload:
    state: str
    ts: str
    version: str

    def to_json(self) -> str:
        return json.dumps({"state": self.state, "ts": self.ts, "version": self.version})


class AgentMQTTClient:
    """
    MQTT client wrapper around paho-mqtt.

    Notes:
    - This class is transport + dispatch only.
    - It intentionally does not implement core business logic beyond routing.
    """

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
        version: str,
        *,
        keepalive: int = 60,
        max_workers: int = 4,
        heartbeat_interval_s: int = 0,  # 0 disables periodic status refresh
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.version = version
        self.keepalive = keepalive
        self.heartbeat_interval_s = heartbeat_interval_s

        self.topics = TopicSchema(self.username)
        self.client_id = f"lucid.agent.{self.username}"

        self._client: Optional[mqtt.Client] = None
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="mqtt-cmd"
        )

        # dispatch table: topic -> handler(payload_str)
        self._handlers: dict[str, Callable[[str], None]] = {
            # v1.0.0 core commands
            self.topics.core_cmd_components_install(): handle_install_component,
            # add uninstall, refresh, etc. once implemented
        }

    # --------------------
    # Internal helpers
    # --------------------
    def _status_payload(self, state: str) -> str:
        return StatusPayload(state=state, ts=_utc_iso(), version=self.version).to_json()

    def _publish_status(self, state: str) -> None:
        if not self._client:
            return
        self._client.publish(
            self.topics.status(),
            payload=self._status_payload(state),
            qos=1,
            retain=True,
        )

    # --------------------
    # MQTT callbacks
    # --------------------
    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        if rc != 0:
            logger.error("MQTT connect failed rc=%s", rc)
            return

        logger.info("Connected to MQTT broker as %s", self.username)

        # Subscribe to the exact command topics we implement.
        for topic in self._handlers.keys():
            client.subscribe(topic, qos=1)
            logger.info("Subscribed: %s", topic)

        self._publish_status("online")

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc != 0:
            logger.warning("Unexpected disconnect rc=%s", rc)
        else:
            logger.info("Disconnected cleanly")

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        handler = self._handlers.get(msg.topic)
        if not handler:
            logger.warning("Unhandled topic: %s", msg.topic)
            return

        try:
            payload_str = msg.payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.error("Payload decode failed topic=%s err=%s", msg.topic, exc)
            return

        # bounded concurrency: executor limits worker threads
        self._executor.submit(handler, payload_str)

    # --------------------
    # Public API
    # --------------------
    def connect(self) -> bool:
        try:
            client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            client.username_pw_set(self.username, self.password)

            # LWT: broker publishes offline if connection drops
            client.will_set(
                self.topics.status(),
                payload=self._status_payload("offline"),
                qos=1,
                retain=True,
            )

            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message

            client.connect(self.host, self.port, keepalive=self.keepalive)
            client.loop_start()

            self._client = client

            # Optional status refresh (off by default)
            if self.heartbeat_interval_s > 0:
                client.loop_misc()  # no-op; leave refresh to future if needed

            return True
        except Exception:
            logger.exception("Failed to connect to MQTT broker")
            return False

    def disconnect(self) -> None:
        if not self._client:
            return
        try:
            # publish offline on clean shutdown
            self._publish_status("offline")
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._client = None
            self._executor.shutdown(wait=False, cancel_futures=True)

    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected())

    def publish(self, topic: str, payload: Any, *, qos: int = 0, retain: bool = False) -> None:
        if not self._client:
            raise RuntimeError("MQTT client not connected")

        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)

        self._client.publish(topic, payload=payload, qos=qos, retain=retain)
