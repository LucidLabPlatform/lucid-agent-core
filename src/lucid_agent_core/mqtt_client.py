"""
MQTT client for LUCID Agent Core.

Responsibilities:
- Connect + maintain MQTT session (auth, LWT).
- Subscribe to core command topics.
- Dispatch received commands to bounded worker pool.
- Publish retained presence status and snapshots.
- Dynamic heartbeat with thread-safe interval updates.

Business logic (install/uninstall/start/stop) must live in dedicated handlers.
"""

from __future__ import annotations

import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from lucid_agent_core.mqtt_topics import TopicSchema

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class StatusPayload:
    state: str
    ts: str
    version: str
    agent_id: str

    def to_json(self) -> str:
        return json.dumps({
            "state": self.state,
            "ts": self.ts,
            "version": self.version,
            "agent_id": self.agent_id,
        })


class AgentMQTTClient:
    """
    MQTT client wrapper around paho-mqtt.

    Notes:
    - This class is transport + dispatch only.
    - It intentionally does not implement core business logic beyond routing.
    - Context must be set before connect() to enable snapshot publishing.
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

        self.topics = TopicSchema(self.username)
        self.client_id = f"lucid.agent.{self.username}"

        self._client: Optional[mqtt.Client] = None
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="mqtt-cmd"
        )

        # Context (must be set before connect)
        self._ctx: Optional[Any] = None  # CoreCommandContext

        # Handler dispatch table (built after context is set)
        self._handlers: dict[str, Callable[[str], None]] = {}

        # Heartbeat thread management
        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop_event = threading.Event()
        self._hb_interval_lock = threading.Lock()
        self._hb_interval_s = heartbeat_interval_s

    # --------------------
    # Context management
    # --------------------
    def set_context(self, ctx: Any) -> None:
        """
        Set command context and build handler dispatch table.

        Must be called before connect().
        """
        self._ctx = ctx
        self._build_handlers()
        logger.info("Context set, handlers built")

    def _build_handlers(self) -> None:
        """Build handler dispatch table using context."""
        if not self._ctx:
            self._handlers = {}
            return

        # Import handlers here to avoid circular imports
        from lucid_agent_core.core.handlers import (
            on_cfg_set,
            on_install,
            on_refresh,
            on_uninstall,
        )

        ctx = self._ctx
        self._handlers = {
            self.topics.core_cmd_components_install(): lambda p: on_install(ctx, p),
            self.topics.core_cmd_components_uninstall(): lambda p: on_uninstall(ctx, p),
            self.topics.core_cfg_set(): lambda p: on_cfg_set(ctx, p),
            self.topics.core_cmd_refresh(): lambda p: on_refresh(ctx, p),
        }
        logger.debug("Built %d command handlers", len(self._handlers))

    # --------------------
    # Heartbeat management
    # --------------------
    def set_heartbeat_interval(self, interval_s: int) -> None:
        """
        Update heartbeat interval dynamically.

        Thread-safe: can be called while heartbeat is running.
        """
        with self._hb_interval_lock:
            old_interval = self._hb_interval_s
            self._hb_interval_s = interval_s

        logger.info("Heartbeat interval changed from %ds to %ds", old_interval, interval_s)

        # Start or stop heartbeat thread as needed
        if interval_s > 0 and not self._hb_thread:
            self._start_heartbeat()
        elif interval_s == 0 and self._hb_thread:
            self._stop_heartbeat()

    def _start_heartbeat(self) -> None:
        """Start heartbeat thread."""
        if self._hb_thread:
            logger.warning("Heartbeat thread already running")
            return

        self._hb_stop_event.clear()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="mqtt-heartbeat"
        )
        self._hb_thread.start()
        logger.info("Heartbeat thread started")

    def _stop_heartbeat(self) -> None:
        """Stop heartbeat thread."""
        if not self._hb_thread:
            return

        logger.info("Stopping heartbeat thread")
        self._hb_stop_event.set()
        self._hb_thread.join(timeout=2.0)
        self._hb_thread = None

    def _heartbeat_loop(self) -> None:
        """Heartbeat loop: periodically republish status."""
        logger.info("Heartbeat loop started")

        while not self._hb_stop_event.is_set():
            # Get current interval
            with self._hb_interval_lock:
                interval = self._hb_interval_s

            if interval <= 0:
                logger.info("Heartbeat interval is 0, stopping")
                break

            # Wait for interval or stop signal
            if self._hb_stop_event.wait(timeout=interval):
                break

            # Publish status if connected
            if self._client and self._client.is_connected():
                try:
                    self._publish_status("online")
                    logger.debug("Heartbeat: published status")
                except Exception as exc:
                    logger.error("Heartbeat publish failed: %s", exc)

        logger.info("Heartbeat loop exited")

    # --------------------
    # Internal helpers
    # --------------------
    def _status_payload(self, state: str) -> str:
        return StatusPayload(
            state=state,
            ts=_utc_iso(),
            version=self.version,
            agent_id=self.username,
        ).to_json()

    def _publish_status(self, state: str) -> None:
        """Publish status using legacy method (for LWT and fallback)."""
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

        if not self._ctx:
            logger.error("Connected but context not set; snapshots cannot be published")
            self._publish_status("online")
            return

        # Subscribe to command topics
        for topic in self._handlers.keys():
            client.subscribe(topic, qos=1)
            logger.info("Subscribed: %s", topic)

        # Publish retained snapshots using ctx.publish()
        try:
            from lucid_agent_core.components.registry import load_registry
            from lucid_agent_core.core.snapshots import (
                build_core_cfg_state,
                build_core_components_snapshot,
                build_core_metadata,
                build_core_state,
                build_status_payload,
            )

            ctx = self._ctx

            # Status
            status = build_status_payload("online", self.version, ctx.agent_id)
            ctx.publish(self.topics.status(), status, retain=True, qos=1)

            # Core metadata
            metadata = build_core_metadata(ctx.agent_id, self.version)
            ctx.publish(self.topics.core_metadata(), metadata, retain=True, qos=1)

            # Core state
            state = build_core_state(ctx.agent_id)
            ctx.publish(self.topics.core_state(), state, retain=True, qos=1)

            # Core components
            registry = load_registry()
            components = build_core_components_snapshot(registry)
            ctx.publish(self.topics.core_components(), components, retain=True, qos=1)

            # Core cfg state (use cached config, no I/O)
            cfg = ctx.config_store.get_cached()
            cfg_state = build_core_cfg_state(cfg)
            ctx.publish(self.topics.core_cfg_state(), cfg_state, retain=True, qos=1)

            logger.info("Published all retained snapshots on connect")

        except Exception as exc:
            logger.exception("Failed to publish retained snapshots: %s", exc)

        # Start heartbeat if configured
        with self._hb_interval_lock:
            interval = self._hb_interval_s
        if interval > 0:
            self._start_heartbeat()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc != 0:
            logger.warning("Unexpected disconnect rc=%s", rc)
        else:
            logger.info("Disconnected cleanly")

        # Stop heartbeat on disconnect
        self._stop_heartbeat()

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        if not self._ctx:
            logger.error("Message received before context set: %s", msg.topic)
            return

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
            client.loop_start()  # CRITICAL: enables wait_for_publish()

            self._client = client

            return True
        except Exception:
            logger.exception("Failed to connect to MQTT broker")
            return False

    def disconnect(self) -> None:
        if not self._client:
            return
        try:
            # Stop heartbeat first
            self._stop_heartbeat()

            # publish offline on clean shutdown
            self._publish_status("offline")
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._client = None
            self._executor.shutdown(wait=False, cancel_futures=True)

    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected())

    def publish(self, topic: str, payload: Any, *, qos: int = 0, retain: bool = False) -> Any:
        """
        Publish a message to MQTT broker.

        Returns MQTTMessageInfo for wait_for_publish().
        """
        if not self._client:
            raise RuntimeError("MQTT client not connected")

        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)

        return self._client.publish(topic, payload=payload, qos=qos, retain=retain)
