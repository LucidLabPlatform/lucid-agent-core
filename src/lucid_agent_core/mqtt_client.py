"""
MQTT client for LUCID Agent Core — unified v1.0.0 contract.

Connect, subscribe to agent cmd/ping, cmd/restart, cmd/refresh and component cmd topics,
publish retained metadata, status, state, cfg, cfg/telemetry at startup.
"""

from __future__ import annotations

import json
import logging
import threading
import time
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
    connected_since_ts: str
    uptime_s: float

    def to_json(self) -> str:
        return json.dumps({
            "state": self.state,
            "connected_since_ts": self.connected_since_ts,
            "uptime_s": self.uptime_s,
        })


class AgentMQTTClient:
    """
    MQTT client for agent: unified topics, no core/ nesting.
    Context must be set before connect(). After connect, call add_component_handlers(components)
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
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="mqtt-cmd"
        )

        self._ctx: Optional[Any] = None
        self._handlers: dict[str, Callable[[str], None]] = {}
        self._components: list[Any] = []
        self._components_lock = threading.Lock()
        self._connected_since_ts: Optional[str] = None
        self._connected_ts: Optional[float] = None

        self._hb_thread: Optional[threading.Thread] = None
        self._hb_stop_event = threading.Event()
        self._hb_interval_lock = threading.Lock()
        self._hb_interval_s = heartbeat_interval_s

    def set_context(self, ctx: Any) -> None:
        """Set command context and build agent command handlers. Call before connect()."""
        self._ctx = ctx
        self._build_handlers()
        logger.info("Context set, handlers built")

    def _build_handlers(self) -> None:
        if not self._ctx:
            self._handlers = {}
            return

        from lucid_agent_core.core.handlers import (
            on_ping,
            on_restart,
            on_refresh,
            on_cfg_set,
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
            self.topics.cmd_components_install(): lambda p: on_components_install(ctx, p),
            self.topics.cmd_components_uninstall(): lambda p: on_components_uninstall(ctx, p),
            self.topics.cmd_components_enable(): lambda p: on_components_enable(ctx, p),
            self.topics.cmd_components_disable(): lambda p: on_components_disable(ctx, p),
            self.topics.cmd_components_upgrade(): lambda p: on_components_upgrade(ctx, p),
            self.topics.cmd_core_upgrade(): lambda p: on_core_upgrade(ctx, p),
        }
        logger.debug("Built %d agent command handlers", len(self._handlers))

    def add_component_handlers(self, components: list[Any], registry: dict[str, dict]) -> None:
        """
        Subscribe to each component's cmd/reset, cmd/ping, cmd/cfg/set, and cfg/telemetry topics.
        Call after connect() and load_components().
        Enforces enabled gating: only subscribe if component is enabled in registry.
        """
        if not self._client or not self._client.is_connected():
            logger.warning("add_component_handlers called but client not connected")
            return

        with self._components_lock:
            self._components = list(components)

        for comp in components:
            cid = getattr(comp, "component_id", None)
            if not cid:
                continue
            
            # Enforce enabled gating
            if cid in registry and registry[cid].get("enabled") is False:
                logger.info("Skipping cmd subscriptions for disabled component: %s", cid)
                continue
            
            cmd_actions = [
                ("reset", "on_cmd_reset", self.topics.component_cmd_reset),
                ("ping", "on_cmd_ping", self.topics.component_cmd_ping),
            ]
            for action, method_name, topic_fn in cmd_actions:
                method = getattr(comp, method_name, None)
                if not callable(method):
                    continue
                topic = topic_fn(cid)
                self._handlers[topic] = lambda p, m=method: m(p)
                self._client.subscribe(topic, qos=1)
                logger.info("Subscribed: %s", topic)

            # cmd/cfg/set → Component.on_cmd_cfg_set(...)
            on_cfg_set = getattr(comp, "on_cmd_cfg_set", None)
            if callable(on_cfg_set):
                cfg_set_topic = self.topics.component_cmd_cfg_set(cid)
                self._handlers[cfg_set_topic] = lambda p, m=on_cfg_set: m(p)
                self._client.subscribe(cfg_set_topic, qos=1)
                logger.info("Subscribed: %s", cfg_set_topic)

            # Telemetry config: cfg/telemetry → Component.set_telemetry_config(...) (legacy; prefer cmd/cfg/set)
            set_cfg = getattr(comp, "set_telemetry_config", None)
            if callable(set_cfg):
                cfg_topic = f"{self.topics.component_base(cid)}/cfg/telemetry"

                def _handle_cfg_telemetry(payload_str: str, setter=set_cfg, topic=cfg_topic) -> None:
                    try:
                        cfg = json.loads(payload_str) if payload_str else {}
                        if not isinstance(cfg, dict):
                            logger.warning("Ignoring non-object cfg/telemetry payload on %s", topic)
                            return
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode cfg/telemetry payload on %s", topic)
                        return
                    try:
                        setter(cfg)
                        logger.info("Applied telemetry config for component %s from %s", cid, topic)
                    except Exception as exc:
                        logger.exception("Failed to apply telemetry config for component %s: %s", cid, exc)

                self._handlers[cfg_topic] = _handle_cfg_telemetry
                self._client.subscribe(cfg_topic, qos=1)
                logger.info("Subscribed: %s", cfg_topic)

    def get_component(self, component_id: str) -> Optional[Any]:
        """Get a component by ID. Returns None if not found."""
        with self._components_lock:
            for comp in self._components:
                cid = getattr(comp, "component_id", None)
                if cid == component_id:
                    return comp
        return None

    def stop_component(self, component_id: str) -> bool:
        """
        Stop a running component by ID. Returns True if stopped, False if not found.
        Also unsubscribes from component command topics.
        """
        comp = self.get_component(component_id)
        if comp is None:
            return False
        
        try:
            comp.stop()
            logger.info("Stopped component: %s", component_id)
        except Exception as exc:
            logger.exception("Failed to stop component %s: %s", component_id, exc)
            return False

        # Unsubscribe from component command topics
        if self._client and self._client.is_connected():
            topics_to_unsub = [
                self.topics.component_cmd_reset(component_id),
                self.topics.component_cmd_ping(component_id),
                self.topics.component_cmd_cfg_set(component_id),
                f"{self.topics.component_base(component_id)}/cfg/telemetry",
            ]
            for topic in topics_to_unsub:
                if topic in self._handlers:
                    try:
                        self._client.unsubscribe(topic)
                        del self._handlers[topic]
                        logger.info("Unsubscribed: %s", topic)
                    except Exception as exc:
                        logger.warning("Failed to unsubscribe %s: %s", topic, exc)

        return True

    def start_component(self, component_id: str, registry: dict[str, dict]) -> bool:
        """
        Start a component by ID. Component must be in registry and enabled.
        Also subscribes to component command topics.
        Returns True if started, False if not found or disabled.
        """
        from lucid_agent_core.components.loader import load_registry
        from lucid_agent_core.components.registry import load_registry as _load_registry
        
        reg = registry if registry else _load_registry()
        if component_id not in reg:
            return False
        
        meta = reg[component_id]
        if meta.get("enabled") is False:
            return False

        # Check if already loaded
        comp = self.get_component(component_id)
        if comp is not None:
            # Already loaded, check if running
            from lucid_component_base import ComponentStatus
            if hasattr(comp, "state") and comp.state.status == ComponentStatus.RUNNING:
                logger.info("Component %s already running", component_id)
                # Still resubscribe in case subscriptions were removed
                self._subscribe_component_topics(comp, component_id)
                # Republish retained topics (metadata, status, state, cfg, cfg/telemetry)
                # to ensure subscribers get fresh data after enable
                if hasattr(comp, "_publish_all_retained"):
                    try:
                        comp._publish_all_retained()
                        logger.info("Republished retained topics for component: %s", component_id)
                    except Exception as exc:
                        logger.warning("Failed to republish retained topics for %s: %s", component_id, exc)
                return True
            # Try to start it
            try:
                comp.start()
                logger.info("Started component: %s", component_id)
                # Subscribe to component topics
                self._subscribe_component_topics(comp, component_id)
                return True
            except Exception as exc:
                logger.exception("Failed to start component %s: %s", component_id, exc)
                return False

        # Component not loaded - would need to load it, but that's complex
        # For now, return False and require restart
        logger.warning("Component %s not loaded; restart agent to load disabled components", component_id)
        return False

    def _subscribe_component_topics(self, comp: Any, component_id: str) -> None:
        """Subscribe to a single component's command topics. Internal helper."""
        if not self._client or not self._client.is_connected():
            return
        
        cmd_actions = [
            ("reset", "on_cmd_reset", self.topics.component_cmd_reset),
            ("ping", "on_cmd_ping", self.topics.component_cmd_ping),
        ]
        for action, method_name, topic_fn in cmd_actions:
            method = getattr(comp, method_name, None)
            if not callable(method):
                continue
            topic = topic_fn(component_id)
            if topic not in self._handlers:
                self._handlers[topic] = lambda p, m=method: m(p)
                self._client.subscribe(topic, qos=1)
                logger.info("Subscribed: %s", topic)

        # cmd/cfg/set → Component.on_cmd_cfg_set(...)
        on_cfg_set = getattr(comp, "on_cmd_cfg_set", None)
        if callable(on_cfg_set):
            cfg_set_topic = self.topics.component_cmd_cfg_set(component_id)
            if cfg_set_topic not in self._handlers:
                self._handlers[cfg_set_topic] = lambda p, m=on_cfg_set: m(p)
                self._client.subscribe(cfg_set_topic, qos=1)
                logger.info("Subscribed: %s", cfg_set_topic)

        # Telemetry config: cfg/telemetry → Component.set_telemetry_config(...)
        set_cfg = getattr(comp, "set_telemetry_config", None)
        if callable(set_cfg):
            cfg_topic = f"{self.topics.component_base(component_id)}/cfg/telemetry"
            if cfg_topic not in self._handlers:
                import json
                def _handle_cfg_telemetry(payload_str: str, setter=set_cfg, topic=cfg_topic) -> None:
                    try:
                        cfg = json.loads(payload_str) if payload_str else {}
                        if not isinstance(cfg, dict):
                            logger.warning("Ignoring non-object cfg/telemetry payload on %s", topic)
                            return
                    except json.JSONDecodeError:
                        logger.warning("Failed to decode cfg/telemetry payload on %s", topic)
                        return
                    try:
                        setter(cfg)
                        logger.info("Applied telemetry config for component %s from %s", component_id, topic)
                    except Exception as exc:
                        logger.exception("Failed to apply telemetry config for component %s: %s", component_id, exc)
                self._handlers[cfg_topic] = _handle_cfg_telemetry
                self._client.subscribe(cfg_topic, qos=1)
                logger.info("Subscribed: %s", cfg_topic)

    def publish_retained_state(self, components_list: list[dict[str, Any]]) -> None:
        """
        Publish retained state with current components list.
        Call after load_components() so state.components is accurate.
        """
        if not self._ctx or not self._client:
            return
        from lucid_agent_core.core.snapshots import build_state
        state = build_state(components_list)
        self._ctx.publish(self.topics.state(), state, retain=True, qos=1)
        logger.info("Published retained state with %d components", len(components_list))

    def publish_retained_refresh(self, components_list: list[dict[str, Any]]) -> None:
        """
        Republish all retained snapshots that are not always updated: metadata, status,
        state, cfg, cfg/telemetry. Use after cmd/refresh to refresh topics without restart.
        """
        if not self._ctx or not self._client:
            return
        from lucid_agent_core.core.snapshots import (
            build_metadata,
            build_status,
            build_state,
            build_cfg_telemetry,
        )
        ctx = self._ctx
        metadata = build_metadata(ctx.agent_id, self.version)
        ctx.publish(self.topics.metadata(), metadata, retain=True, qos=1)
        uptime_s = 0.0
        if self._connected_ts is not None:
            uptime_s = max(0.0, time.time() - self._connected_ts)
        status = build_status(
            "online",
            self._connected_since_ts or _utc_iso(),
            uptime_s,
        )
        ctx.publish(self.topics.status(), status, retain=True, qos=1)
        state = build_state(components_list)
        ctx.publish(self.topics.state(), state, retain=True, qos=1)
        cfg = ctx.config_store.get_cached()
        ctx.publish(self.topics.cfg(), cfg, retain=True, qos=1)
        telemetry_cfg = cfg.get("telemetry") if isinstance(cfg.get("telemetry"), dict) else {}
        if not telemetry_cfg:
            telemetry_cfg = {"enabled": False, "metrics": {}, "interval_s": 2, "change_threshold_percent": 2.0}
        cfg_telem = build_cfg_telemetry(telemetry_cfg)
        ctx.publish(self.topics.cfg_telemetry(), cfg_telem, retain=True, qos=1)
        logger.info("Published retained refresh (metadata, status, state, cfg, cfg/telemetry)")

    def set_heartbeat_interval(self, interval_s: int) -> None:
        with self._hb_interval_lock:
            self._hb_interval_s = interval_s
        if interval_s > 0 and not self._hb_thread:
            self._start_heartbeat()
        elif interval_s == 0 and self._hb_thread:
            self._stop_heartbeat()

    def _start_heartbeat(self) -> None:
        if self._hb_thread:
            return
        self._hb_stop_event.clear()
        self._hb_thread = threading.Thread(
            target=self._heartbeat_loop,
            daemon=True,
            name="mqtt-heartbeat",
        )
        self._hb_thread.start()

    def _stop_heartbeat(self) -> None:
        if not self._hb_thread:
            return
        self._hb_stop_event.set()
        self._hb_thread.join(timeout=2.0)
        self._hb_thread = None

    def _heartbeat_loop(self) -> None:
        while not self._hb_stop_event.is_set():
            with self._hb_interval_lock:
                interval = self._hb_interval_s
            if interval <= 0:
                break
            if self._hb_stop_event.wait(timeout=interval):
                break
            if self._client and self._client.is_connected() and self._connected_ts is not None:
                try:
                    uptime_s = max(0.0, time.time() - self._connected_ts)
                    payload = StatusPayload(
                        state="online",
                        connected_since_ts=self._connected_since_ts or _utc_iso(),
                        uptime_s=uptime_s,
                    )
                    self._client.publish(
                        self.topics.status(),
                        payload=payload.to_json(),
                        qos=1,
                        retain=True,
                    )
                except Exception as exc:
                    logger.error("Heartbeat publish failed: %s", exc)

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

    def _on_connect(self, client: mqtt.Client, userdata: Any, flags: dict, rc: int) -> None:
        if rc != 0:
            logger.error("MQTT connect failed rc=%s", rc)
            return

        logger.info("Connected to MQTT broker as %s", self.username)
        # Only set connected_since_ts on first connect (maintain stability)
        if self._connected_since_ts is None:
            self._connected_ts = time.time()
            self._connected_since_ts = _utc_iso()
        # Else keep existing values (reconnect scenario)

        # Iterate over a copy to avoid RuntimeError if handlers are added concurrently
        for topic in list(self._handlers.keys()):
            client.subscribe(topic, qos=1)
            logger.info("Subscribed: %s", topic)

        if not self._ctx:
            self._publish_status("online")
            return

        try:
            from lucid_agent_core.core.snapshots import (
                build_metadata,
                build_status,
                build_cfg_telemetry,
            )

            ctx = self._ctx

            metadata = build_metadata(ctx.agent_id, self.version)
            ctx.publish(self.topics.metadata(), metadata, retain=True, qos=1)

            status = build_status(
                "online",
                self._connected_since_ts,
                0,
            )
            ctx.publish(self.topics.status(), status, retain=True, qos=1)

            # State will be published by publish_retained_state() after components are loaded
            # This avoids publishing empty state that gets overwritten immediately

            cfg = ctx.config_store.get_cached()
            ctx.publish(self.topics.cfg(), cfg, retain=True, qos=1)

            telemetry_cfg = cfg.get("telemetry") if isinstance(cfg.get("telemetry"), dict) else {}
            if not telemetry_cfg:
                telemetry_cfg = {"enabled": False, "metrics": {}, "interval_s": 2, "change_threshold_percent": 2.0}
            cfg_telem = build_cfg_telemetry(telemetry_cfg)
            ctx.publish(self.topics.cfg_telemetry(), cfg_telem, retain=True, qos=1)

            logger.info("Published all retained snapshots on connect")
        except Exception as exc:
            logger.exception("Failed to publish retained snapshots: %s", exc)

        with self._hb_interval_lock:
            interval = self._hb_interval_s
        if interval > 0:
            self._start_heartbeat()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc != 0:
            logger.warning("Unexpected disconnect rc=%s", rc)
        self._stop_heartbeat()

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
        self._executor.submit(handler, payload_str)

    def connect(self) -> bool:
        try:
            # Initialize connected_since_ts for LWT
            if self._connected_since_ts is None:
                self._connected_since_ts = _utc_iso()
                self._connected_ts = time.time()
            
            client = mqtt.Client(client_id=self.client_id, protocol=mqtt.MQTTv311)
            client.username_pw_set(self.username, self.password)

            # LWT must match exact status schema with last known values
            uptime_s = 0.0
            if self._connected_ts is not None:
                uptime_s = max(0.0, time.time() - self._connected_ts)
            
            payload = StatusPayload(
                state="offline",
                connected_since_ts=self._connected_since_ts,
                uptime_s=uptime_s,
            )
            client.will_set(
                self.topics.status(),
                payload=payload.to_json(),
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
            self._stop_heartbeat()
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
