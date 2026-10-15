#!/usr/bin/env python3
"""Sentinel-Edge: Multi-Channel Action Notifier & Hardware Actuation

Dispatches verified threats to:
1. Telegram Bot API webhook (with cooldown throttling)
2. ESP32 UART Hardware (FreeRTOS siren, relays, interlocks, LEDs)
3. Local sound & console logs
"""

import json
import logging
import time
from typing import Any, Dict, Optional

log = logging.getLogger("sentinel.notifier")


class MultiChannelNotifier:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        dispatch_cfg = self.config.get("dispatch", {})
        
        self.telegram_cfg = dispatch_cfg.get("telegram", {})
        self.esp32_cfg = dispatch_cfg.get("esp32_uart", {})
        self.local_cfg = dispatch_cfg.get("local_alerts", {})

        self.last_telegram_time = 0.0
        self.ser = None

        if self.esp32_cfg.get("enabled", False):
            self._init_serial()

    def _init_serial(self):
        try:
            import serial
            port = self.esp32_cfg.get("port", "COM3")
            baud = self.esp32_cfg.get("baudrate", 115200)
            self.ser = serial.Serial(port, baud, timeout=0.1)
            log.info("ESP32 FirmGen hardware UART connected on %s @ %d bps", port, baud)
        except Exception as e:
            log.warning("ESP32 UART not active (%s). Hardware closed-loop will run in software simulation mode.", e)
            self.ser = None

    def dispatch(self, alert: Dict[str, Any]):
        """Dispatch alert to all active physical and remote channels."""
        severity = alert.get("severity", "WARNING")
        rule_id = alert.get("rule_id", "threat")
        msg = alert.get("message", "")
        action = alert.get("suggested_action", "")
        level = alert.get("actuator_level", 2)

        # 1. Local Console Output
        if self.local_cfg.get("console_highlight", True):
            icon = "🚨" if severity == "CRITICAL" else "⚠️"
            log.warning(
                "%s [%s] ALERT DISPATCHED -> %s | Action: %s",
                icon, severity, msg, action
            )

        # 2. ESP32 FirmGen Closed-Loop Hardware Command
        self._dispatch_esp32(level, rule_id)

        # 3. Telegram Bot Webhook
        self._dispatch_telegram(alert)

    def _dispatch_esp32(self, level: int, tag: str):
        cmd = f"ALERT {level} {tag}\n"
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd.encode("ascii"))
                log.info("ESP32 UART Command sent: %s", cmd.strip())
            except Exception as e:
                log.error("Failed to write to ESP32: %s", e)
        else:
            # Simulated hardware feedback
            log.info("[SIMULATED ESP32 ACTUATOR] Command: %s (Relay/LED Tripped)", cmd.strip())

    def clear_esp32(self, tag: str = "all_clear"):
        cmd = f"CLEAR {tag}\n"
        if self.ser and self.ser.is_open:
            try:
                self.ser.write(cmd.encode("ascii"))
            except Exception:
                pass
        else:
            log.info("[SIMULATED ESP32 ACTUATOR] Command: %s", cmd.strip())

    def _dispatch_telegram(self, alert: Dict[str, Any]):
        if not self.telegram_cfg.get("enabled", False):
            return

        now = time.time()
        cooldown = self.telegram_cfg.get("cooldown_seconds", 30)
        if (now - self.last_telegram_time) < cooldown:
            return

        token = self.telegram_cfg.get("bot_token")
        chat_id = self.telegram_cfg.get("chat_id")
        if not token or not chat_id:
            return

        text = (
            f"🚨 *SENTINEL-EDGE ALERT: {alert.get('severity')}*\n\n"
            f"*Rule:* `{alert.get('rule_name')}`\n"
            f"*Camera:* `{alert.get('camera_id')}`\n"
            f"*Message:* {alert.get('message')}\n\n"
            f"👉 *SUGGESTED ACTION:* {alert.get('suggested_action')}\n\n"
            f"⏱️ Timestamp: `{alert.get('timestamp')}`\n"
            f"🔒 Verification Gate: *PASSED (Grounded Edge Proof)*"
        )

        try:
            import requests
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
            requests.post(url, json=payload, timeout=3.0)
            self.last_telegram_time = now
            log.info("Telegram alert dispatched successfully.")
        except Exception as e:
            log.error("Telegram dispatch failed: %s", e)
