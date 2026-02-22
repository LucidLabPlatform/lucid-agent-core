"""
MQTT client for LUCID Agent Core — unified v1.0.0 contract.

Connect, subscribe to agent cmd/ping, cmd/restart, cmd/refresh and component cmd topics,
publish retained metadata, status, state, cfg at startup.
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
        
        # Telemetry tracking
        self._telemetry_thread: Optional[threading.Thread] = None
        self._telemetry_stop_event = threading.Event()
        self._telemetry_last: dict[str, tuple[Any, float]] = {}  # metric -> (value, last_publish_ts)

        # Per-component cmd topics (for unsubscribe on stop)
        self._component_cmd_topics: dict[str, set[str]] = {}

    def set_context(self, ctx: Any) -> None:
        """Set command context and build agent command handlers. Call before connect()."""
        self._ctx = ctx
        self._build_handlers()
        self._setup_mqtt_logging()
        logger.info("Context set, handlers built")
    
    def _setup_mqtt_logging(self) -> None:
        """Set up MQTT logging handler for core logs."""
        try:
            from lucid_agent_core.core.mqtt_log_handler import MQTTLogHandler
            
            # Only add handler if not already added
            root_logger = logging.getLogger()
            for handler in root_logger.handlers:
                if isinstance(handler, MQTTLogHandler) and handler.topic == self.topics.logs():
                    return  # Already added
            
            # Create and add handler
            handler = MQTTLogHandler(self, self.topics.logs())
            handler.setLevel(logging.DEBUG)  # Handler level, actual filtering done by logger level
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
        Subscribe to each component's cmd/reset, cmd/ping, cmd/cfg/set topics.
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
            
            caps = getattr(comp, "capabilities", None)
            cap_list = list(caps()) if callable(caps) else []
            topics_for_cid = self._component_cmd_topics.setdefault(cid, set())
            for action in cap_list:
                method_name = "on_cmd_" + action.replace("/", "_")
                method = getattr(comp, method_name, None)
                if not callable(method):
                    continue
                try:
                    topic = self.topics.component_cmd(cid, action)
                except Exception:
                    continue
                if topic in self._handlers:
                    continue
                self._handlers[topic] = lambda p, m=method: m(p)
                self._client.subscribe(topic, qos=1)
                topics_for_cid.add(topic)
                logger.info("Subscribed: %s", topic)

            on_cfg_set = getattr(comp, "on_cmd_cfg_set", None)
            if callable(on_cfg_set):
                cfg_set_topic = self.topics.component_cmd_cfg_set(cid)
                if cfg_set_topic not in self._handlers:
                    self._handlers[cfg_set_topic] = lambda p, m=on_cfg_set: m(p)
                    self._client.subscribe(cfg_set_topic, qos=1)
                    topics_for_cid.add(cfg_set_topic)
                    logger.info("Subscribed: %s", cfg_set_topic)

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
            # Republish all retained topics to ensure status and state are updated
            if hasattr(comp, "_publish_all_retained"):
                try:
                    comp._publish_all_retained()
                    logger.info("Republished retained topics for stopped component: %s", component_id)
                except Exception as exc:
                    logger.warning("Failed to republish retained topics for %s: %s", component_id, exc)
        except Exception as exc:
            logger.exception("Failed to stop component %s: %s", component_id, exc)
            return False

        if self._client and self._client.is_connected():
            topics_to_unsub = self._component_cmd_topics.pop(component_id, set())
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
            from lucid_component_base import ComponentStatus
            
            # Check current status
            current_status = None
            if hasattr(comp, "state") and hasattr(comp.state, "status"):
                current_status = comp.state.status
                logger.info("Component %s found, current status: %s", component_id, current_status.value)
            else:
                logger.warning("Component %s found but missing state attribute", component_id)
            
            # If already running, just resubscribe and republish
            if current_status == ComponentStatus.RUNNING:
                logger.info("Component %s already running, resubscribing and republishing", component_id)
                self._subscribe_component_topics(comp, component_id)
                # Republish retained topics (metadata, status, state, cfg)
                # to ensure subscribers get fresh data after enable
                if hasattr(comp, "_publish_all_retained"):
                    try:
                        comp._publish_all_retained()
                        logger.info("Republished retained topics for component: %s", component_id)
                    except Exception as exc:
                        logger.warning("Failed to republish retained topics for %s: %s", component_id, exc)
                return True
            
            # If stopped or failed, try to start it
            if current_status in (ComponentStatus.STOPPED, ComponentStatus.FAILED, None):
                logger.info("Component %s is %s, attempting to start", component_id, current_status.value if current_status else "unknown")
                try:
                    comp.start()
                    logger.info("Successfully started component: %s", component_id)
                    # Subscribe to component topics
                    self._subscribe_component_topics(comp, component_id)
                    # Republish all retained topics to ensure status and state are updated
                    if hasattr(comp, "_publish_all_retained"):
                        try:
                            comp._publish_all_retained()
                            logger.info("Republished retained topics for component: %s", component_id)
                        except Exception as exc:
                            logger.warning("Failed to republish retained topics for %s: %s", component_id, exc)
                    return True
                except Exception as exc:
                    logger.exception("Failed to start component %s: %s", component_id, exc)
                    return False
            
            # If in STARTING or STOPPING state, wait a bit and check again
            if current_status in (ComponentStatus.STARTING, ComponentStatus.STOPPING):
                logger.warning("Component %s is in transitional state %s, cannot start now", component_id, current_status.value)
                return False

        # Component not loaded - would need to load it, but that's complex
        # For now, return False and require restart
        logger.warning("Component %s not loaded; restart agent to load disabled components", component_id)
        return False

    def _subscribe_component_topics(self, comp: Any, component_id: str) -> None:
        """Subscribe to a single component's command topics from its capabilities."""
        if not self._client or not self._client.is_connected():
            return
        caps = getattr(comp, "capabilities", None)
        cap_list = list(caps()) if callable(caps) else []
        topics_for_cid = self._component_cmd_topics.setdefault(component_id, set())
        for action in cap_list:
            method_name = "on_cmd_" + action.replace("/", "_")
            method = getattr(comp, method_name, None)
            if not callable(method):
                continue
            try:
                topic = self.topics.component_cmd(component_id, action)
            except Exception:
                continue
            if topic in self._handlers:
                continue
            self._handlers[topic] = lambda p, m=method: m(p)
            self._client.subscribe(topic, qos=1)
            topics_for_cid.add(topic)
            logger.info("Subscribed: %s", topic)
        on_cfg_set = getattr(comp, "on_cmd_cfg_set", None)
        if callable(on_cfg_set):
            cfg_set_topic = self.topics.component_cmd_cfg_set(component_id)
            if cfg_set_topic not in self._handlers:
                self._handlers[cfg_set_topic] = lambda p, m=on_cfg_set: m(p)
                self._client.subscribe(cfg_set_topic, qos=1)
                topics_for_cid.add(cfg_set_topic)
                logger.info("Subscribed: %s", cfg_set_topic)

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
        state, cfg. Use after cmd/refresh to refresh topics without restart.
        """
        if not self._ctx or not self._client:
            return
        from lucid_agent_core.core.snapshots import (
            build_metadata,
            build_status,
            build_state,
            build_cfg,
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
        ctx.publish(self.topics.cfg(), build_cfg(cfg), retain=True, qos=1)
        logger.info("Published retained refresh (metadata, status, state, cfg)")

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

    def _should_publish_telemetry(self, metric: str, value: Any, metric_cfg: dict[str, Any]) -> bool:
        """
        Check if telemetry should be published for a metric based on its config.
        Returns True if enabled and (delta > threshold or interval exceeded).
        """
        if not metric_cfg.get("enabled", False):
            return False
        
        interval_s = max(1, metric_cfg.get("interval_s", 2))
        threshold = max(0.0, metric_cfg.get("change_threshold_percent", 2.0))
        now = time.time()
        last = self._telemetry_last.get(metric)
        
        if last is None:
            return True
        
        last_value, last_ts = last
        if now - last_ts >= interval_s:
            return True
        
        try:
            if isinstance(last_value, (int, float)) and isinstance(value, (int, float)):
                if last_value == 0:
                    return value != 0
                delta_pct = abs(value - last_value) / abs(last_value) * 100.0
                return delta_pct >= threshold
        except TypeError:
            pass
        return value != last_value

    def _telemetry_loop(self) -> None:
        """Publish core telemetry streams based on cfg.telemetry.metrics config."""
        while not self._telemetry_stop_event.is_set():
            if not self._ctx or not self._client or not self._client.is_connected():
                if self._telemetry_stop_event.wait(timeout=1.0):
                    break
                continue
            
            try:
                # Use build_cfg() to ensure defaults are applied
                from lucid_agent_core.core.snapshots import build_cfg
                raw_cfg = self._ctx.config_store.get_cached()
                cfg = build_cfg(raw_cfg)
                
                telemetry_cfg = cfg.get("telemetry", {})
                metrics_cfg = telemetry_cfg.get("metrics", {})
                
                if not metrics_cfg:
                    logger.debug("Telemetry loop: no metrics config found, waiting...")
                    if self._telemetry_stop_event.wait(timeout=2.0):
                        break
                    continue
                
                # Get current state values
                from lucid_agent_core.core.snapshots import (
                    _system_cpu_percent,
                    _system_memory_percent,
                    _system_disk_percent,
                )
                
                state_values = {
                    "cpu_percent": _system_cpu_percent(),
                    "memory_percent": _system_memory_percent(),
                    "disk_percent": _system_disk_percent(),
                }
                
                # Publish telemetry for each enabled metric
                published_count = 0
                for metric_name, metric_cfg in metrics_cfg.items():
                    if not isinstance(metric_cfg, dict):
                        logger.debug("Telemetry loop: skipping %s (not a dict)", metric_name)
                        continue
                    
                    if metric_name not in state_values:
                        logger.debug("Telemetry loop: skipping %s (not in state_values)", metric_name)
                        continue
                    
                    value = state_values[metric_name]
                    if self._should_publish_telemetry(metric_name, value, metric_cfg):
                        try:
                            topic = self.topics.telemetry(metric_name)
                            payload = json.dumps({"value": value})
                            self._client.publish(topic, payload, qos=0, retain=False)
                            self._telemetry_last[metric_name] = (value, time.time())
                            published_count += 1
                            logger.info("Published telemetry: %s = %.2f", metric_name, value)
                        except Exception as exc:
                            logger.warning("Failed to publish telemetry %s: %s", metric_name, exc)
                    else:
                        logger.debug("Telemetry loop: skipping %s (should_publish returned False, enabled=%s)", 
                                   metric_name, metric_cfg.get("enabled", False))
                
                if published_count == 0:
                    logger.debug("Telemetry loop: no metrics published this cycle")
                
                # Sleep for minimum interval (check configs more frequently)
                if self._telemetry_stop_event.wait(timeout=1.0):
                    break
                    
            except Exception as exc:
                logger.exception("Telemetry loop error: %s", exc)
                if self._telemetry_stop_event.wait(timeout=2.0):
                    break

    def _start_telemetry(self) -> None:
        """Start telemetry publishing thread if not already running."""
        if self._telemetry_thread:
            return
        
        # Log current telemetry config state
        if self._ctx:
            from lucid_agent_core.core.snapshots import build_cfg
            raw_cfg = self._ctx.config_store.get_cached()
            cfg = build_cfg(raw_cfg)
            telemetry_cfg = cfg.get("telemetry", {})
            metrics_cfg = telemetry_cfg.get("metrics", {})
            enabled_metrics = [name for name, mcfg in metrics_cfg.items() 
                             if isinstance(mcfg, dict) and mcfg.get("enabled", False)]
            logger.info("Starting telemetry thread. Enabled metrics: %s (total metrics: %d)", 
                       enabled_metrics if enabled_metrics else "none", len(metrics_cfg))
        
        self._telemetry_stop_event.clear()
        self._telemetry_thread = threading.Thread(
            target=self._telemetry_loop,
            name="LucidCoreTelemetry",
            daemon=True,
        )
        self._telemetry_thread.start()
        logger.info("Started core telemetry thread")

    def _stop_telemetry(self) -> None:
        """Stop telemetry publishing thread."""
        if not self._telemetry_thread:
            return
        self._telemetry_stop_event.set()
        self._telemetry_thread.join(timeout=2.0)
        if self._telemetry_thread.is_alive():
            logger.warning("Telemetry thread did not stop within timeout")
        self._telemetry_thread = None
        logger.info("Stopped core telemetry thread")

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
                build_cfg,
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
            ctx.publish(self.topics.cfg(), build_cfg(cfg), retain=True, qos=1)

            logger.info("Published all retained snapshots on connect")
        except Exception as exc:
            logger.exception("Failed to publish retained snapshots: %s", exc)

        with self._hb_interval_lock:
            interval = self._hb_interval_s
        if interval > 0:
            self._start_heartbeat()
        
        # Start telemetry thread
        self._start_telemetry()

    def _on_disconnect(self, client: mqtt.Client, userdata: Any, rc: int) -> None:
        if rc != 0:
            logger.warning("Unexpected disconnect rc=%s", rc)
        self._stop_heartbeat()
        self._stop_telemetry()

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

            # LWT is minimal: set once at connect; broker publishes on disconnect/crash.
            # Cannot contain live values (e.g. uptime at crash). Same topic as status.
            lwt_payload = {"state": "offline", "agent_id": self.username, "version": self.version}
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
            self._stop_heartbeat()
            self._stop_telemetry()
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
