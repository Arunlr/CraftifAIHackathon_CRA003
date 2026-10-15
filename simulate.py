#!/usr/bin/env python3
"""
simulate.py - fake PipeGen / DeepStream detections, so you can build and demo the
action layer (rules, dashboard, Telegram, ESP32) BEFORE PipeGen is installed.

Default output = DeepStream msgconv "minimal" JSON, one message per frame (the same
shape a DeepStream app publishes over MQTT). --format generic = per-frame JSON with
bbox dicts (+ pose keypoints for the 'press' scenario).

  python simulate.py elephant | python action_engine.py -c configs/elephant_track.yaml
  python simulate.py traffic --loop | python action_engine.py -c configs/traffic_sentinel.yaml
  python simulate.py crowd --mqtt localhost:1883 --topic pipegen/detections --loop
  python simulate.py parking --fast > parking.jsonl

Scenarios: elephant, traffic, parking, crowd, bag, fall, press, zebra, dogs
"""
import argparse
import datetime as dt
import json
import random
import sys
import time

W, H = 1920, 1080


class Obj:
    """Keyframed object. keys = [(t, x, y, w, h), ...] in 0..1 coords.
    (x, y) is the bottom-centre of the box (or the centre if anchor='center')."""

    def __init__(self, tid, label, keys, anchor="bottom", kps=None):
        self.tid, self.label, self.keys = tid, label, sorted(keys)
        self.anchor, self.kps = anchor, kps

    def state(self, t):
        k = self.keys
        if t < k[0][0] or t > k[-1][0]:
            return None
        for a, b in zip(k, k[1:]):
            if a[0] <= t <= b[0]:
                f = 0.0 if b[0] == a[0] else (t - a[0]) / (b[0] - a[0])
                return tuple(a[i] + (b[i] - a[i]) * f for i in range(1, 5))
        return tuple(k[-1][1:5])

    def box(self, t, jitter):
        s = self.state(t)
        if s is None:
            return None
        x, y, w, h = s
        jx, jy = random.uniform(-jitter, jitter), random.uniform(-jitter, jitter)
        if self.anchor == "center":
            return (x - w / 2 + jx, y - h / 2 + jy, x + w / 2 + jx, y + h / 2 + jy)
        return (x - w / 2 + jx, y - h + jy, x + w / 2 + jx, y + jy)


def persp(y, bw, bh, a=0.35, b=1.0):
    s = a + b * y
    return (bw * s, bh * s)


def mk(tid, label, pts, bw, bh, a=0.35, b=1.0):
    return Obj(tid, label, [(t, x, y) + persp(y, bw, bh, a, b) for t, x, y in pts])


# --------------------------------------------------------------------------- scenarios
def sc_elephant():
    e = dict(a=0.55, b=0.75)
    return [
        mk(1, "elephant", [(1, .12, .40), (8, .38, .52), (13, .44, .68), (20, .47, .70),
                           (28, .66, .97)], .13, .21, **e),
        mk(2, "elephant", [(3, .06, .42), (10, .32, .54), (15, .38, .70), (22, .41, .71),
                           (30, .60, .98)], .08, .12, **e),
        mk(3, "elephant", [(33, .92, .97), (39, .80, .72), (43, .78, .66), (50, .70, .42),
                           (56, .62, .30)], .13, .21, **e),
        mk(4, "person", [(44, 1.02, .62), (50, .55, .66), (55, .53, .66), (60, .30, .69)],
           .03, .12, **e),
        mk(5, "car", [(5, 1.08, .93), (9, -.08, .93)], .12, .09, **e),
    ], 62


def lane_x(f, y):
    t = (y - 0.22) / 0.78
    xl, xr = 0.25 - 0.22 * t, 0.75 + 0.22 * t
    return xl + f * (xr - xl)


def vehicle(tid, label, pts, bw, bh):
    """pts = [(t, lane_fraction, y)]"""
    return Obj(tid, label, [(t, lane_x(f, y), y) + persp(y, bw, bh) for t, f, y in pts])


def riders(moto, offsets, first_tid):
    out = []
    for i, off in enumerate(offsets):
        keys = [(t, x + off * w, y - 0.15 * h, 0.7 * w, 1.7 * h) for t, x, y, w, h in moto.keys]
        out.append(Obj(first_tid + i, "person", keys))
    return out


def sc_traffic():
    o = []
    for i, (t0, f) in enumerate([(0, .45), (3, .70), (6, .88), (9, .55), (15, .80), (22, .50),
                                 (30, .68), (38, .86)]):
        o.append(vehicle(10 + i, "car", [(t0, f, .24), (t0 + 7, f, 1.06)], .075, .07))
    o.append(vehicle(20, "truck", [(12, .62, .24), (21, .62, 1.06)], .09, .10))
    for i, (t0, f) in enumerate([(2, .36), (11, .76), (25, .33), (33, .74)]):
        m = vehicle(70 + i, "motorcycle", [(t0, f, .24), (t0 + 6, f, 1.06)], .028, .05)
        o += [m] + riders(m, [0.0], 170 + i)
    o.append(vehicle(30, "bus", [(4, .09, .24), (12, .10, 1.06)], .10, .16))
    # car that sits in the BMTC bus lane
    o.append(vehicle(31, "car", [(14, .32, .30), (16, .10, .45), (22, .10, .62), (24, .30, .75),
                                 (27, .32, 1.06)], .075, .07))
    # wrong-way motorcycle
    m = vehicle(40, "motorcycle", [(20, .70, 1.02), (27, .70, .28)], .028, .05)
    o += [m] + riders(m, [0.0], 41)
    # triple riding
    m = vehicle(50, "motorcycle", [(28, .42, .24), (35, .42, 1.06)], .028, .05)
    o += [m] + riders(m, [-0.22, 0.0, 0.22], 51)
    # footpath riding
    fx = lambda y: 0.77 + 0.22 * (y - 0.22) / 0.78 + 0.03  # noqa: E731
    m = Obj(60, "motorcycle", [(t, fx(y), y) + persp(y, .028, .05) for t, y in [(36, .30), (41, .80)]])
    o += [m] + riders(m, [0.0], 61)
    return o, 46


def sc_parking():
    cx = {"1": .185, "2": .395, "3": .605, "4": .815}
    cy = {"A": .26, "B": .74}
    size = (.12, .19)
    o, sp = [], 0.35
    leave = {"A1": 34, "B2": 40}
    for i, (slot, t0) in enumerate([("A1", 1), ("B2", 3), ("A3", 6), ("B4", 9), ("A2", 12),
                                    ("B1", 15), ("A4", 18), ("B3", 22)]):
        x, y = cx[slot[1]], cy[slot[0]]
        ta = t0 + (1.06 - x) / sp
        keys = [(t0, 1.06, .5), (ta, x, .5), (ta + 1.2, x, y)]
        if slot in leave:
            tl = leave[slot]
            keys += [(tl, x, y), (tl + 1.2, x, .5), (tl + 1.2 + (x + .06) / sp, -.06, .5)]
        else:
            keys += [(70, x, y)]
        o.append(Obj(1 + i, "car", [k + size for k in keys], anchor="center"))
    # car stopping in the fire lane / aisle
    o.append(Obj(20, "car", [k + size for k in [(46, 1.06, .5), (47.6, .5, .5), (60, .5, .5),
                                                 (62, -.06, .5)]], anchor="center"))
    return o, 66


def sc_crowd():
    rnd = random.Random(42)
    o = []
    arrivals = sorted(rnd.uniform(0, 38) for _ in range(46))
    for i, ta in enumerate(arrivals):
        x0, xq, yq = rnd.uniform(.28, .72), rnd.uniform(.33, .67), rnd.uniform(.52, .90)
        tq = ta + rnd.uniform(4, 6)
        tdep = max(tq + 2, 42 + 0.5 * i + rnd.uniform(0, 1.5))
        tgone = tdep + rnd.uniform(3, 4.5)
        o.append(mk(100 + i, "person", [(ta, x0, 1.06), (tq, xq, yq),
                                        (tdep, xq + rnd.uniform(-.02, .02), yq),
                                        (tgone, .5 + (xq - .5) * .4, .30)], .035, .13))
    for j, t0 in enumerate([34, 36.5, 39]):  # people pushing against the flow
        x = .40 + .10 * j
        o.append(mk(200 + j, "person", [(t0, x, .47), (t0 + 5, x + .02, 1.06)], .035, .13))
    return o, 72


def sc_bag():
    return [
        mk(1, "person", [(0, -.05, .70), (7, .45, .72), (10, .45, .72), (17, 1.05, .55)], .04, .16),
        mk(2, "suitcase", [(0, -.02, .715), (7, .49, .735), (60, .49, .735)], .025, .05),
        mk(3, "person", [(20, 1.05, .80), (27, -.05, .78)], .04, .16),
        mk(4, "person", [(30, -.05, .60), (38, 1.05, .62)], .04, .16),
        mk(5, "backpack", [(30, -.05, .55), (38, 1.05, .57)], .02, .035),
    ], 52


def sc_fall():
    up, lying = (.07, .33), (.30, .11)
    keys = [(0, .20, .80) + up, (6, .50, .82) + up, (6.6, .53, .86) + lying, (20, .53, .86) + lying,
            (21.5, .52, .83) + up, (28, .95, .80) + up]
    return [Obj(1, "person", keys)], 30


def sc_press():
    base = [(.50, .30), (.49, .29), (.51, .29), (.48, .30), (.52, .30), (.44, .40), (.56, .40),
            (.40, .52), (.60, .52), (.36, .62), (.64, .62), (.46, .65), (.54, .65), (.46, .80),
            (.54, .80), (.46, .95), (.54, .95)]

    def kps(t):
        cyc = t % 10.0
        rx, ry = base[10]
        if 4.0 <= cyc <= 6.0:  # right hand reaches into the die area
            f = min(1.0, (cyc - 4.0) / 0.4) if cyc < 5.6 else max(0.0, (6.0 - cyc) / 0.4)
            rx, ry = rx + (.52 - rx) * f, ry + (.52 - ry) * f
        pts = [[x * W, y * H, 0.9] for x, y in base]
        pts[10] = [rx * W, ry * H, 0.9]
        return pts

    return [Obj(1, "person", [(0, .5, .98, .24, .76), (40, .5, .98, .24, .76)], kps=kps)], 40


def sc_zebra():
    """Zebra crossing (band y=.56-.66). Car 10 passes an empty crossing; car 11 and truck 20 STOP
    for pedestrians (yield); motorcycle 70, car 12 and motorcycle 71 drive through while people are
    on the crossing (3 violations)."""
    o = [vehicle(10, "car", [(1, .60, .24), (7, .60, 1.06)], .075, .07)]
    for i, (t0, y, dur) in enumerate([(8, .61, 9), (8.6, .63, 9.5), (9.3, .60, 8.5)]):
        o.append(mk(100 + i, "person", [(t0, .03, y), (t0 + dur, .97, y)], .03, .12))
    o.append(vehicle(11, "car", [(5, .35, .24), (8.5, .35, .52), (18.5, .35, .52), (22, .35, 1.06)],
                     .075, .07))  # waits at the stop line -> yields
    o.append(vehicle(70, "motorcycle", [(9, .78, .24), (14, .78, 1.06)], .028, .05))
    o.append(vehicle(12, "car", [(10.5, .55, .24), (16.5, .55, 1.06)], .075, .07))
    for i, (t0, y, dur) in enumerate([(24, .62, 8), (24.8, .60, 8.5)]):
        o.append(mk(110 + i, "person", [(t0, .97, y), (t0 + dur, .03, y)], .03, .12))
    o.append(vehicle(20, "truck", [(21, .65, .24), (24.5, .65, .50), (33.5, .65, .50), (38, .65, 1.06)],
                     .09, .10))  # yields
    o.append(vehicle(71, "motorcycle", [(25, .30, .24), (30, .30, 1.06)], .028, .05))
    return o, 40


def sc_dogs():
    """School gate at dismissal. A lone dog naps by the wall; children stream out from t=8; a pack of
    3 more dogs arrives at t=16 and mixes with the children; the pack leaves at t=34."""
    rnd = random.Random(7)
    o = [mk(1, "dog", [(0, .12, .80), (50, .13, .80)], .06, .05)]
    for i in range(18):
        ta = 8 + i * 1.2 + rnd.uniform(0, .6)
        x0 = rnd.uniform(.42, .58)
        side_x = rnd.choice([-.05, 1.05])
        o.append(mk(100 + i, "person", [(ta, x0, .45), (ta + 3, x0 + rnd.uniform(-.08, .08), .66),
                                        (ta + 9, side_x, .74)], .025, .09))
    for j, (x, y) in enumerate([(.45, .62), (.55, .66), (.50, .70)]):
        o.append(mk(10 + j, "dog", [(16 + j, 1.05, .85), (21 + j, x, y), (30 + j, x + .03, y + .01),
                                    (34 + j, -.05, .90)], .06, .05))
    return o, 46


SCENARIOS = {"elephant": sc_elephant, "traffic": sc_traffic, "parking": sc_parking,
             "crowd": sc_crowd, "bag": sc_bag, "fall": sc_fall, "press": sc_press,
             "zebra": sc_zebra, "dogs": sc_dogs}


# --------------------------------------------------------------------------- output
def iso(t):
    return dt.datetime.fromtimestamp(t, dt.timezone.utc).isoformat(timespec="milliseconds") \
        .replace("+00:00", "Z")


def frame_msg(fmt, n, t_abs, cam, items):
    if fmt == "generic":
        objs = []
        for tid, label, (x1, y1, x2, y2), conf, kps in items:
            o = {"track_id": tid, "label": label, "confidence": round(conf, 3),
                 "bbox": {"left": round(x1 * W, 1), "top": round(y1 * H, 1),
                          "width": round((x2 - x1) * W, 1), "height": round((y2 - y1) * H, 1)}}
            if kps:
                o["keypoints"] = [[round(a, 1), round(b, 1), c] for a, b, c in kps]
            objs.append(o)
        return {"frame_num": n, "timestamp": round(t_abs, 3), "source_id": cam,
                "width": W, "height": H, "objects": objs}
    return {"version": "4.0", "id": str(n), "@timestamp": iso(t_abs), "sensorId": cam,
            "objects": [f"{tid}|{x1 * W:.1f}|{y1 * H:.1f}|{x2 * W:.1f}|{y2 * H:.1f}|{label}"
                        for tid, label, (x1, y1, x2, y2), conf, kps in items]}


def main():
    ap = argparse.ArgumentParser(description="Fake PipeGen detections")
    ap.add_argument("scenario", choices=sorted(SCENARIOS))
    ap.add_argument("--fps", type=float, default=10)
    ap.add_argument("--fast", action="store_true", help="no sleeping (timestamps still advance)")
    ap.add_argument("--loop", action="store_true", help="repeat forever")
    ap.add_argument("--duration", type=float, help="override scenario length (s)")
    ap.add_argument("--format", choices=["ds", "generic"], help="default: ds (press: generic)")
    ap.add_argument("--mqtt", metavar="HOST:PORT", help="publish to MQTT instead of stdout")
    ap.add_argument("--topic", default="pipegen/detections")
    ap.add_argument("--cam", default="cam0")
    ap.add_argument("--drop", type=float, default=0.03, help="detection dropout probability")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    random.seed(args.seed)
    fmt = args.format or ("generic" if args.scenario == "press" else "ds")

    pub = None
    if args.mqtt:
        import paho.mqtt.client as mqtt
        host, _, port = args.mqtt.partition(":")
        try:
            pub = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        except (AttributeError, TypeError):
            pub = mqtt.Client()
        import threading
        ready = threading.Event()
        pub.on_connect = lambda *a: ready.set()
        pub.connect(host or "localhost", int(port or 1883), 60)
        pub.loop_start()
        if not ready.wait(5):  # paho drops QoS-0 publishes sent before CONNACK
            sys.exit(f"could not connect to MQTT broker {args.mqtt}")
        print(f"publishing '{args.scenario}' to mqtt://{args.mqtt}/{args.topic}", file=sys.stderr)

    t0 = time.time()
    dt_frame = 1.0 / args.fps
    last_info = None
    n, loop, wall_start = 0, 0, time.time()
    try:
        while True:
            objs, dur = SCENARIOS[args.scenario]()
            dur = args.duration or dur
            t = 0.0
            while t <= dur:
                items = []
                for o in objs:
                    b = o.box(t, 0.0015)
                    if b is None or random.random() < args.drop:
                        continue
                    if b[2] < 0 or b[0] > 1 or b[3] < 0 or b[1] > 1:
                        continue  # fully outside the frame
                    kps = o.kps(t) if o.kps else None
                    items.append((o.tid + 1000 * loop, o.label, b, random.uniform(.55, .95), kps))
                t_abs = t0 + loop * (dur + 1) + t
                msg = json.dumps(frame_msg(fmt, n, t_abs, args.cam, items))
                if pub:
                    last_info = pub.publish(args.topic, msg)
                else:
                    sys.stdout.write(msg + "\n")
                    sys.stdout.flush()
                n += 1
                t += dt_frame
                if not args.fast:
                    sleep = wall_start + n * dt_frame - time.time()
                    if sleep > 0:
                        time.sleep(sleep)
            loop += 1
            if not args.loop:
                break
    except (KeyboardInterrupt, BrokenPipeError):
        pass
    finally:
        if pub:
            if last_info is not None:
                try:
                    last_info.wait_for_publish(timeout=15)  # flush queued messages
                except (RuntimeError, ValueError):
                    pass
            time.sleep(1.5)  # let the broker route everything before we hang up
            pub.disconnect()
            pub.loop_stop()


if __name__ == "__main__":
    main()
