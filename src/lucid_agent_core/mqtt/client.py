"""
AgentMQTTClient — Paho connection, message routing, and component lifecycle.

Delegates heartbeat to HeartbeatLoop, telemetry to TelemetryLoop,
component subscriptions to component_subscriptions helpers,
and retained publishing to retained helpers.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import paho.mqtt.client as mqtt

from lucid_agent_core.mqtt_topics import TopicSchema
from lucid_agent_core.mqtt.heartbeat import HeartbeatLoop, StatusPayload
from lucid_agent_core.mqtt.telemetry import TelemetryLoop

logger = logging.getLogger(__name__)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AgentMQTTClient:
    """
    MQTT client for the LUCID agent.

    Call set_context() before connect(). After connect(), call add_component_handlers()
    to subscribe to component cmd topics.
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
        heartbeat_interval_s: int = 0,
    ) -> None:
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.version = version
        self.keepalive = keepalive

        self.topics = TopicSchema(username)
        self.client_id = f"lucid.agent.{username}"

        self._client: Optional[mqtt.Client] = None
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="mqtt-cmd")

        self._ctx: Optional[Any] = None
        self._handlers: dict[str, Callable[[str], None]] = {}
        self._components: list[Any] = []
        self._components_lock = threading.Lock()
        # Serialises concurrent start/stop operations so the read-check-act
        # sequence in start_component/stop_component is atomic.
        self._lifecycle_lock = threading.Lock()
        self._connected_since_ts: Optional[str] = None
        self._connected_ts: Optional[float] = None

        # Per-component cmd topics (for unsubscribe on stop)
        self._component_cmd_topics: dict[str, set[str]] = {}

        # Rate-limit concurrent in-flight command handlers. Keeps the
        # executor queue bounded so a flood of MQTT commands cannot exhaust
        # memory or trigger unbounded installs/restarts on the Pi.
        self._inflight_limit = max_workers * 8
        self._inflight_sem = threading.Semaphore(self._inflight_limit)

        # Heartbeat
        self._heartbeat = HeartbeatLoop(
            paho_publish=self._paho_publish,
            status_topic=self.topics.status(),
            get_connection_info=self._get_connection_info,
        )
        self._hb_interval_s = heartbeat_interval_s

        # Telemetry
        self._telemetry = TelemetryLoop(
            paho_publish=self._paho_publish,
            get_ctx=lambda: self._ctx,
            is_connected=self.is_connected,
            topics=self.topics,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _paho_publish(self, topic: str, payload: Any = None, *, qos: int = 0, retain: bool = False) -> Any:
        """Bare paho publish — used by heartbeat/telemetry loops."""
        if self._client:
            return self._client.publish(topic, payload=payload, qos=qos, retain=retain)

    def _get_connection_info(self) -> Optional[tuple[str, float]]:
        """Return (connected_since_ts, connected_ts) if connected, else None."""
        if self._client and self._client.is_connected() and self._connected_ts is not None:
            return self._connected_since_ts or _utc_iso(), self._connected_ts
        return None

    # ------------------------------------------------------------------
    # Context + handlers
    # ------------------------------------------------------------------

    def set_context(self, ctx: Any) -> None:
        """Set command context and build agent command handlers. Call before connect()."""
        self._ctx = ctx
        self._build_handlers()
        self._setup_mqtt_logging()
        logger.info("Context set, handlers built")

    def _setup_mqtt_logging(self) -> None:
        try:
            from lucid_agent_core.core.mqtt_log_handler import MQTTLogHandler

            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if isinstance(handler, MQTTLogHandler) and handler.topic == self.topics.logs():
                    return
            handler = MQTTLogHandler(self, self.topics.logs())
            handler.setLevel(logging.DEBUG)
            root_logger.addHandler(handler)
            logger.info("MQTT logging handler added for core logs")
        except Exception as exc:
            logger.warning("Failed to set up MQTT logging: %s", exc)

    def _build_handlers(self) -> None:
        if not self._ctx:
            self._handlers = {}
            return

        from lucid_agent_core.core.handlers import (
            on_ping,
            on_restart,
            on_refresh,
            on_cfg_set,
            on_cfg_logging_set,
            on_cfg_telemetry_set,
            on_components_install,
            on_components_uninstall,
            on_components_enable,
            on_components_disable,
            on_components_upgrade,
            on_core_upgrade,
        )

        ctx = self._ctx
        self._handlers = {
            self.topics.cmd_ping(): lambda p: on_ping(ctx, p),
            self.topics.cmd_restart(): lambda p: on_restart(ctx, p),
            self.topics.cmd_refresh(): lambda p: on_refresh(ctx, p),
            self.topics.cmd_cfg_set(): lambda p: on_cfg_set(ctx, p),
            self.topics.cmd_cfg_logging_set(): lambda p: on_cfg_logging_set(ctx, p),
            self.topics.cmd_cfg_telemetry_set(): lambda p: on_cfg_telemetry_set(ctx, p),
            self.topics.cmd_components_install(): lambda p: on_components_install(ctx, p),
            self.topics.cmd_components_uninstall(): lambda p: on_components_uninstall(ctx, p),
            self.topics.cmd_components_enable(): lambda p: on_components_enable(ctx, p),
            self.topics.cmd_components_disable(): lambda p: on_components_disable(ctx, p),
            self.topics.cmd_components_upgrade(): lambda p: on_components_upgrade(ctx, p),
            self.topics.cmd_core_upgrade(): lambda p: on_core_upgrade(ctx, p),
        }
        logger.debug("Built %d agent command handlers", len(self._handlers))

    # ------------------------------------------------------------------
    # Component lifecycle
    # ------------------------------------------------------------------

    @staticmethod
    def _action_to_method_name(action: str) -> str:
        return "on_cmd_" + action.replace("/", "_").replace("-", "_")

    def add_component_handlers(self, components: list[Any], registry: dict[str, dict]) -> None:
        """Subscribe to each component's cmd topics. Call after connect() and load_components()."""
        from lucid_agent_core.mqtt.component_subscriptions import add_component_handlers

        with self._components_lock:
            self._components = list(components)

        add_component_handlers(
            self._client,
            self._handlers,
            self._component_cmd_topics,
            self.topics,
            components,
            registry,
        )

    def _subscribe_component_topics(self, comp: Any, component_id: str) -> None:
        """Subscribe to a single component's command topics."""
        from lucid_agent_core.mqtt.component_subscriptions import subscribe_component_topics

        subscribe_component_topics(
            self._client,
            self._handlers,
            self._component_cmd_topics,
            self.topics,
            comp,
            component_id,
        )

    def get_component(self, component_id: str) -> Optional[Any]:
        """Return the component with the given ID, or None if not found."""
        with self._components_lock:
            for comp in self._components:
                if getattr(comp, "component_id", None) == component_id:
                    return comp
        return None

    def stop_component(self, component_id: str) -> bool:
        """Stop a running component and unsubscribe its cmd topics."""
        from lucid_agent_core.mqtt.component_subscriptions import unsubscribe_component_topics

        with self._lifecycle_lock:
            comp = self.get_component(component_id)
            if comp is None:
                return False

            try:
                comp.stop()
                logger.info("Stopped component: %s", component_id)
                if hasattr(comp, "_publish_all_retained"):
                    try:
                        comp._publish_all_retained()
                        logger.info("Republished retained topics for stopped component: %s", component_id)
                    except Exception as exc:
                        logger.warning("Failed to republish retained for %s: %s", component_id, exc)
            except Exception as exc:
                logger.exception("Failed to stop component %s: %s", component_id, exc)
                return False

            topics_to_unsub = self._component_cmd_topics.pop(component_id, set())
            unsubscribe_component_topics(self._client, self._handlers, topics_to_unsub)
            return True

    def start_component(self, component_id: str, registry: dict[str, dict]) -> bool:
        """Start a component by ID. Returns True if started, False otherwise."""
        with self._lifecycle_lock:
            return self._start_component_locked(component_id, registry)

    def _start_component_locked(self, component_id: str, registry: dict[str, dict]) -> bool:
        """Inner implementation — must be called with _lifecycle_lock held."""
        from lucid_agent_core.components.registry import load_registry as _load_registry

        reg = registry if registry else _load_registry()
        if component_id not in reg:
            return False

        meta = reg[component_id]
        if meta.get("enabled") is False:
            return False

        comp = self.get_component(component_id)
        if comp is not None:
            from lucid_component_base import ComponentStatus

            current_status = None
            if hasattr(comp, "state") and hasattr(comp.state, "status"):
                current_status = comp.state.status
                logger.info("Component %s found, status: %s", component_id, current_status.value)
            else:
                logger.warning("Component %s found but missing state attribute", component_id)

            if current_status == ComponentStatus.RUNNING:
                logger.info("Component %s already running, resubscribing", component_id)
                self._subscribe_component_topics(comp, component_id)
                if hasattr(comp, "_publish_all_retained"):
                    try:
                        comp._publish_all_retained()
                    except Exception as exc:
                        logger.warning("Failed to republish retained for %s: %s", component_id, exc)
                return True

            if current_status in (ComponentStatus.STOPPED, ComponentStatus.FAILED, None):
                logger.info("Component %s is %s, starting", component_id,
                            current_status.value if current_status else "unknown")
                try:
                    comp.start()
                    logger.info("Started component: %s", component_id)
                    self._subscribe_component_topics(comp, component_id)
                    if hasattr(comp, "_publish_all_retained"):
                        try:
                            comp._publish_all_retained()
                        except Exception as exc:
                            logger.warning("Failed to republish retained for %s: %s", component_id, exc)
                    return True
                except Exception as exc:
                    logger.exception("Failed to start component %s: %s", component_id, exc)
                    return False

            if current_status in (ComponentStatus.STARTING, ComponentStatus.STOPPING):
                logger.warning("Component %s is in transitional state %s", component_id,
                               current_status.value)
                return False

        # Component not in memory — try dynamic loading (e.g. after install)
        logger.info("Component %s not loaded; attempting dynamic load", component_id)
        try:
            import importlib
            importlib.invalidate_caches()
            from lucid_agent_core.components.loader import load_single_component

            comp = load_single_component(
                component_id=component_id,
                registry_entry=meta,
                agent_id=self.username,
                base_topic=self.topics.base,
                mqtt=self,
            )
            if comp is None:
                logger.warning("Dynamic load failed for %s — restart required", component_id)
                return False

            comp.start()
            with self._components_lock:
                self._components.append(comp)
            self._subscribe_component_topics(comp, component_id)
            if hasattr(comp, "_publish_all_retained"):
                try:
                    comp._publish_all_retained()
                except Exception as exc:
                    logger.warning("Failed to republish retained for %s: %s", component_id, exc)
            logger.info("Dynamically loaded and started component: %s", component_id)
            return True
        except Exception as exc:
            logger.exception("Dynamic load failed for %s: %s — restart required", component_id, exc)
            return False

    # ------------------------------------------------------------------
    # Retained publishing
    # ------------------------------------------------------------------

    def publish_retained_state(self, components_list: list[dict[str, Any]]) -> None:
        """Publish retained state with the current components list."""
        if not self._ctx or not self._client:
            return
        from lucid_agent_core.mqtt.retained import publish_retained_state
        publish_retained_state(self._ctx, self.topics, components_list)

    def publish_retained_refresh(self, components_list: list[dict[str, Any]]) -> None:
        """Republish all retained snapshots: metadata, status, state, cfg, cfg/logging, cfg/telemetry."""
        if not self._ctx or not self._client:
            return
        from lucid_agent_core.mqtt.retained import publish_retained_refresh
        publish_retained_refresh(
            self._ctx,
            self.topics,
            components_list,
            self._connected_ts,
            self._connected_since_ts,
            self.version,
        )

    # ------------------------------------------------------------------
    # Heartbeat
    # ------------------------------------------------------------------

    def set_heartbeat_interval(self, interval_s: int) -> None:
        self._hb_interval_s = interval_s
        self._heartbeat.update_interval(interval_s)
        if interval_s > 0 and self._heartbeat._thread is None:
            self._heartbeat.start(interval_s)
        elif interval_s == 0 and self._heartbeat._thread is not None:
            self._heartbeat.stop()

    # ------------------------------------------------------------------
    # Status publishing
    # ------------------------------------------------------------------

    def _publish_status(self, state: str) -> None:
        if not self._client:
            return
        connected = self._connected_since_ts or _utc_iso()
        uptime_s = 0.0
        if self._connected_ts is not None:
            uptime_s = max(0.0, time.time() - self._connected_ts)
        payload = StatusPayload(state=state, connected_since_ts=connected, uptime_s=uptime_s)
        self._client.publish(
            self.topics.status(),
            payload=payload.to_json(),
            qos=1,
            retain=True,
        )

    # ------------------------------------------------------------------
    # Paho callbacks
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        connect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code != 0:
            logger.error("MQTT connect failed: %s", reason_code)
            return

        logger.info("Connected to MQTT broker as %s", self.username)
        if self._connected_since_ts is None:
            self._connected_ts = time.time()
            self._connected_since_ts = _utc_iso()

        for topic in list(self._handlers.keys()):
            client.subscribe(topic, qos=1)
            logger.info("Subscribed: %s", topic)

        if not self._ctx:
            self._publish_status("online")
            return

        try:
            from lucid_agent_core.core.snapshots import (
                build_metadata, build_status, build_cfg,
                build_cfg_logging, build_cfg_telemetry,
            )

            ctx = self._ctx
            metadata = build_metadata(self.version)
            ctx.publish(self.topics.metadata(), metadata, retain=True, qos=1)

            status = build_status("online", self._connected_since_ts, 0)
            ctx.publish(self.topics.status(), status, retain=True, qos=1)

            cfg = ctx.config_store.get_cached()
            ctx.publish(self.topics.cfg(), build_cfg(cfg), retain=True, qos=1)
            ctx.publish(self.topics.cfg_logging(), build_cfg_logging(cfg), retain=True, qos=1)
            ctx.publish(self.topics.cfg_telemetry(), build_cfg_telemetry(cfg), retain=True, qos=1)

            logger.info("Published all retained snapshots on connect")
        except Exception as exc:
            logger.exception("Failed to publish retained snapshots: %s", exc)

        if self._hb_interval_s > 0:
            self._heartbeat.start(self._hb_interval_s)

        self._telemetry.start()

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: Any,
        reason_code: Any,
        properties: Any,
    ) -> None:
        if reason_code != 0:
            logger.warning("Unexpected disconnect: %s", reason_code)
        self._heartbeat.stop()
        self._telemetry.stop()

    def _on_message(self, client: mqtt.Client, userdata: Any, msg: mqtt.MQTTMessage) -> None:
        logger.debug("Message received: topic=%s payload_len=%d", msg.topic, len(msg.payload))
        handler = self._handlers.get(msg.topic)
        if not handler:
            logger.warning("Unhandled topic: %s", msg.topic)
            return
        try:
            payload_str = msg.payload.decode("utf-8")
        except UnicodeDecodeError as exc:
            logger.error("Payload decode failed topic=%s err=%s", msg.topic, exc)
            return

        if not self._inflight_sem.acquire(blocking=False):
            logger.warning(
                "Command rate limit reached (%d in-flight); dropping %s",
                self._inflight_limit,
                msg.topic,
            )
            return

        def _run() -> None:
            try:
                handler(payload_str)
            finally:
                self._inflight_sem.release()

        self._executor.submit(_run)

    # ------------------------------------------------------------------
    # Connection management
    # ------------------------------------------------------------------

    def connect(self) -> bool:
        try:
            if self._connected_since_ts is None:
                self._connected_since_ts = _utc_iso()
                self._connected_ts = time.time()

            client = mqtt.Client(
                mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id, protocol=mqtt.MQTTv311
            )
            client.username_pw_set(self.username, self.password)

            lwt_payload = {"state": "offline", "agent_id": self.username}
            client.will_set(
                self.topics.status(),
                payload=json.dumps(lwt_payload),
                qos=1,
                retain=True,
            )

            client.on_connect = self._on_connect
            client.on_disconnect = self._on_disconnect
            client.on_message = self._on_message

            client.connect(self.host, self.port, keepalive=self.keepalive)
            client.loop_start()

            self._client = client
            return True
        except Exception:
            logger.exception("Failed to connect to MQTT broker")
            return False

    def disconnect(self) -> None:
        if not self._client:
            return
        try:
            self._heartbeat.stop()
            self._telemetry.stop()
            self._publish_status("offline")
            self._client.loop_stop()
            self._client.disconnect()
        finally:
            self._client = None
            self._executor.shutdown(wait=False, cancel_futures=True)

    def is_connected(self) -> bool:
        return bool(self._client and self._client.is_connected())

    def publish(self, topic: str, payload: Any, *, qos: int = 0, retain: bool = False) -> Any:
        if not self._client:
            raise RuntimeError("MQTT client not connected")
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        return self._client.publish(topic, payload=payload, qos=qos, retain=retain)
