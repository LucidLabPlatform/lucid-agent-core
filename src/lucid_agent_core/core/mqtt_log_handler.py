"""
MQTT logging handler for core agent.

Publishes log messages to MQTT /logs topic with rate limiting to prevent flooding.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Rate limiting: max logs per time window
MAX_LOGS_PER_WINDOW = 10
TIME_WINDOW_S = 1.0  # 1 second window


class MQTTLogHandler(logging.Handler):
    """
    Logging handler that publishes log messages to MQTT /logs topic.
    
    Implements rate limiting to prevent flooding: max MAX_LOGS_PER_WINDOW logs per TIME_WINDOW_S seconds.
    """
    
    def __init__(self, mqtt_client: Any, topic: str) -> None:
        """
        Initialize MQTT log handler.
        
        Args:
            mqtt_client: MQTT client instance with publish() method
            topic: MQTT topic to publish logs to
        """
        super().__init__()
        self.mqtt_client = mqtt_client
        self.topic = topic
        
        # Rate limiting state
        self._lock = threading.Lock()
        self._log_timestamps: list[float] = []
        self._dropped_count = 0
        self._last_warning_ts = 0.0
        
    def emit(self, record: logging.LogRecord) -> None:
        """Emit a log record to MQTT if rate limit allows and logs_enabled is True."""
        try:
            # Check if logs are enabled
            if self.mqtt_client and hasattr(self.mqtt_client, "_ctx") and self.mqtt_client._ctx:
                ctx = self.mqtt_client._ctx
                if hasattr(ctx, "config_store"):
                    cfg = ctx.config_store.get_cached()
                    if not cfg.get("logs_enabled", False):
                        return  # Logs disabled, skip publishing
            
            # Check rate limit
            if not self._should_publish():
                self._dropped_count += 1
                # Warn about dropped logs occasionally (every 10 seconds max)
                now = time.time()
                if now - self._last_warning_ts >= 10.0:
                    logger.warning(
                        "MQTT log handler: dropped %d log messages due to rate limiting",
                        self._dropped_count
                    )
                    self._dropped_count = 0
                    self._last_warning_ts = now
                return
            
            # Map Python log levels to MQTT log levels
            level_map = {
                logging.DEBUG: "debug",
                logging.INFO: "info",
                logging.WARNING: "warning",
                logging.ERROR: "error",
                logging.CRITICAL: "error",
            }
            mqtt_level = level_map.get(record.levelno, "info")
            
            # Format message
            message = self.format(record)
            
            # Publish to MQTT
            payload = {
                "level": mqtt_level,
                "message": message,
            }
            
            # Only publish if client is connected
            if self.mqtt_client and hasattr(self.mqtt_client, "_client"):
                client = self.mqtt_client._client
                if client and client.is_connected():
                    try:
                        self.mqtt_client.publish(
                            self.topic,
                            json.dumps(payload),
                            qos=0,
                            retain=False,
                        )
                    except Exception as exc:
                        # Don't log errors from the log handler itself to avoid recursion
                        pass
                        
        except Exception:
            # Silently ignore errors to prevent recursion
            pass
    
    def _should_publish(self) -> bool:
        """
        Check if we should publish this log based on rate limiting.
        Returns True if under rate limit, False otherwise.
        """
        with self._lock:
            now = time.time()
            
            # Remove timestamps outside the time window
            cutoff = now - TIME_WINDOW_S
            self._log_timestamps = [ts for ts in self._log_timestamps if ts > cutoff]
            
            # Check if we're at the limit
            if len(self._log_timestamps) >= MAX_LOGS_PER_WINDOW:
                return False
            
            # Add this timestamp
            self._log_timestamps.append(now)
            return True
