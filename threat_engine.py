#!/usr/bin/env python3
"""Sentinel-Edge: Spatio-Temporal Multi-Threat Rule Engine & Verification Gate

Deterministic, sub-millisecond edge threat evaluator operating on normalized
PipeGen YOLOv8 / DeepStream metadata. Replaces heavy 31B VLM inference with
mathematical geometric proofs requiring 0 MB extra GPU VRAM.

Rules Implemented:
1. Medical Emergency / Fall Detection (aspect ratio w/h > 1.15 for >= 3.0s)
2. Suspicious Unattended Luggage (luggage-person distance > 0.18 for >= 8.0s)
3. Unusual Crowding / Stampede Surge (person count >= 5 in zone for >= 2.0s)
4. Restricted Perimeter Breach (unauthorized presence dwelling >= 5.0s)
"""

import os
import json
import math
import time
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

log = logging.getLogger("sentinel.threat_engine")


def point_in_polygon(x: float, y: float, polygon: List[List[float]]) -> bool:
    """Ray-casting algorithm for testing if a normalized point is inside a polygon."""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    p1x, p1y = polygon[0]
    for i in range(n + 1):
        p2x, p2y = polygon[i % n]
        if min(p1y, p2y) < y <= max(p1y, p2y):
            if x <= max(p1x, p2x):
                if p1y != p2y:
                    xinters = (y - p1y) * (p2x - p1x) / (p2y - p1y) + p1x
                if p1x == p2x or x <= xinters:
                    inside = not inside
        p1x, p1y = p2x, p2y
    return inside


class ThreatEngine:
    def __init__(self, config_or_path: Any = None):
        if isinstance(config_or_path, (str, Path)):
            import yaml
            with open(config_or_path, "r", encoding="utf-8") as f:
                self.config = yaml.safe_load(f)
        elif isinstance(config_or_path, dict):
            self.config = config_or_path
        else:
            self.config = self._default_config()

        self.zones = self.config.get("zones", {})
        self.rules = {r["id"]: r for r in self.config.get("rules", [])}
        self.cooldown_sec = self.config.get("verification", {}).get("cooldown_seconds", 15)
        self.min_confidence = self.config.get("verification", {}).get("min_confidence", 0.45)
        
        # State tracking
        # track_id -> dict(first_seen, last_seen, last_bbox, history=[(t, x, y, w, h)])
        self.tracks: Dict[int, Dict[str, Any]] = {}
        # track_id -> timestamp when baggage became isolated
        self.unattended_tracker: Dict[int, Dict[str, Any]] = {}
        # track_id -> timestamp when person aspect ratio exceeded horizontal threshold
        self.fall_tracker: Dict[int, Dict[str, Any]] = {}
        # (track_id, zone_id) -> timestamp first entered zone
        self.zone_dwell_tracker: Dict[Tuple[int, str], float] = {}
        # zone_id -> timestamp when crowd threshold was first reached
        self.crowd_tracker: Dict[str, float] = {}
        # rule_id -> timestamp of last fired alert (for cooldown)
        self.alert_cooldowns: Dict[str, float] = {}
        # In-memory recent alerts
        self.recent_alerts: List[Dict[str, Any]] = []

        # Storage setup
        output_dir = Path(self.config.get("storage", {}).get("output_dir", "output"))
        output_dir.mkdir(parents=True, exist_ok=True)
        self.alerts_file = Path(self.config.get("storage", {}).get("alerts_file", "output/alerts.jsonl"))

    def _default_config(self) -> dict:
        return {
            "camera_id": "cam_01",
            "verification": {"min_confidence": 0.45, "cooldown_seconds": 15},
            "zones": {
                "secure_perimeter": {
                    "name": "Secure Perimeter Zone A",
                    "polygon": [[0.10, 0.15], [0.90, 0.15], [0.90, 0.85], [0.10, 0.85]]
                }
            },
            "rules": [
                {
                    "id": "unattended_package",
                    "type": "unattended",
                    "target_classes": ["backpack", "suitcase", "handbag"],
                    "anchor_class": "person",
                    "max_distance_norm": 0.18,
                    "dwell_seconds": 8.0,
                    "severity": "CRITICAL",
                    "actuator_level": 3,
                    "message": "VERIFIED THREAT: Unattended package isolated from owner > 8s",
                    "suggested_action": "Dispatch security to inspect isolated bag (Track ID #{track_id})"
                },
                {
                    "id": "fall_emergency",
                    "type": "fall",
                    "target_classes": ["person"],
                    "aspect_ratio_threshold": 1.15,
                    "dwell_seconds": 3.0,
                    "severity": "CRITICAL",
                    "actuator_level": 3,
                    "message": "MEDICAL EMERGENCY: Person collapsed / horizontal on floor > 3s",
                    "suggested_action": "Dispatch medical responder to Camera {camera_id} immediately"
                },
                {
                    "id": "crowd_surge",
                    "type": "count_threshold",
                    "zone": "secure_perimeter",
                    "target_classes": ["person"],
                    "max_count": 5,
                    "dwell_seconds": 2.0,
                    "severity": "WARNING",
                    "actuator_level": 2,
                    "message": "ANOMALY: Unusual crowding / sudden gathering detected in Camera Zone",
                    "suggested_action": "Monitor crowd density in Zone A; deploy crowd control if sustained"
                },
                {
                    "id": "perimeter_breach",
                    "type": "zone_dwell",
                    "zone": "secure_perimeter",
                    "target_classes": ["person", "car", "motorcycle"],
                    "dwell_seconds": 5.0,
                    "severity": "CRITICAL",
                    "actuator_level": 3,
                    "message": "SECURITY LOG: Prolonged loitering / unauthorized presence in monitored zone",
                    "suggested_action": "Security dispatch: unauthorized presence in restricted perimeter"
                }
            ]
        }

    def _normalize_box(self, box: Dict[str, Any], frame_w: int, frame_h: int) -> Tuple[float, float, float, float, float, float]:
        """Convert pixel bounding box to normalized (x_norm, y_norm, w_norm, h_norm, cx_norm, cy_norm)."""
        x = float(box.get("x", 0.0))
        y = float(box.get("y", 0.0))
        w = float(box.get("w", 0.0))
        h = float(box.get("h", 0.0))
        
        # If coordinates are already normalized <= 1.05
        if max(x, y, w, h) <= 1.05 and frame_w <= 1:
            cx = x + w / 2.0
            cy = y + h / 2.0
            return x, y, w, h, cx, cy
            
        fw = max(1.0, float(frame_w))
        fh = max(1.0, float(frame_h))
        xn = max(0.0, min(1.0, x / fw))
        yn = max(0.0, min(1.0, y / fh))
        wn = max(0.0, min(1.0, w / fw))
        hn = max(0.0, min(1.0, h / fh))
        cxn = max(0.0, min(1.0, xn + wn / 2.0))
        cyn = max(0.0, min(1.0, yn + hn / 2.0))
        return xn, yn, wn, hn, cxn, cyn

    def process_frame_detections(self, records: List[Dict[str, Any]], current_time: Optional[float] = None) -> List[Dict[str, Any]]:
        """Evaluate a batch of detection records from the current frame.
        
        Returns a list of newly fired verified alert objects.
        """
        now = current_time or time.time()
        new_alerts: List[Dict[str, Any]] = []

        active_persons: List[Dict[str, Any]] = []
        active_luggage: List[Dict[str, Any]] = []
        active_zone_occupants: Dict[str, List[Dict[str, Any]]] = {z: [] for z in self.zones.keys()}
        seen_track_ids = set()

        for r in records:
            conf = float(r.get("confidence", 0.0))
            if conf < self.min_confidence:
                continue

            tid = int(r.get("track_id", 0))
            cls = str(r.get("class_name", "")).lower()
            frame = r.get("frame", {})
            fw = int(frame.get("width", 1280))
            fh = int(frame.get("height", 720))
            cam_id = str(r.get("camera_id", self.config.get("camera_id", "cam_01")))

            box = r.get("bounding_box", {})
            xn, yn, wn, hn, cxn, cyn = self._normalize_box(box, fw, fh)

            seen_track_ids.add(tid)

            # Update track history
            if tid not in self.tracks:
                self.tracks[tid] = {
                    "track_id": tid,
                    "class_name": cls,
                    "first_seen": now,
                    "last_seen": now,
                    "history": []
                }
            self.tracks[tid]["last_seen"] = now
            self.tracks[tid]["history"].append((now, xn, yn, wn, hn, cxn, cyn))
            if len(self.tracks[tid]["history"]) > 60:
                self.tracks[tid]["history"].pop(0)

            rec_info = {
                "track_id": tid,
                "class_name": cls,
                "confidence": conf,
                "camera_id": cam_id,
                "box": (xn, yn, wn, hn),
                "centroid": (cxn, cyn),
                "aspect_ratio": wn / max(1e-4, hn)
            }

            if cls == "person":
                active_persons.append(rec_info)
            elif cls in ("backpack", "suitcase", "handbag"):
                active_luggage.append(rec_info)

            # Check geofence zones
            for zone_id, zone_data in self.zones.items():
                poly = zone_data.get("polygon", [])
                if point_in_polygon(cxn, cyn, poly):
                    active_zone_occupants[zone_id].append(rec_info)

        # -------------------------------------------------------------
        # Rule 1: Medical Emergency / Fall Detection
        # -------------------------------------------------------------
        rule_fall = self.rules.get("fall_emergency")
        if rule_fall:
            for p in active_persons:
                tid = p["track_id"]
                ar = p["aspect_ratio"]
                thresh = float(rule_fall.get("aspect_ratio_threshold", 1.15))
                dwell_target = float(rule_fall.get("dwell_seconds", 3.0))

                if ar >= thresh:
                    if tid not in self.fall_tracker:
                        self.fall_tracker[tid] = {"start_time": now, "peak_ar": ar}
                    else:
                        self.fall_tracker[tid]["peak_ar"] = max(self.fall_tracker[tid]["peak_ar"], ar)
                    
                    dwell = now - self.fall_tracker[tid]["start_time"]
                    if dwell >= dwell_target:
                        alert = self._create_alert(
                            rule=rule_fall,
                            camera_id=p["camera_id"],
                            track_ids=[tid],
                            now=now,
                            evidence={
                                "aspect_ratio": round(ar, 3),
                                "threshold": thresh,
                                "dwell_seconds": round(dwell, 2),
                                "posture": "horizontal_collapse",
                                "verification_gate": "PASSED (Deterministic Aspect Ratio Persistence)"
                            }
                        )
                        if alert:
                            new_alerts.append(alert)
                else:
                    self.fall_tracker.pop(tid, None)

        # -------------------------------------------------------------
        # Rule 2: Suspicious Unattended Luggage
        # -------------------------------------------------------------
        rule_unattended = self.rules.get("unattended_package")
        if rule_unattended:
            max_dist = float(rule_unattended.get("max_distance_norm", 0.18))
            dwell_target = float(rule_unattended.get("dwell_seconds", 8.0))

            for bag in active_luggage:
                bid = bag["track_id"]
                bcx, bcy = bag["centroid"]

                # Find distance to closest active person
                min_dist = float("inf")
                closest_pid = None
                for p in active_persons:
                    pcx, pcy = p["centroid"]
                    d = math.hypot(bcx - pcx, bcy - pcy)
                    if d < min_dist:
                        min_dist = d
                        closest_pid = p["track_id"]

                # Bag is isolated if no person is within max_dist
                is_isolated = (min_dist > max_dist)
                if is_isolated:
                    if bid not in self.unattended_tracker:
                        self.unattended_tracker[bid] = {
                            "start_time": now,
                            "min_observed_dist": min_dist,
                            "camera_id": bag["camera_id"]
                        }
                    else:
                        self.unattended_tracker[bid]["min_observed_dist"] = min(
                            self.unattended_tracker[bid]["min_observed_dist"], min_dist
                        )
                    
                    dwell = now - self.unattended_tracker[bid]["start_time"]
                    if dwell >= dwell_target:
                        alert = self._create_alert(
                            rule=rule_unattended,
                            camera_id=bag["camera_id"],
                            track_ids=[bid],
                            now=now,
                            evidence={
                                "luggage_track_id": bid,
                                "nearest_person_track_id": closest_pid,
                                "current_distance_norm": round(min_dist, 3),
                                "distance_threshold_norm": max_dist,
                                "dwell_seconds": round(dwell, 2),
                                "verification_gate": "PASSED (Spatial Euclidean Separation > 8s)"
                            }
                        )
                        if alert:
                            new_alerts.append(alert)
                else:
                    # Reset unattended timer if owner returns
                    self.unattended_tracker.pop(bid, None)

        # -------------------------------------------------------------
        # Rule 3: Unusual Crowding / Stampede Surge
        # -------------------------------------------------------------
        rule_crowd = self.rules.get("crowd_surge")
        if rule_crowd:
            target_zone = rule_crowd.get("zone", "secure_perimeter")
            occupants = active_zone_occupants.get(target_zone, [])
            persons_in_zone = [o for o in occupants if o["class_name"] == "person"]
            p_count = len(persons_in_zone)
            max_count = int(rule_crowd.get("max_count", 5))
            dwell_target = float(rule_crowd.get("dwell_seconds", 2.0))

            if p_count >= max_count:
                if target_zone not in self.crowd_tracker:
                    self.crowd_tracker[target_zone] = now
                dwell = now - self.crowd_tracker[target_zone]
                if dwell >= dwell_target:
                    tids = [p["track_id"] for p in persons_in_zone]
                    alert = self._create_alert(
                        rule=rule_crowd,
                        camera_id=self.config.get("camera_id", "cam_01"),
                        track_ids=tids,
                        now=now,
                        evidence={
                            "zone": target_zone,
                            "occupant_count": p_count,
                            "threshold": max_count,
                            "dwell_seconds": round(dwell, 2),
                            "verification_gate": "PASSED (Sustained Polygon Density Surge)"
                        }
                    )
                    if alert:
                        new_alerts.append(alert)
            else:
                self.crowd_tracker.pop(target_zone, None)

        # -------------------------------------------------------------
        # Rule 4: Restricted Perimeter Breach
        # -------------------------------------------------------------
        rule_breach = self.rules.get("perimeter_breach")
        if rule_breach:
            target_zone = rule_breach.get("zone", "secure_perimeter")
            dwell_target = float(rule_breach.get("dwell_seconds", 5.0))
            occupants = active_zone_occupants.get(target_zone, [])

            for o in occupants:
                tid = o["track_id"]
                key = (tid, target_zone)
                if key not in self.zone_dwell_tracker:
                    self.zone_dwell_tracker[key] = now
                
                dwell = now - self.zone_dwell_tracker[key]
                if dwell >= dwell_target:
                    alert = self._create_alert(
                        rule=rule_breach,
                        camera_id=o["camera_id"],
                        track_ids=[tid],
                        now=now,
                        evidence={
                            "zone": target_zone,
                            "class_name": o["class_name"],
                            "track_id": tid,
                            "dwell_seconds": round(dwell, 2),
                            "verification_gate": "PASSED (Point-In-Polygon Loitering Gate)"
                        }
                    )
                    if alert:
                        new_alerts.append(alert)

        # Clean up stale tracks (not seen in last 30s)
        stale_threshold = now - 30.0
        for tid in list(self.tracks.keys()):
            if self.tracks[tid]["last_seen"] < stale_threshold:
                self.tracks.pop(tid, None)
                self.unattended_tracker.pop(tid, None)
                self.fall_tracker.pop(tid, None)

        return new_alerts

    def _create_alert(self, rule: Dict[str, Any], camera_id: str, track_ids: List[int], now: float, evidence: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rule_id = rule["id"]
        last_fired = self.alert_cooldowns.get(rule_id, 0.0)
        if (now - last_fired) < self.cooldown_sec:
            return None  # Under cooldown

        self.alert_cooldowns[rule_id] = now
        alert_id = f"ALT-{int(now * 1000) % 1000000:06d}-{rule_id[:4].upper()}"
        ts_iso = datetime.fromtimestamp(now, tz=timezone.utc).isoformat()

        # Format message and suggested action templates
        primary_tid = track_ids[0] if track_ids else 0
        raw_msg = rule.get("message", "THREAT DETECTED")
        msg = raw_msg.format(track_id=primary_tid, camera_id=camera_id)
        raw_action = rule.get("suggested_action", "Investigate monitored area.")
        action = raw_action.format(track_id=primary_tid, camera_id=camera_id)

        alert_record = {
            "alert_id": alert_id,
            "rule_id": rule_id,
            "rule_name": rule.get("name", rule_id),
            "severity": rule.get("severity", "WARNING"),
            "actuator_level": int(rule.get("actuator_level", 2)),
            "camera_id": camera_id,
            "track_ids": track_ids,
            "timestamp": ts_iso,
            "epoch": now,
            "message": msg,
            "suggested_action": action,
            "evidence": evidence,
            "acknowledged": False
        }

        self.recent_alerts.append(alert_record)
        if len(self.recent_alerts) > 200:
            self.recent_alerts.pop(0)

        # Write to JSONL
        self._write_alert_record(alert_record)
        log.warning("[%s] %s: %s (Action: %s)", alert_record["severity"], rule_id, msg, action)
        return alert_record

    def _write_alert_record(self, alert_record: Dict[str, Any]):
        try:
            with open(self.alerts_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(alert_record) + "\n")
        except Exception as e:
            log.error("Failed to append alert to %s: %s", self.alerts_file, e)

    def get_recent_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        return list(reversed(self.recent_alerts[-limit:]))

    def acknowledge_alert(self, alert_id: str) -> bool:
        for a in self.recent_alerts:
            if a["alert_id"] == alert_id:
                a["acknowledged"] = True
                return True
        return False
