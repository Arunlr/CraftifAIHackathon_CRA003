#!/usr/bin/env python3
"""Sentinel-Edge: Realistic Multi-Scenario CCTV Telemetry Simulator

Simulates real-time edge detections from PipeGen DeepStream YOLOv8s.
Emits both DeepStream Schema 4.0 over MQTT and standard JSONL over HTTP/stdout.

Scenarios Simulated:
1. Normal transit corridor flow (peaceful commuters, aspect ratio ~0.4)
2. Suspicious Unattended Bag (Track #14 backpack isolated > 8s from owner)
3. Medical Emergency / Person Down (Track #22 horizontal aspect ratio > 1.25)
4. Unusual Crowding / Surge (6+ persons converging inside Secure Perimeter Zone)
"""

import argparse
import json
import math
import sys
import time
from datetime import datetime, timezone
from typing import List, Dict, Any

# Frame dimensions
FRAME_W = 1280
FRAME_H = 720


def generate_normal_frame(frame_num: int, sim_time: float) -> List[Dict[str, Any]]:
    """Commuters moving across the corridor."""
    records = []
    ts = datetime.now(timezone.utc).isoformat()

    # Person 1 moving left to right
    x1 = 150 + int((frame_num * 5) % 900)
    y1 = 300 + int(math.sin(frame_num * 0.1) * 20)
    records.append({
        "camera_id": "cam_01",
        "timestamp": ts,
        "class_name": "person",
        "confidence": 0.91,
        "track_id": 1,
        "bounding_box": {"x": x1, "y": y1, "w": 85, "h": 210},
        "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
    })

    # Person 2 moving right to left
    x2 = 1000 - int((frame_num * 4) % 850)
    y2 = 260
    records.append({
        "camera_id": "cam_01",
        "timestamp": ts,
        "class_name": "person",
        "confidence": 0.88,
        "track_id": 2,
        "bounding_box": {"x": x2, "y": y2, "w": 80, "h": 200},
        "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
    })

    return records


def generate_unattended_bag_frame(frame_num: int, sim_time: float) -> List[Dict[str, Any]]:
    """Person 3 drops a backpack (Track #14) and walks away."""
    records = []
    ts = datetime.now(timezone.utc).isoformat()

    # Stationary isolated backpack
    records.append({
        "camera_id": "cam_01",
        "timestamp": ts,
        "class_name": "backpack",
        "confidence": 0.93,
        "track_id": 14,
        "bounding_box": {"x": 380, "y": 480, "w": 65, "h": 70},
        "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
    })

    # Owner walking away further and further
    x_owner = min(1150, 420 + int(sim_time * 50))
    records.append({
        "camera_id": "cam_01",
        "timestamp": ts,
        "class_name": "person",
        "confidence": 0.90,
        "track_id": 3,
        "bounding_box": {"x": x_owner, "y": 280, "w": 85, "h": 215},
        "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
    })

    return records


def generate_fall_emergency_frame(frame_num: int, sim_time: float) -> List[Dict[str, Any]]:
    """Person collapses: transitions from vertical (80x200) to horizontal (260x85)."""
    records = []
    ts = datetime.now(timezone.utc).isoformat()

    # Person 22 on the ground
    records.append({
        "camera_id": "cam_01",
        "timestamp": ts,
        "class_name": "person",
        "confidence": 0.94,
        "track_id": 22,
        "bounding_box": {"x": 480, "y": 500, "w": 250, "h": 85},  # w/h ratio = 2.94
        "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
    })

    # Bystander rushing
    records.append({
        "camera_id": "cam_01",
        "timestamp": ts,
        "class_name": "person",
        "confidence": 0.89,
        "track_id": 9,
        "bounding_box": {"x": 820, "y": 420, "w": 85, "h": 200},
        "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
    })

    return records


def generate_crowd_surge_frame(frame_num: int, sim_time: float) -> List[Dict[str, Any]]:
    """6 persons gathering inside Secure Perimeter Zone A (normalized x: 0.1-0.9, y: 0.15-0.85)."""
    records = []
    ts = datetime.now(timezone.utc).isoformat()

    positions = [
        (350, 300), (430, 320), (510, 290),
        (590, 330), (670, 310), (750, 340)
    ]
    for i, (bx, by) in enumerate(positions):
        records.append({
            "camera_id": "cam_01",
            "timestamp": ts,
            "class_name": "person",
            "confidence": 0.88 + (i * 0.01),
            "track_id": 100 + i,
            "bounding_box": {"x": bx, "y": by, "w": 80, "h": 190},
            "frame": {"width": FRAME_W, "height": FRAME_H, "number": frame_num}
        })

    return records


def format_deepstream_schema_4(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Format records to DeepStream Schema 4.0 objects array."""
    objects = []
    for r in records:
        tid = r["track_id"]
        bb = r["bounding_box"]
        left = float(bb["x"])
        top = float(bb["y"])
        right = left + float(bb["w"])
        bottom = top + float(bb["h"])
        cls = r["class_name"]
        objects.append(f"{tid}|{left:.1f}|{top:.1f}|{right:.1f}|{bottom:.1f}|{cls}")

    return {
        "version": "4.0",
        "id": str(records[0]["frame"]["number"] if records else 0),
        "@timestamp": records[0]["timestamp"] if records else datetime.now(timezone.utc).isoformat(),
        "sensorId": "cam_01",
        "objects": objects
    }


def main():
    parser = argparse.ArgumentParser(description="Sentinel-Edge CCTV Telemetry Simulator")
    parser.add_argument("--mode", choices=["http", "mqtt", "stdout"], default="http", help="Ingestion delivery mode")
    parser.add_argument("--url", default="http://localhost:8050/ingest", help="HTTP ingest URL")
    parser.add_argument("--broker", default="localhost", help="MQTT broker host")
    parser.add_argument("--port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--topic", default="pipegen/detections", help="MQTT topic")
    parser.add_argument("--fps", type=float, default=10.0, help="Simulation FPS (frame rate)")
    parser.add_argument("--duration", type=float, default=60.0, help="Total run duration in seconds")
    parser.add_argument("--scenario", choices=["all", "normal", "bag", "fall", "crowd"], default="all", help="Scenario to play")
    args = parser.parse_args()

    print(f"[*] Starting Sentinel-Edge Simulator (mode={args.mode}, fps={args.fps}, scenario={args.scenario})...")

    mqtt_client = None
    if args.mode == "mqtt":
        try:
            import paho.mqtt.client as mqtt
            mqtt_client = mqtt.Client(client_id="sentinel_simulator")
            mqtt_client.connect(args.broker, args.port, 60)
            print(f"[+] Connected to MQTT broker at {args.broker}:{args.port}")
        except Exception as e:
            print(f"[-] MQTT error: {e}. Falling back to HTTP mode.")
            args.mode = "http"

    start_time = time.time()
    frame_interval = 1.0 / max(1.0, args.fps)
    frame_num = 0

    try:
        while True:
            elapsed = time.time() - start_time
            if args.duration > 0 and elapsed > args.duration:
                break

            # Scenario timeline sequencing (cycles every 40s in 'all' mode)
            cycle_t = elapsed % 40.0
            if args.scenario == "bag" or (args.scenario == "all" and 5.0 <= cycle_t < 15.0):
                records = generate_unattended_bag_frame(frame_num, cycle_t - 5.0)
            elif args.scenario == "fall" or (args.scenario == "all" and 15.0 <= cycle_t < 25.0):
                records = generate_fall_emergency_frame(frame_num, cycle_t - 15.0)
            elif args.scenario == "crowd" or (args.scenario == "all" and 25.0 <= cycle_t < 35.0):
                records = generate_crowd_surge_frame(frame_num, cycle_t - 25.0)
            else:
                records = generate_normal_frame(frame_num, cycle_t)

            frame_num += 1

            if args.mode == "http":
                try:
                    import requests
                    requests.post(args.url, json=records, timeout=0.5)
                except Exception:
                    pass
            elif args.mode == "mqtt" and mqtt_client:
                ds_msg = format_deepstream_schema_4(records)
                mqtt_client.publish(args.topic, json.dumps(ds_msg))
            elif args.mode == "stdout":
                for r in records:
                    print(json.dumps(r))
                    sys.stdout.flush()

            time.sleep(frame_interval)

    except KeyboardInterrupt:
        print("\n[*] Simulation stopped by operator.")
    finally:
        if mqtt_client:
            mqtt_client.disconnect()
        print(f"[OK] Simulation complete: {frame_num} frames emitted.")


if __name__ == "__main__":
    main()
