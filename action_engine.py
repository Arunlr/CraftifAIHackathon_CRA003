#!/usr/bin/env python3
"""
PipeGen Action Engine  -  the "ACT" half of your PipeGen project.

PipeGen (DeepStream + TensorRT) does the perception and publishes detections
(MQTT or JSON metadata). This engine turns them into real-world actions:

  zone_enter / zone_dwell  object of class X inside a polygon (for N seconds)
  line_cross               counts per class and direction across a line
  wrong_way                movement against the allowed direction
  count_threshold          crowd / queue / demand levels (warning, critical)
  group_on_vehicle         triple riding (3+ persons on one motorcycle)
  unattended               bag left alone (no person nearby) for N seconds
  slot_occupancy           parking / seat slots free vs occupied
  fall                     person lying down (wide box) for N seconds
  danger_zone              hand/body inside a machine danger zone -> BLOCK / CLEAR

Sinks: console, run/events.jsonl, run/state.json (read by dashboard.py),
MQTT alerts (alerts/<rule> + retained alerts/state), Telegram, serial -> ESP32.

Examples
  # 1) Try it right now with fake detections (no PipeGen needed)
  python simulate.py elephant | python action_engine.py -c configs/elephant_track.yaml

  # 2) Live: PipeGen publishes MQTT to a local Mosquitto broker
  python action_engine.py -c configs/elephant_track.yaml --source "mqtt://localhost:1883/#"

  # 3) Live: PipeGen writes JSON metadata
  python action_engine.py -c configs/traffic_sentinel.yaml --source file:/home/me/out/meta.jsonl
  python action_engine.py -c configs/traffic_sentinel.yaml --source dir:/home/me/out/json/

  # See what PipeGen actually sends (first 3 messages) so you can adjust the config
  python action_engine.py -c configs/elephant_track.yaml --source "mqtt://localhost:1883/#" --print-raw 3
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import os
import queue
import sys
import threading
import time
import urllib.parse
import urllib.request
from collections import deque

try:
    import yaml  # pip install pyyaml
except ImportError:  # pragma: no cover
    yaml = None

COCO80 = [
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat",
    "traffic light", "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog",
    "horse", "sheep", "cow", "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella",
    "handbag", "tie", "suitcase", "frisbee", "skis", "snowboard", "sports ball", "kite",
    "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant",
    "bed", "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone",
    "microwave", "oven", "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors",
    "teddy bear", "hair drier", "toothbrush",
]
LEVEL = {"info": 1, "warning": 2, "critical": 3}
LEVEL_NAME = {0: "ALL CLEAR", 1: "INFO", 2: "WARNING", 3: "CRITICAL"}


# --------------------------------------------------------------------------- geometry
def point_in_poly(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y):
            if x < (xj - xi) * (y - yi) / (yj - yi) + xi:
                inside = not inside
        j = i
    return inside


def box_hits_poly(box, poly, n=5):
    """True if any of n*n sample points of the box (or a polygon vertex) is inside."""
    x1, y1, x2, y2 = box
    for i in range(n):
        for j in range(n):
            if point_in_poly(x1 + (x2 - x1) * i / (n - 1), y1 + (y2 - y1) * j / (n - 1), poly):
                return True
    return any(x1 <= px <= x2 and y1 <= py <= y2 for px, py in poly)


def area(b):
    return max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])


def inter(a, b):
    return area((max(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), min(a[3], b[3])))


def iou(a, b):
    i = inter(a, b)
    u = area(a) + area(b) - i
    return i / u if u > 0 else 0.0


def ioa(a, b):
    """Fraction of box a that lies inside box b."""
    ar = area(a)
    return inter(a, b) / ar if ar > 0 else 0.0


def side(a, b, p):
    """> 0 if p is on the RIGHT of the arrow a->b (image coordinates, y down)."""
    return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0])


def seg_intersect(p1, p2, q1, q2):
    return ((side(q1, q2, p1) > 0) != (side(q1, q2, p2) > 0)) and \
           ((side(p1, p2, q1) > 0) != (side(p1, p2, q2) > 0))


# --------------------------------------------------------------------------- parsing
BOX_KEYS = ("bbox", "box", "rect", "rect_params", "bounding_box", "boundingBox", "xyxy")
LIST_KEYS = ("objects", "detections", "objs", "obj_meta", "object_meta", "results",
             "predictions", "boxes")
LABEL_KEYS = ("label", "obj_label", "objectType", "object_type", "class_name", "className",
              "class", "name", "category")
CLASS_ID_KEYS = ("class_id", "classId", "cls", "class_index", "category_id")
ID_KEYS = ("track_id", "trackId", "tracking_id", "trackingId", "object_id", "objectId", "id", "tid")
CONF_KEYS = ("confidence", "conf", "score", "probability", "prob")
TS_KEYS = ("@timestamp", "timestamp", "ts", "time", "ntp_timestamp", "ntpTimestamp")
FRAME_KEYS = ("frame_num", "frameNum", "frame_number", "frame", "frame_id")
SRC_KEYS = ("sensorId", "sensor_id", "source_id", "sourceId", "stream_id", "camera_id", "cam")


def _first(d, keys):
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_time(v):
    if _num(v):
        v = float(v)
        if v > 1e17:
            return v / 1e9
        if v > 1e14:
            return v / 1e6
        if v > 1e11:
            return v / 1e3
        return v
    if isinstance(v, str):
        s = v.strip()
        try:
            return parse_time(float(s))
        except ValueError:
            pass
        try:
            return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


class Det:
    __slots__ = ("tid", "label", "conf", "box", "kps")

    def __init__(self, tid, label, conf, box, kps=None):
        self.tid, self.label, self.conf, self.box, self.kps = tid, label, conf, box, kps


class Frame:
    __slots__ = ("ts", "src", "dets", "complete")

    def __init__(self, ts, src, dets, complete=True):
        self.ts, self.src, self.dets, self.complete = ts, src, dets, complete


class Parser:
    """Understands DeepStream msgconv 'minimal' + 'full' schemas and most custom JSON layouts."""

    def __init__(self, cfg):
        st = cfg.get("stream") or {}
        self.W = float(st.get("width", 1920))
        self.H = float(st.get("height", 1080))
        self.fps = float(st.get("fps", 30))
        self.fmt = st.get("bbox_format", "xyxy")  # for list boxes: xyxy | xywh | cxcywh
        self.class_names = cfg.get("class_names") or COCO80
        self.alias = {}
        for canon, names in (cfg.get("label_aliases") or {}).items():
            for n in ([names] if isinstance(names, str) else list(names)) + [canon]:
                self.alias[str(n).strip().lower()] = str(canon)

    def canon(self, label):
        if label is None:
            return "object"
        if _num(label) or (isinstance(label, str) and label.strip().isdigit()):
            i = int(float(label))
            label = self.class_names[i] if 0 <= i < len(self.class_names) else f"class_{i}"
        s = str(label).strip().lower()
        return self.alias.get(s, s)

    # -- entry point
    def parse(self, raw):
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", "replace")
        if isinstance(raw, str):
            raw = raw.strip()
            if not raw:
                return []
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                return []
        return self._frames(raw)

    def _looks_like_det(self, o):
        if not isinstance(o, dict):
            return False
        if any(k in o for k in BOX_KEYS):
            return True
        return self._box(o) is not None

    def _frames(self, obj):
        out = []
        if isinstance(obj, list):
            if obj and all(isinstance(o, dict) and self._looks_like_det(o) for o in obj):
                return [self._frame(obj, {})]
            for o in obj:
                out.extend(self._frames(o))
            return out
        if not isinstance(obj, dict):
            return out
        if isinstance(obj.get("frames"), list):
            meta = {k: v for k, v in obj.items() if k != "frames"}
            for f in obj["frames"]:
                if isinstance(f, dict):
                    merged = dict(meta)
                    merged.update(f)
                    out.extend(self._frames(merged))
            return out
        for k in LIST_KEYS:
            if isinstance(obj.get(k), list):
                return [self._frame(obj[k], obj)]
        if isinstance(obj.get("object"), dict):  # DeepStream "full" schema: 1 object / message
            f = self._frame([obj["object"]], obj)
            f.complete = False
            return [f]
        if self._looks_like_det(obj):
            f = self._frame([obj], {})
            f.complete = False
            return [f]
        return out

    def _frame(self, items, meta):
        ts = None
        src = None
        W, H = self.W, self.H
        if isinstance(meta, dict):
            v = _first(meta, TS_KEYS)
            ts = parse_time(v) if v is not None else None
            if ts is None:
                fn = _first(meta, FRAME_KEYS)
                if _num(fn):
                    ts = float(fn) / self.fps
            src = _first(meta, SRC_KEYS)
            if src is None and isinstance(meta.get("sensor"), dict):
                src = meta["sensor"].get("id")
            w = _first(meta, ("width", "frame_width", "source_width", "img_width"))
            h = _first(meta, ("height", "frame_height", "source_height", "img_height"))
            if _num(w) and _num(h) and w > 0 and h > 0:
                W, H = float(w), float(h)
        dets = [d for d in (self._det(o, W, H) for o in items) if d is not None]
        return Frame(ts, str(src if src is not None else "cam0"), dets, True)

    def _det(self, o, W, H):
        if isinstance(o, str):  # DeepStream minimal schema: "trackId|left|top|right|bottom|label|..."
            p = o.split("|")
            if len(p) < 5:
                return None
            try:
                box = tuple(float(v) for v in p[1:5])
            except ValueError:
                return None
            conf = None
            if len(p) > 6:
                c = _to_float(p[-1])
                conf = c if c is not None and 0.0 <= c <= 1.0 else None
            label = p[5] if len(p) > 5 else "object"
            return Det(_to_int(p[0]), self.canon(label), conf, self._norm(box, W, H))
        if not isinstance(o, dict):
            return None
        box = None
        for k in BOX_KEYS:
            if k in o:
                box = self._box(o[k])
                break
        if box is None:
            box = self._box(o)
        if box is None:
            return None
        label = _first(o, LABEL_KEYS)
        if isinstance(label, dict):
            label = label.get("name") or label.get("label")
        if label is None:
            cid = _first(o, CLASS_ID_KEYS)
            if cid is not None:
                label = cid
            else:
                for k in ("vehicle", "person", "face"):
                    if k in o:
                        label = k
                        break
        kps = self._kps(o.get("keypoints") or o.get("kps") or o.get("landmarks"), W, H)
        return Det(_to_int(_first(o, ID_KEYS)), self.canon(label),
                   _to_float(_first(o, CONF_KEYS)), self._norm(box, W, H), kps)

    def _box(self, b):
        if isinstance(b, (list, tuple)) and len(b) >= 4 and all(_num(v) for v in b[:4]):
            a, c, e, f = (float(v) for v in b[:4])
            if self.fmt == "xywh":
                return (a, c, a + e, c + f)
            if self.fmt == "cxcywh":
                return (a - e / 2, c - f / 2, a + e / 2, c + f / 2)
            return (a, c, e, f)
        if not isinstance(b, dict):
            return None
        k = {str(kk).lower(): vv for kk, vv in b.items()}

        def g(*names):
            vals = [k.get(n) for n in names]
            return vals if all(_num(v) for v in vals) else None

        v = g("left", "top", "width", "height")
        if v:
            return (v[0], v[1], v[0] + v[2], v[1] + v[3])
        for names in (("left", "top", "right", "bottom"), ("x1", "y1", "x2", "y2"),
                      ("xmin", "ymin", "xmax", "ymax"),
                      ("topleftx", "toplefty", "bottomrightx", "bottomrighty")):
            v = g(*names)
            if v:
                return tuple(float(x) for x in v)
        v = g("x", "y", "w", "h") or g("x", "y", "width", "height")
        if v:
            if self.fmt == "cxcywh":
                return (v[0] - v[2] / 2, v[1] - v[3] / 2, v[0] + v[2] / 2, v[1] + v[3] / 2)
            return (v[0], v[1], v[0] + v[2], v[1] + v[3])
        return None

    def _norm(self, box, W, H):
        x1, y1, x2, y2 = box
        if x2 < x1:
            x1, x2 = x2, x1
        if y2 < y1:
            y1, y2 = y2, y1
        if max(abs(x1), abs(y1), abs(x2), abs(y2)) > 1.5:  # pixels -> 0..1
            x1, x2, y1, y2 = x1 / W, x2 / W, y1 / H, y2 / H
        return (x1, y1, x2, y2)

    def _kps(self, k, W, H):
        if not k or not isinstance(k, list):
            return None
        if _num(k[0]):  # flat list
            step = 3 if (len(k) == 51 or (len(k) % 3 == 0 and len(k) != 34)) else 2
            k = [k[i:i + step] for i in range(0, len(k) - step + 1, step)]
        pts = []
        for p in k:
            if isinstance(p, dict):
                x, y = p.get("x"), p.get("y")
                c = p.get("score", p.get("conf", p.get("confidence", 1.0)))
            elif isinstance(p, (list, tuple)) and len(p) >= 2:
                x, y = p[0], p[1]
                c = p[2] if len(p) > 2 else 1.0
            else:
                continue
            if _num(x) and _num(y):
                pts.append([float(x), float(y), float(c) if _num(c) else 1.0])
        if pts and max(max(abs(p[0]), abs(p[1])) for p in pts) > 1.5:
            for p in pts:
                p[0] /= W
                p[1] /= H
        return pts or None


# --------------------------------------------------------------------------- tracking
class IoUTracker:
    """Fallback tracker, only used when PipeGen's output has no tracking IDs."""

    def __init__(self, thr=0.25, max_age=1.5):
        self.thr, self.max_age = thr, max_age
        self.tracks = {}
        self.next_id = 100000

    def assign(self, src, dets, now):
        cands = [(k, v) for k, v in self.tracks.items() if k[0] == src]
        used = set()
        for d in sorted(dets, key=lambda d: -(d.conf or 0.0)):
            if d.tid is not None:
                continue
            best, best_iou = None, self.thr
            for k, (box, label, _ts) in cands:
                if k in used or label != d.label:
                    continue
                v = iou(box, d.box)
                if v > best_iou:
                    best, best_iou = k, v
            if best is None:
                self.next_id += 1
                best = (src, self.next_id)
            used.add(best)
            d.tid = best[1]
            self.tracks[best] = (d.box, d.label, now)
        for k in [k for k, v in self.tracks.items() if now - v[2] > self.max_age]:
            del self.tracks[k]


class Track:
    __slots__ = ("key", "tid", "label", "box", "conf", "kps", "first", "last", "present",
                 "hist", "zin", "zsince", "flags", "mode")

    def __init__(self, key, det, now, mode):
        self.key, self.tid, self.label, self.mode = key, det.tid, det.label, mode
        self.first = now
        self.hist = deque(maxlen=240)
        self.zin, self.zsince, self.flags = {}, {}, {}
        self.update(det, now)

    def update(self, det, now):
        self.box, self.conf, self.kps = det.box, det.conf, det.kps
        self.last, self.present = now, True
        self.hist.append((now,) + self.anchor())

    def anchor(self):
        x1, y1, x2, y2 = self.box
        if self.mode == "center":
            return ((x1 + x2) / 2, (y1 + y2) / 2)
        return ((x1 + x2) / 2, y2)

    def center(self):
        x1, y1, x2, y2 = self.box
        return ((x1 + x2) / 2, (y1 + y2) / 2)


# --------------------------------------------------------------------------- rules
class _SafeDict(dict):
    def __missing__(self, k):
        return "{" + k + "}"


DEFAULT_MSG = {
    "zone_enter": "{class} #{track_id} entered {zone}",
    "zone_dwell": "{class} #{track_id} in {zone} for {seconds}s",
    "line_cross": "{class} #{track_id} crossed {rule} ({direction})",
    "wrong_way": "WRONG-WAY {class} #{track_id} in {zone}",
    "count_threshold": "{zone}: {count} objects -> {level}",
    "group_on_vehicle": "TRIPLE RIDING: {riders} riders on {class} #{track_id}",
    "unattended": "Unattended {class} #{track_id} for {seconds}s",
    "slot_occupancy": "Slot {slot} {status} - {free}/{total} free",
    "fall": "FALL: {class} #{track_id} down for {seconds}s",
    "danger_zone": "{state}: body part inside {zone}",
    "zone_conflict": "{class} #{track_id} moved through {zone} while {protected} {protected_label} inside",
}


class Rule:
    stateful = False

    def __init__(self, spec, eng):
        self.spec, self.eng = spec, eng
        self.type = spec["type"]
        self.name = str(spec.get("name") or self.type)
        self.classes = {eng.parser.canon(c) for c in spec.get("classes", [])} or None
        self.exclude = {eng.parser.canon(c) for c in spec.get("exclude_classes", [])}
        self.severity = spec.get("severity", "warning")
        self.message = spec.get("message")
        self.cooldown = float(spec.get("cooldown", 0))
        self.zone = spec.get("zone")
        if self.zone is not None and self.zone not in eng.zones:
            raise SystemExit(f"[config] rule '{self.name}': zone '{self.zone}' is not defined "
                             f"(known: {', '.join(eng.zones) or 'none'})")
        self.fired = 0
        self.last_fire = None
        self._last_ts = -1e18

    def match(self, t):
        return t.present and (self.classes is None or t.label in self.classes) \
            and t.label not in self.exclude

    def zone_count(self):
        if not self.zone:
            return sum(1 for t in self.eng.tracks.values() if self.match(t))
        return sum(1 for t in self.eng.tracks.values() if self.match(t) and t.zin.get(self.zone))

    def event(self, now, data, severity=None, force=False):
        if not force and self.cooldown and now - self._last_ts < self.cooldown:
            return None
        self._last_ts = now
        sev = severity or self.severity
        if sev not in ("info", "clear"):
            self.fired += 1
        d = {"rule": self.name, "zone": self.zone or ""}
        d.update(data)
        if "count" not in d:
            d["count"] = self.zone_count()
        if sev == "clear":
            tmpl = self.spec.get("clear_message") or "{rule}: back to normal"
        else:
            tmpl = self.message or DEFAULT_MSG.get(self.type, "{rule}")
        try:
            text = tmpl.format_map(_SafeDict(d))
        except (ValueError, IndexError):
            text = tmpl
        self.last_fire = dt.datetime.now().strftime("%H:%M:%S")
        ev = {"ts": round(now, 3), "time": self.last_fire, "type": self.type, "severity": sev,
              "message": text, "stateful": self.stateful}
        ev.update(d)
        return ev

    def kpi(self):
        k = {"type": self.type, "severity": self.severity, "fired": self.fired,
             "last": self.last_fire, "zone": self.zone or ""}
        if self.zone:
            k["now"] = self.zone_count()
        return k

    def evaluate(self, now):  # pragma: no cover - overridden
        return []


class ZoneDwell(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        if not self.zone:
            raise SystemExit(f"[config] rule '{self.name}' needs a zone")
        default = 0.5 if self.type == "zone_enter" else 5.0
        self.seconds = float(spec.get("seconds", spec.get("min_seconds", default)))
        self.rearm = bool(spec.get("rearm", True))

    def evaluate(self, now):
        out, key = [], ("zd", self.name)
        for t in self.eng.tracks.values():
            if not self.match(t):
                continue
            if t.zin.get(self.zone):
                dwell = now - t.zsince.get(self.zone, now)
                if dwell >= self.seconds and not t.flags.get(key):
                    ev = self.event(now, {"track_id": t.tid, "class": t.label,
                                          "seconds": round(dwell, 1)})
                    if ev:
                        t.flags[key] = True
                        out.append(ev)
            elif self.rearm and t.flags.get(key):
                t.flags[key] = False
        return out


class LineCross(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        self.line = eng.get_geom("lines", spec.get("line"), self.name)
        self.direction = spec.get("direction", "any")  # any | L2R | R2L
        self.emit = bool(spec.get("emit_events", False))
        names = spec.get("direction_names") or {}
        self.names = {"L2R": str(names.get("L2R", "L2R")), "R2L": str(names.get("R2L", "R2L"))}
        self.counts = {"L2R": {}, "R2L": {}}
        self.prev = {}

    def total(self, d):
        return sum(self.counts[d].values())

    def evaluate(self, now):
        out = []
        a, b = self.line
        for key, t in self.eng.tracks.items():
            if not self.match(t):
                continue
            p = t.anchor()
            q = self.prev.get(key)
            self.prev[key] = p
            if q is None or q == p or not seg_intersect(q, p, a, b):
                continue
            d = "L2R" if side(a, b, p) > 0 else "R2L"
            last = t.flags.get(("lc", self.name))
            if last is not None and now - last < 1.0:
                continue
            t.flags[("lc", self.name)] = now
            self.counts[d][t.label] = self.counts[d].get(t.label, 0) + 1
            if self.emit and self.direction in ("any", d):
                ev = self.event(now, {"track_id": t.tid, "class": t.label,
                                      "direction": self.names[d], "total": self.total(d)})
                if ev:
                    out.append(ev)
        if len(self.prev) > 4000:
            self.prev = {k: v for k, v in self.prev.items() if k in self.eng.tracks}
        return out

    def kpi(self):
        k = super().kpi()
        k.update(L2R=self.total("L2R"), R2L=self.total("R2L"), by_class=self.counts,
                 names=self.names)
        return k


class WrongWay(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        (x1, y1), (x2, y2) = eng.get_geom("directions", spec.get("direction"), self.name)
        n = math.hypot(x2 - x1, y2 - y1) or 1.0
        self.vec = ((x2 - x1) / n, (y2 - y1) / n)
        self.min_dist = float(spec.get("min_distance", 0.06))
        self.window = float(spec.get("window", 3.0))
        self.max_cos = float(spec.get("max_cos", -0.5))

    def evaluate(self, now):
        out, key = [], ("ww", self.name)
        for t in self.eng.tracks.values():
            if not self.match(t) or t.flags.get(key):
                continue
            if self.zone and not t.zin.get(self.zone):
                continue
            old = next(((x, y) for ts, x, y in t.hist if now - ts <= self.window), None)
            if old is None:
                continue
            _, cx, cy = t.hist[-1]
            dx, dy = cx - old[0], cy - old[1]
            dist = math.hypot(dx, dy)
            if dist < self.min_dist:
                continue
            if (dx * self.vec[0] + dy * self.vec[1]) / dist <= self.max_cos:
                ev = self.event(now, {"track_id": t.tid, "class": t.label})
                if ev:
                    t.flags[key] = True
                    out.append(ev)
        return out


class CountThreshold(Rule):
    stateful = True

    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        lv = spec.get("levels") or {self.severity: spec.get("threshold", 10)}
        self.levels = sorted(((int(v), str(k)) for k, v in lv.items()), reverse=True)
        self.seconds = float(spec.get("seconds", 2.0))
        self.notify_clear = bool(spec.get("notify_clear", True))
        self.active, self.cand, self.cand_since, self.count = "normal", "normal", None, 0

    def evaluate(self, now):
        c = self.zone_count()
        self.count = c
        lvl = next((name for thr, name in self.levels if c >= thr), "normal")
        if lvl != self.cand:
            self.cand, self.cand_since = lvl, now
        if self.cand == self.active or now - (self.cand_since or now) < self.seconds:
            return []
        prev, self.active = self.active, self.cand
        if self.active == "normal":
            if not self.notify_clear:
                return []
            ev = self.event(now, {"count": c, "level": "normal", "previous": prev},
                            severity="clear", force=True)
        else:
            sev = self.active if self.active in LEVEL else self.severity
            ev = self.event(now, {"count": c, "level": self.active, "previous": prev},
                            severity=sev, force=True)
        return [ev] if ev else []

    def kpi(self):
        k = super().kpi()
        k.update(count=self.count, level=self.active,
                 thresholds={name: thr for thr, name in self.levels})
        return k


class GroupOnVehicle(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        cn = eng.parser.canon
        self.vehicles = {cn(c) for c in spec.get("vehicle_classes", ["motorcycle"])}
        self.riders = {cn(c) for c in spec.get("rider_classes", ["person"])}
        self.min_riders = int(spec.get("min_riders", 3))
        self.seconds = float(spec.get("seconds", 0.6))
        self.min_overlap = float(spec.get("min_overlap", 0.25))

    def evaluate(self, now):
        out, key, skey = [], ("gv", self.name), ("gv_since", self.name)
        people = [t for t in self.eng.tracks.values() if t.present and t.label in self.riders]
        for v in self.eng.tracks.values():
            if not v.present or v.label not in self.vehicles or v.flags.get(key):
                continue
            if self.zone and not v.zin.get(self.zone):
                continue
            x1, y1, x2, y2 = v.box
            w, h = x2 - x1, y2 - y1
            region = (x1 - 0.15 * w, y1 - 1.2 * h, x2 + 0.15 * w, y2 + 0.1 * h)
            n = 0
            for p in people:
                pcx = (p.box[0] + p.box[2]) / 2
                if ioa(p.box, region) >= self.min_overlap and x1 - 0.1 * w <= pcx <= x2 + 0.1 * w:
                    n += 1
            if n >= self.min_riders:
                since = v.flags.setdefault(skey, now)
                if now - since >= self.seconds:
                    ev = self.event(now, {"track_id": v.tid, "class": v.label, "riders": n})
                    if ev:
                        v.flags[key] = True
                        out.append(ev)
            else:
                v.flags.pop(skey, None)
        return out


class Unattended(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        cn = eng.parser.canon
        if self.classes is None:
            self.classes = {cn("backpack"), cn("handbag"), cn("suitcase")}
        self.owners = {cn(c) for c in spec.get("owner_classes", ["person"])}
        self.seconds = float(spec.get("seconds", 30))
        self.radius = float(spec.get("radius", 0.12))
        self.still = float(spec.get("still_eps", 0.015))

    def evaluate(self, now):
        out, key, skey = [], ("ua", self.name), ("ua_since", self.name)
        people = [t.center() for t in self.eng.tracks.values()
                  if t.present and t.label in self.owners]
        for t in self.eng.tracks.values():
            if not self.match(t) or t.flags.get(key):
                continue
            if self.zone and not t.zin.get(self.zone):
                continue
            _, ax, ay = t.hist[-1]
            moving = any(math.hypot(x - ax, y - ay) > self.still
                         for ts, x, y in t.hist if now - ts <= 2.0)
            cx, cy = t.center()
            near = any(math.hypot(px - cx, py - cy) <= self.radius for px, py in people)
            if moving or near:
                t.flags.pop(skey, None)
                continue
            since = t.flags.setdefault(skey, now)
            if now - since >= self.seconds:
                ev = self.event(now, {"track_id": t.tid, "class": t.label,
                                      "seconds": round(now - since, 1)})
                if ev:
                    t.flags[key] = True
                    out.append(ev)
        return out


class SlotOccupancy(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        names = spec.get("slots") or []
        if isinstance(names, str):
            pre = names.rstrip("*")
            names = sorted(z for z in eng.zones if z.startswith(pre))
        for n in names:
            if n not in eng.zones:
                raise SystemExit(f"[config] rule '{self.name}': slot zone '{n}' is not defined")
        self.slots = list(names)
        self.seconds = float(spec.get("seconds", 2.0))
        self.emit = bool(spec.get("emit_events", True))
        self.state = {n: False for n in self.slots}
        self.cand = {n: (False, None) for n in self.slots}
        self.full_sent = False

    def free(self):
        return sum(1 for v in self.state.values() if not v)

    def evaluate(self, now):
        out = []
        for n in self.slots:
            occ = any(self.match(t) and t.zin.get(n) for t in self.eng.tracks.values())
            c, since = self.cand[n]
            if occ != c or since is None:
                self.cand[n] = (occ, now)
                continue
            if occ != self.state[n] and now - since >= self.seconds:
                self.state[n] = occ
                if self.emit:
                    ev = self.event(now, {"slot": n, "status": "occupied" if occ else "free",
                                          "free": self.free(), "total": len(self.slots)},
                                    severity="info", force=True)
                    if ev:
                        out.append(ev)
        free = self.free()
        if free == 0 and self.slots and not self.full_sent:
            self.full_sent = True
            self.message, saved = self.spec.get("full_message", "Lot FULL - 0/{total} free"), \
                self.message
            ev = self.event(now, {"slot": "-", "status": "full", "free": 0,
                                  "total": len(self.slots)}, force=True)
            self.message = saved
            if ev:
                out.append(ev)
        elif free > 0:
            self.full_sent = False
        return out

    def kpi(self):
        k = super().kpi()
        k.update(free=self.free(), total=len(self.slots), slots=self.state)
        return k


class Fall(Rule):
    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        if self.classes is None:
            self.classes = {eng.parser.canon("person")}
        self.ratio = float(spec.get("aspect_ratio", 1.15))
        self.seconds = float(spec.get("seconds", 2.0))

    def evaluate(self, now):
        out, key, skey = [], ("fall", self.name), ("fall_since", self.name)
        W, H = self.eng.parser.W, self.eng.parser.H
        for t in self.eng.tracks.values():
            if not self.match(t):
                continue
            if self.zone and not t.zin.get(self.zone):
                continue
            x1, y1, x2, y2 = t.box
            if (x2 - x1) * W / max((y2 - y1) * H, 1e-6) >= self.ratio:
                since = t.flags.setdefault(skey, now)
                if not t.flags.get(key) and now - since >= self.seconds:
                    ev = self.event(now, {"track_id": t.tid, "class": t.label,
                                          "seconds": round(now - since, 1)})
                    if ev:
                        t.flags[key] = True
                        out.append(ev)
            else:
                t.flags.pop(skey, None)
                t.flags.pop(key, None)
        return out


class DangerZone(Rule):
    """Machine interlock: BLOCKED while a wrist keypoint (or the body box) is in the zone."""
    stateful = True

    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        if not self.zone:
            raise SystemExit(f"[config] rule '{self.name}' needs a zone")
        if self.classes is None:
            self.classes = {eng.parser.canon("person")}
        self.kp_idx = [int(i) for i in spec.get("keypoints", [9, 10])]  # COCO-17 wrists
        self.kp_conf = float(spec.get("keypoint_confidence", 0.3))
        self.clear_seconds = float(spec.get("clear_seconds", 1.0))
        self.blocked, self.clear_since = False, None

    def evaluate(self, now):
        poly = self.eng.zones[self.zone]
        hit, via = None, ""
        for t in self.eng.tracks.values():
            if not self.match(t):
                continue
            if t.kps:
                pts = [t.kps[i] for i in self.kp_idx if i < len(t.kps) and t.kps[i][2] >= self.kp_conf]
                if any(point_in_poly(p[0], p[1], poly) for p in pts):
                    hit, via = t, "keypoints"
                    break
                if pts:
                    continue
            if box_hits_poly(t.box, poly):
                hit, via = t, "box"
                break
        if hit is not None:
            self.clear_since = None
            if not self.blocked:
                self.blocked = True
                ev = self.event(now, {"track_id": hit.tid, "class": hit.label,
                                      "state": "BLOCKED", "via": via}, force=True)
                return [ev] if ev else []
            return []
        if self.blocked:
            if self.clear_since is None:
                self.clear_since = now
            if now - self.clear_since >= self.clear_seconds:
                self.blocked = False
                ev = self.event(now, {"state": "CLEAR"}, severity="clear", force=True)
                return [ev] if ev else []
        return []

    def kpi(self):
        k = super().kpi()
        k.update(state="BLOCKED" if self.blocked else "CLEAR")
        return k


class ZoneConflict(Rule):
    """Right-of-way conflict: an object of `classes` keeps MOVING inside a zone while at least
    `min_protected` objects of `protected_classes` are also inside it.
    Zebra crossing: vehicle drives through while pedestrians are on it (did not yield).
    School gate: dog(s) among children (set min_movement: 0 so standing dogs count too)."""

    def __init__(self, spec, eng):
        super().__init__(spec, eng)
        if not self.zone:
            raise SystemExit(f"[config] rule '{self.name}' needs a zone")
        cn = eng.parser.canon
        if self.classes is None:
            self.classes = {cn(c) for c in ("car", "motorcycle", "bus", "truck", "bicycle")}
        self.protected = {cn(c) for c in spec.get("protected_classes", ["person"])}
        self.protected_label = str(spec.get("protected_label", "pedestrian(s)"))
        self.min_protected = int(spec.get("min_protected", 1))
        self.min_move = float(spec.get("min_movement", 0.03))  # normalised distance within `window`
        self.window = float(spec.get("window", 1.0))
        self.seconds = float(spec.get("seconds", 0.3))
        self.rearm = bool(spec.get("rearm", False))  # fire again for the same track after it leaves

    def protected_now(self):
        return sum(1 for t in self.eng.tracks.values()
                   if t.present and t.label in self.protected and t.zin.get(self.zone))

    def evaluate(self, now):
        out, key, skey = [], ("zc", self.name), ("zc_since", self.name)
        prot = self.protected_now()
        for v in self.eng.tracks.values():
            if not self.match(v):
                continue
            inside = v.zin.get(self.zone)
            if v.flags.get(key):
                if self.rearm and not inside:
                    v.flags[key] = False
                continue
            if prot < self.min_protected or not inside:
                v.flags.pop(skey, None)
                continue
            if self.min_move > 0:
                old = next(((x, y) for ts, x, y in v.hist if now - ts <= self.window), None)
                _, cx, cy = v.hist[-1]
                if old is None or math.hypot(cx - old[0], cy - old[1]) < self.min_move:
                    v.flags.pop(skey, None)  # stopped / waiting = yielding, fine
                    continue
            since = v.flags.setdefault(skey, now)
            if now - since >= self.seconds:
                ev = self.event(now, {"track_id": v.tid, "class": v.label, "protected": prot,
                                      "protected_label": self.protected_label})
                if ev:
                    v.flags[key] = True
                    out.append(ev)
        return out

    def kpi(self):
        k = super().kpi()
        k.update(protected_now=self.protected_now())
        return k


RULES = {
    "zone_enter": ZoneDwell, "zone_dwell": ZoneDwell, "line_cross": LineCross,
    "wrong_way": WrongWay, "count_threshold": CountThreshold, "crowd": CountThreshold,
    "group_on_vehicle": GroupOnVehicle, "triple_riding": GroupOnVehicle,
    "unattended": Unattended, "slot_occupancy": SlotOccupancy, "fall": Fall,
    "danger_zone": DangerZone, "keypoint_zone": DangerZone,
    "zone_conflict": ZoneConflict, "yield_violation": ZoneConflict,
}


# --------------------------------------------------------------------------- sinks
class Sink:
    def send(self, ev):
        pass

    def on_level(self, level, rule, msg):
        pass


class ConsoleSink(Sink):
    C = {"critical": "\033[91m", "warning": "\033[93m", "info": "\033[96m", "clear": "\033[92m"}

    def __init__(self, color=True):
        self.color = color and sys.stdout.isatty()

    def _c(self, sev):
        return self.C.get(sev, "") if self.color else ""

    def send(self, ev):
        end = "\033[0m" if self.color else ""
        print(f"{self._c(ev['severity'])}[{ev['time']}] {ev['severity'].upper():8} "
              f"{ev['rule']}: {ev['message']}{end}", flush=True)

    def on_level(self, level, rule, msg):
        print(f"    >> ACTUATOR {LEVEL_NAME.get(level, level)}"
              f"{' (' + rule + ')' if rule else ''}", flush=True)


class JsonlSink(Sink):
    def __init__(self, path):
        self.path = path

    def send(self, ev):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(ev) + "\n")


def _mqtt_client(mqtt):
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except (AttributeError, TypeError):
        return mqtt.Client()


class MqttSink(Sink):
    def __init__(self, cfg):
        import paho.mqtt.client as mqtt  # pip install paho-mqtt
        self.prefix = cfg.get("topic_prefix", "alerts")
        self.c = _mqtt_client(mqtt)
        if cfg.get("username"):
            self.c.username_pw_set(cfg["username"], cfg.get("password"))
        ready = threading.Event()
        self.c.on_connect = lambda *a: ready.set()
        self.c.connect(cfg.get("host", "localhost"), int(cfg.get("port", 1883)), 60)
        self.c.loop_start()
        if not ready.wait(5):
            raise ConnectionError("MQTT broker did not answer (is mosquitto running?)")

    def send(self, ev):
        self.c.publish(f"{self.prefix}/{ev['rule']}", json.dumps(ev), qos=0)

    def on_level(self, level, rule, msg):
        self.c.publish(f"{self.prefix}/state", json.dumps(
            {"level": level, "state": LEVEL_NAME.get(level), "rule": rule, "message": msg,
             "ts": time.time()}), qos=1, retain=True)


class TelegramSink(Sink):
    """Create a bot with @BotFather, send it any message, then get your chat id from
    https://api.telegram.org/bot<TOKEN>/getUpdates . Export TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID."""

    ICON = {"critical": "\U0001F6A8", "warning": "\u26A0\uFE0F", "clear": "\u2705", "info": "\u2139\uFE0F"}

    def __init__(self, cfg):
        self.token = os.environ.get("TELEGRAM_BOT_TOKEN") or cfg.get("bot_token")
        self.chat = os.environ.get("TELEGRAM_CHAT_ID") or cfg.get("chat_id")
        if not (self.token and self.chat):
            raise ValueError("set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID (env vars)")
        self.min_interval = float(cfg.get("min_interval", 15))
        self.sev = set(cfg.get("severities", ["warning", "critical"]))
        self.prefix = cfg.get("prefix", "")
        self.last = {}
        self.q = queue.Queue()
        threading.Thread(target=self._run, daemon=True).start()

    def send(self, ev):
        if ev["severity"] not in self.sev:
            return
        t = time.time()
        if t - self.last.get(ev["rule"], 0) < self.min_interval:
            return
        self.last[ev["rule"]] = t
        self.q.put(f"{self.ICON.get(ev['severity'], '')} {self.prefix}{ev['message']}\n"
                   f"{ev['time']} | rule: {ev['rule']}")

    def _run(self):
        while True:
            text = self.q.get()
            data = urllib.parse.urlencode({"chat_id": self.chat, "text": text}).encode()
            try:
                urllib.request.urlopen(f"https://api.telegram.org/bot{self.token}/sendMessage",
                                       data=data, timeout=10).read()
            except Exception as e:  # noqa: BLE001
                print(f"[telegram] {e}", file=sys.stderr)


class SerialSink(Sink):
    """Drives the ESP32 firmware from firmgen/ESP32_alert_PRD.md over USB serial.
    Protocol: 'ALERT <2|3> <rule>' / 'CLEAR' on every actuator change; once per second it re-sends
    the current 'ALERT <lvl> <rule>' (or 'PING' when clear) as keep-alive."""

    def __init__(self, cfg):
        import serial  # pip install pyserial
        self.ser = serial.Serial(cfg.get("port", "COM3"), int(cfg.get("baud", 115200)), timeout=0)
        self.lock = threading.Lock()
        self.level, self.rule = 0, ""
        threading.Thread(target=self._loop, daemon=True).start()

    def _write(self, line):
        with self.lock:
            self.ser.write((line + "\n").encode())

    def on_level(self, level, rule, msg):
        self.level, self.rule = level, rule
        self._write(f"ALERT {level} {rule}" if level >= 2 else "CLEAR")

    def _loop(self):
        while True:
            time.sleep(1.0)
            try:
                # keep-alive that also re-asserts the current state (board fails safe after 3 s silence)
                self._write(f"ALERT {self.level} {self.rule}" if self.level >= 2 else "PING")
                with self.lock:
                    data = self.ser.read(1024)
                if data:
                    sys.stderr.write("[esp32] " + data.decode(errors="replace"))
            except Exception as e:  # noqa: BLE001
                print(f"[serial] {e}", file=sys.stderr)


# --------------------------------------------------------------------------- engine
class Engine:
    def __init__(self, cfg, state_dir, sinks, source_desc=""):
        self.cfg = cfg
        self.parser = Parser(cfg)
        self.tracker = IoUTracker()
        self.anchor_mode = cfg.get("anchor", "bottom_center")
        self.min_conf = float(cfg.get("min_confidence", 0.0))
        self.time_source = cfg.get("time_source", "auto")  # auto | message | wall
        self.stale = float(cfg.get("stale_after", 0.7))
        self.forget = float(cfg.get("forget_after", 8.0))
        self.hold = float((cfg.get("actuator") or {}).get("hold_seconds", 8.0))
        self.zones = {n: [tuple(map(float, p)) for p in pts]
                      for n, pts in (cfg.get("zones") or {}).items()}
        self.geom = {"lines": cfg.get("lines") or {}, "directions": cfg.get("directions") or {}}
        self.tracks = {}
        self.sinks = sinks
        self.source_desc = source_desc
        self.events = deque(maxlen=200)
        self.alert_walls = deque(maxlen=20000)
        self.active = {}
        self.level, self.level_rule, self.level_msg = 0, "", "All clear"
        self.stats = {"messages": 0, "frames": 0, "detections": 0, "started": time.time(),
                      "last_msg": None}
        self.now = None
        self.rate, self._rate_t, self._rate_n = 0.0, time.time(), 0
        self._last_write = 0.0
        os.makedirs(state_dir, exist_ok=True)
        self.state_path = os.path.join(state_dir, "state.json")
        self.rules = []
        for spec in cfg.get("rules") or []:
            cls = RULES.get(spec.get("type"))
            if cls is None:
                raise SystemExit(f"[config] unknown rule type '{spec.get('type')}'. "
                                 f"Use one of: {', '.join(sorted(RULES))}")
            self.rules.append(cls(spec, self))

    def get_geom(self, kind, ref, rule):
        if isinstance(ref, str):
            if ref not in self.geom[kind]:
                raise SystemExit(f"[config] rule '{rule}': {kind[:-1]} '{ref}' is not defined")
            ref = self.geom[kind][ref]
        if not (isinstance(ref, (list, tuple)) and len(ref) == 2):
            raise SystemExit(f"[config] rule '{rule}': needs a 2-point {kind[:-1]}")
        return tuple(tuple(map(float, p)) for p in ref)

    # -- input
    def handle(self, raw):
        self.stats["messages"] += 1
        self.stats["last_msg"] = time.time()
        for f in self.parser.parse(raw):
            self.process(f)
        self.write_state()

    def process(self, f):
        wall = time.time()
        now = f.ts if (f.ts is not None and self.time_source != "wall") else wall
        if self.now is not None and now < self.now - 5:  # video looped / clock jumped back
            self.tracks.clear()
        self.now = now
        self.stats["frames"] += 1
        dets = [d for d in f.dets if d.conf is None or d.conf >= self.min_conf]
        self.stats["detections"] += len(dets)
        for d in dets:
            if d.tid is not None and (d.tid < 0 or d.tid >= 2 ** 63):
                d.tid = None
        if any(d.tid is None for d in dets):
            self.tracker.assign(f.src, dets, now)
        for d in dets:
            key = (f.src, d.label, d.tid)
            t = self.tracks.get(key)
            if t is None:
                self.tracks[key] = Track(key, d, now, self.anchor_mode)
            else:
                t.update(d, now)
        for key in list(self.tracks):
            t = self.tracks[key]
            age = now - t.last
            if age > self.forget:
                del self.tracks[key]
                continue
            t.present = age <= self.stale
            if not t.present:
                for z in t.zin:
                    t.zin[z] = False
                continue
            ax, ay = t.anchor()
            for zn, poly in self.zones.items():
                inside = point_in_poly(ax, ay, poly)
                if inside and not t.zin.get(zn):
                    t.zsince[zn] = now
                t.zin[zn] = inside
        for r in self.rules:
            for ev in r.evaluate(now) or []:
                self.emit(ev)
        self.update_level()

    # -- output
    def emit(self, ev):
        self.events.appendleft(ev)
        if ev["severity"] in ("warning", "critical"):
            self.alert_walls.append(time.time())
        sev = ev["severity"]
        if sev == "clear":
            self.active.pop(ev["rule"], None)
        elif LEVEL.get(sev, 0) >= 2:
            self.active[ev["rule"]] = (LEVEL[sev], time.time(), bool(ev.get("stateful")),
                                       ev["message"])
        for s in self.sinks:
            try:
                s.send(ev)
            except Exception as e:  # noqa: BLE001
                print(f"[sink {type(s).__name__}] {e}", file=sys.stderr)

    def update_level(self):
        wall = time.time()
        for r, (_lvl, t, stateful, _m) in list(self.active.items()):
            if not stateful and wall - t > self.hold:
                del self.active[r]
        if self.active:
            r, (lvl, _t, _s, msg) = max(self.active.items(), key=lambda kv: (kv[1][0], kv[1][1]))
        else:
            r, lvl, msg = "", 0, "All clear"
        if lvl != self.level or r != self.level_rule:
            self.level, self.level_rule, self.level_msg = lvl, r, msg
            for s in self.sinks:
                try:
                    s.on_level(lvl, r, msg)
                except Exception as e:  # noqa: BLE001
                    print(f"[sink {type(s).__name__}] {e}", file=sys.stderr)

    def snapshot(self):
        wall = time.time()
        zones = {}
        for zn in self.zones:
            by = {}
            for t in self.tracks.values():
                if t.present and t.zin.get(zn):
                    by[t.label] = by.get(t.label, 0) + 1
            zones[zn] = {"count": sum(by.values()), "by_class": by}
        classes = {}
        for t in self.tracks.values():
            if t.present:
                classes[t.label] = classes.get(t.label, 0) + 1
        per_min = [0] * 30
        for w in self.alert_walls:
            age = int((wall - w) // 60)
            if 0 <= age < 30:
                per_min[29 - age] += 1
        lm = self.stats["last_msg"]
        return {
            "project": self.cfg.get("project", "PipeGen Action Engine"),
            "subtitle": self.cfg.get("subtitle", ""),
            "perf": self.cfg.get("perf") or {},
            "source": self.source_desc,
            "updated": wall,
            "uptime_s": round(wall - self.stats["started"]),
            "messages": self.stats["messages"],
            "frames": self.stats["frames"],
            "detections": self.stats["detections"],
            "msg_rate": round(self.rate, 1),
            "last_message_age_s": None if lm is None else round(wall - lm, 1),
            "active_tracks": sum(1 for t in self.tracks.values() if t.present),
            "classes_now": classes,
            "zones": zones,
            "rules": {r.name: r.kpi() for r in self.rules},
            "actuator": {"level": self.level, "state": LEVEL_NAME.get(self.level, ""),
                         "rule": self.level_rule, "message": self.level_msg},
            "alerts_total": sum(r.fired for r in self.rules),
            "alerts_per_min": per_min,
            "events": list(self.events)[:60],
            "active_objects": [
                {
                    "id": t.tid,
                    "label": t.label,
                    "box": [round(c, 4) for c in t.box] if t.box else None,
                    "conf": round(t.conf, 2) if t.conf else None,
                    "zones": [zn for zn, val in t.zin.items() if val],
                }
                for t in self.tracks.values() if t.present
            ],
            "zones_config": self.zones,
            "lines_config": self.geom.get("lines", {}),
        }

    def write_state(self, force=False):
        wall = time.time()
        if not force and wall - self._last_write < 0.25:
            return
        dtr = wall - self._rate_t
        if dtr >= 1.0:
            inst = (self.stats["messages"] - self._rate_n) / dtr
            self.rate = inst if self.rate == 0 else 0.6 * inst + 0.4 * self.rate
            self._rate_t, self._rate_n = wall, self.stats["messages"]
        self._last_write = wall
        tmp = self.state_path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.snapshot(), f)
            for _ in range(5):
                try:
                    os.replace(tmp, self.state_path)
                    break
                except OSError:
                    time.sleep(0.03)
        except Exception:
            pass


# --------------------------------------------------------------------------- sources
def start_source(spec, q, follow=True):
    """Start a background reader that puts raw messages into q (None = end of input)."""
    if spec in ("stdin", "-"):
        def run():
            for line in sys.stdin:
                q.put(line)
            q.put(None)
        threading.Thread(target=run, daemon=True).start()
        return "stdin"

    if spec.startswith("mqtt://"):
        import paho.mqtt.client as mqtt  # pip install paho-mqtt
        rest = spec[len("mqtt://"):]
        hostport, _, topic = rest.partition("/")
        topic = topic or "#"
        auth = None
        if "@" in hostport:
            auth, hostport = hostport.rsplit("@", 1)
        host, _, port = hostport.partition(":")
        c = _mqtt_client(mqtt)
        if auth:
            u, _, p = auth.partition(":")
            c.username_pw_set(u, p or None)

        def on_connect(client, userdata, *args):
            client.subscribe(topic)
            print(f"[mqtt] connected to {host or 'localhost'}:{port or 1883}, subscribed '{topic}'",
                  flush=True)

        c.on_connect = on_connect
        c.on_message = lambda client, userdata, msg: q.put(msg.payload)
        c.connect(host or "localhost", int(port or 1883), 60)
        c.loop_start()
        return f"MQTT {host or 'localhost'}:{port or 1883} '{topic}'"

    if spec.startswith("file:"):
        path = os.path.expanduser(spec[5:])

        def run():
            while not os.path.exists(path):
                time.sleep(0.5)
            if not follow:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    txt = fh.read()
                try:
                    q.put(json.loads(txt))
                except json.JSONDecodeError:
                    for line in txt.splitlines():
                        q.put(line)
                q.put(None)
                return
            with open(path, encoding="utf-8", errors="replace") as fh:
                buf = ""
                while True:
                    chunk = fh.readline()
                    if not chunk:
                        time.sleep(0.05)
                        continue
                    buf += chunk
                    if buf.endswith("\n"):
                        q.put(buf)
                        buf = ""
        threading.Thread(target=run, daemon=True).start()
        return f"file {path}"

    if spec.startswith("dir:"):
        path = os.path.expanduser(spec[4:])

        def mtime(p):
            try:
                return os.path.getmtime(p)
            except OSError:
                return 0.0

        def run():
            seen = set()
            while True:
                files = glob.glob(os.path.join(path, "*.json")) + \
                    glob.glob(os.path.join(path, "*.jsonl"))
                for p in sorted(files, key=lambda p: (mtime(p), p)):
                    if p in seen:
                        continue
                    try:
                        s1 = os.path.getsize(p)
                        time.sleep(0.02)
                        if os.path.getsize(p) != s1:
                            continue  # still being written
                        with open(p, encoding="utf-8", errors="replace") as fh:
                            txt = fh.read()
                    except OSError:
                        continue
                    seen.add(p)
                    try:
                        q.put(json.loads(txt))
                    except json.JSONDecodeError:
                        for line in txt.splitlines():
                            q.put(line)
                if not follow:
                    q.put(None)
                    return
                time.sleep(0.2)
        threading.Thread(target=run, daemon=True).start()
        return f"dir {path}"

    raise SystemExit(f"Unknown --source '{spec}'. Use stdin | mqtt://host:1883/topic | "
                     f"file:/path.jsonl | dir:/path")


# --------------------------------------------------------------------------- main
def load_config(path):
    with open(path, encoding="utf-8") as f:
        txt = f.read()
    if path.endswith(".json"):
        return json.loads(txt)
    if yaml is None:
        raise SystemExit("PyYAML missing: pip install pyyaml   (or use a .json config)")
    return yaml.safe_load(txt) or {}


def build_sinks(cfg, state_dir, quiet):
    sc = cfg.get("sinks") or {}
    sinks = []
    if sc.get("console", True) and not quiet:
        sinks.append(ConsoleSink())
    if sc.get("jsonl", True):
        sinks.append(JsonlSink(os.path.join(state_dir, "events.jsonl")))
    for name, cls in (("mqtt", MqttSink), ("telegram", TelegramSink), ("serial", SerialSink)):
        c = sc.get(name) or {}
        if c.get("enabled"):
            try:
                sinks.append(cls(c))
                print(f"[sink] {name} enabled", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"[sink] {name} DISABLED: {e}", file=sys.stderr)
    return sinks


def main():
    ap = argparse.ArgumentParser(description="PipeGen Action Engine")
    ap.add_argument("-c", "--config", required=True, help="YAML/JSON config (see configs/)")
    ap.add_argument("--source", help="stdin | mqtt://host:1883/topic | file:/path.jsonl | dir:/path "
                                     "(default: 'source' in config, else stdin)")
    ap.add_argument("--state-dir", default="run", help="where state.json / events.jsonl go")
    ap.add_argument("--no-follow", action="store_true", help="file:/dir: read once and exit")
    ap.add_argument("--print-raw", type=int, default=0, metavar="N",
                    help="print the first N raw messages (to learn PipeGen's JSON format)")
    ap.add_argument("--quiet", action="store_true", help="no console event lines")
    args = ap.parse_args()

    cfg = load_config(args.config)
    os.makedirs(args.state_dir, exist_ok=True)
    open(os.path.join(args.state_dir, "events.jsonl"), "w").close()
    spec = args.source or cfg.get("source") or "stdin"
    q = queue.Queue()
    desc = start_source(spec, q, follow=not args.no_follow)
    eng = Engine(cfg, args.state_dir, build_sinks(cfg, args.state_dir, args.quiet), desc)
    print(f"[engine] {cfg.get('project', '')} | source: {desc} | zones: {', '.join(eng.zones)} | "
          f"rules: {', '.join(r.name for r in eng.rules)}", flush=True)
    printed = 0
    try:
        while True:
            try:
                item = q.get(timeout=0.5)
            except queue.Empty:
                eng.update_level()
                eng.write_state(force=True)
                continue
            if item is None:
                break
            if printed < args.print_raw:
                printed += 1
                txt = item if isinstance(item, str) else (
                    item.decode("utf-8", "replace") if isinstance(item, (bytes, bytearray))
                    else json.dumps(item))
                print(f"--- raw message {printed} ---\n{txt.strip()[:2000]}", flush=True)
            eng.handle(item)
    except KeyboardInterrupt:
        pass
    finally:
        eng.write_state(force=True)
        s = eng.stats
        print(f"\n[engine] done: {s['messages']} messages, {s['frames']} frames, "
              f"{s['detections']} detections", flush=True)
        for r in eng.rules:
            extra = ""
            if isinstance(r, LineCross):
                extra = f" (L2R {r.total('L2R')}, R2L {r.total('R2L')})"
            print(f"  - {r.name:28} {r.type:17} fired {r.fired}{extra}", flush=True)


if __name__ == "__main__":
    main()
