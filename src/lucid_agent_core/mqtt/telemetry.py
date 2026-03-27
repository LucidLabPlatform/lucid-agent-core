"""
Telemetry loop — publishes per-metric telemetry streams based on config.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class TelemetryLoop:
    """
    Publishes core telemetry streams (cpu_percent, memory_percent, disk_percent) on a
    configurable per-metric interval/threshold, driven by the agent's config store.

    Args:
        paho_publish:   The paho client's publish method (topic, payload, *, qos, retain).
        get_ctx:        Callable returning the current CoreCommandContext, or None.
        is_connected:   Callable returning True if the MQTT client is connected.
        topics:         TopicSchema for building metric topic strings.
    """

    def __init__(
        self,
        paho_publish: Callable[..., Any],
        get_ctx: Callable[[], Optional[Any]],
        is_connected: Callable[[], bool],
        topics: Any,
    ) -> None:
        self._paho_publish = paho_publish
        self._get_ctx = get_ctx
        self._is_connected = is_connected
        self._topics = topics
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last: dict[str, tuple[Any, float]] = {}  # metric -> (value, last_publish_ts)

    def start(self) -> None:
        """Start the telemetry thread if not already running."""
        if self._thread:
            return

        ctx = self._get_ctx()
        if ctx is not None:
            from lucid_agent_core.core.snapshots import build_cfg_telemetry

            raw_cfg = ctx.config_store.get_cached()
            metrics_cfg = build_cfg_telemetry(raw_cfg)
            enabled = [
                name for name, mcfg in metrics_cfg.items()
                if isinstance(mcfg, dict) and mcfg.get("enabled", False)
            ]
            logger.info(
                "Starting telemetry thread. Enabled metrics: %s (total: %d)",
                enabled or "none",
                len(metrics_cfg),
            )

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._loop, name="LucidCoreTelemetry", daemon=True
        )
        self._thread.start()
        logger.info("Started core telemetry thread")

    def stop(self) -> None:
        """Stop the telemetry thread and wait for it to exit."""
        if not self._thread:
            return
        self._stop_event.set()
        self._thread.join(timeout=2.0)
        if self._thread.is_alive():
            logger.warning("Telemetry thread did not stop within timeout")
        self._thread = None
        logger.info("Stopped core telemetry thread")

    def _should_publish(self, metric: str, value: Any, metric_cfg: dict[str, Any]) -> bool:
        """Return True if this metric value should be published given its config."""
        if not metric_cfg.get("enabled", False):
            return False

        interval_s = max(1, metric_cfg.get("interval_s", 2))
        threshold = max(0.0, metric_cfg.get("change_threshold_percent", 2.0))
        now = time.time()
        last = self._last.get(metric)

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

    def _loop(self) -> None:
        while not self._stop_event.is_set():
            ctx = self._get_ctx()
            if not ctx or not self._is_connected():
                if self._stop_event.wait(timeout=1.0):
                    break
                continue

            try:
                from lucid_agent_core.core.snapshots import (
                    build_cfg_telemetry,
                    _system_cpu_percent,
                    _system_memory_percent,
                    _system_disk_percent,
                )

                raw_cfg = ctx.config_store.get_cached()
                metrics_cfg = build_cfg_telemetry(raw_cfg)

                if not metrics_cfg:
                    logger.debug("Telemetry loop: no metrics config, waiting...")
                    if self._stop_event.wait(timeout=2.0):
                        break
                    continue

                state_values = {
                    "cpu_percent": _system_cpu_percent(),
                    "memory_percent": _system_memory_percent(),
                    "disk_percent": _system_disk_percent(),
                }

                published_count = 0
                for metric_name, metric_cfg in metrics_cfg.items():
                    if not isinstance(metric_cfg, dict):
                        logger.debug("Telemetry loop: skipping %s (not a dict)", metric_name)
                        continue
                    if metric_name not in state_values:
                        logger.debug("Telemetry loop: skipping %s (not tracked)", metric_name)
                        continue

                    value = state_values[metric_name]
                    if self._should_publish(metric_name, value, metric_cfg):
                        try:
                            topic = self._topics.telemetry(metric_name)
                            payload = json.dumps({"value": value})
                            self._paho_publish(topic, payload, qos=0, retain=False)
                            self._last[metric_name] = (value, time.time())
                            published_count += 1
                            logger.info("Published telemetry: %s = %.2f", metric_name, value)
                        except Exception as exc:
                            logger.warning("Failed to publish telemetry %s: %s", metric_name, exc)
                    else:
                        logger.debug(
                            "Telemetry loop: skipping %s (gated, enabled=%s)",
                            metric_name,
                            metric_cfg.get("enabled", False),
                        )

                if published_count == 0:
                    logger.debug("Telemetry loop: no metrics published this cycle")

                if self._stop_event.wait(timeout=1.0):
                    break

            except Exception as exc:
                logger.exception("Telemetry loop error: %s", exc)
                if self._stop_event.wait(timeout=2.0):
                    break
