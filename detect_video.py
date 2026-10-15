#!/usr/bin/env python3
"""
detect_video.py - Real-Time AI Vision Pipeline for Gaja-Rakshak.

Performs genuine YOLOv8 neural network inference on real video footage
(e.g., railway corridor mast camera) and streams DeepStream Schema 4.0 JSON
to stdout (or MQTT) for consumption by action_engine.py.

Includes an integrated IoU/Centroid tracker (no C++ 'lap' dependency needed on Windows).
"""

import argparse
import datetime as dt
import json
import os
import sys
import time

try:
    import cv2
    import numpy as np
    from ultralytics import YOLO
except ImportError as e:
    sys.stderr.write(f"Error: {e}. Run 'pip install opencv-python ultralytics'\n")
    sys.exit(1)

# COCO Class mapping: 20 is elephant, 0 is person
TARGET_CLASSES = {20: "elephant", 0: "person"}


class SimpleTracker:
    """Lightweight persistent multi-object tracker using box IoU and centroid distance."""
    def __init__(self, max_lost=15, iou_thresh=0.25):
        self.next_id = 1
        self.tracks = {}  # id: {'bbox': [l, t, r, b], 'lost': 0, 'cls': str}
        self.max_lost = max_lost
        self.iou_thresh = iou_thresh

    @staticmethod
    def calc_iou(b1, b2):
        l = max(b1[0], b2[0])
        t = max(b1[1], b2[1])
        r = min(b1[2], b2[2])
        b = min(b1[3], b2[3])
        inter = max(0, r - l) * max(0, b - t)
        area1 = (b1[2] - b1[0]) * (b1[3] - b1[1])
        area2 = (b2[2] - b2[0]) * (b2[3] - b2[1])
        union = area1 + area2 - inter
        return inter / union if union > 0 else 0.0

    def update(self, detections):
        """detections: list of {'bbox': [l, t, r, b], 'conf': float, 'label': str}"""
        # Age existing tracks
        for tid in list(self.tracks.keys()):
            self.tracks[tid]['lost'] += 1
            if self.tracks[tid]['lost'] > self.max_lost:
                del self.tracks[tid]

        assigned_det = set()
        assigned_track = set()

        # Match by IoU
        for tid, tinfo in self.tracks.items():
            best_iou = self.iou_thresh
            best_idx = -1
            for idx, det in enumerate(detections):
                if idx in assigned_det:
                    continue
                if det['label'] != tinfo['cls']:
                    continue
                iou = self.calc_iou(tinfo['bbox'], det['bbox'])
                if iou > best_iou:
                    best_iou = iou
                    best_idx = idx
            if best_idx >= 0:
                self.tracks[tid]['bbox'] = detections[best_idx]['bbox']
                self.tracks[tid]['lost'] = 0
                assigned_det.add(best_idx)
                assigned_track.add(tid)
                detections[best_idx]['id'] = tid

        # New detections get new IDs
        for idx, det in enumerate(detections):
            if idx not in assigned_det:
                new_id = self.next_id
                self.next_id += 1
                self.tracks[new_id] = {'bbox': det['bbox'], 'lost': 0, 'cls': det['label']}
                det['id'] = new_id

        return detections


def run_pipeline(video_path: str, model_name: str = "yolov8n.pt", conf_thresh: float = 0.35,
                 save_annotated: str = None, max_frames: int = None, fps_limit: float = None):
    if not os.path.exists(video_path):
        sys.stderr.write(f"Video file not found: {video_path}\n")
        sys.exit(1)

    sys.stderr.write(f"[Vision] Loading YOLOv8 model ({model_name})...\n")
    model = YOLO(model_name)
    tracker = SimpleTracker(max_lost=10, iou_thresh=0.2)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        sys.stderr.write(f"Could not open video: {video_path}\n")
        sys.exit(1)

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    video_fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    sys.stderr.write(f"[Vision] Source: {video_path} ({width}x{height} @ {video_fps:.1f} fps, {total_frames} frames)\n")

    writer = None
    if save_annotated:
        os.makedirs(os.path.dirname(save_annotated) or ".", exist_ok=True)
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        writer = cv2.VideoWriter(save_annotated, fourcc, video_fps, (width, height))
        sys.stderr.write(f"[Vision] Saving annotated video to: {save_annotated}\n")

    frame_idx = 0
    t0 = time.time()
    next_frame_time = t0

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_idx += 1
            if max_frames and frame_idx > max_frames:
                break

            frame_ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

            # Run standard YOLOv8 inference (no C++ 'lap' dependency needed!)
            results = model(
                frame,
                imgsz=640,
                classes=list(TARGET_CLASSES.keys()),
                conf=conf_thresh,
                verbose=False
            )

            current_detections = []
            if results and len(results) > 0 and results[0].boxes is not None:
                boxes = results[0].boxes
                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    conf = float(boxes.conf[i].item())
                    label = TARGET_CLASSES.get(cls_id, "unknown")
                    xyxy = boxes.xyxy[i].tolist()
                    current_detections.append({
                        'bbox': xyxy,
                        'conf': conf,
                        'label': label
                    })

            # Persistent Tracking
            tracked_objs = tracker.update(current_detections)

            schema_objects = []
            for obj in tracked_objs:
                tid = obj['id']
                l, t, r, b = obj['bbox']
                label = obj['label']
                # DeepStream Schema 4.0: "<id>|<top>|<left>|<bottom>|<right>|<label>"
                schema_objects.append(f"{tid}|{t:.1f}|{l:.1f}|{b:.1f}|{r:.1f}|{label}")

            # Emit DeepStream Schema 4.0 frame payload
            frame_payload = {
                "version": "4.0",
                "id": str(frame_idx),
                "@timestamp": frame_ts,
                "sensorId": "cam0",
                "objects": schema_objects
            }

            print(json.dumps(frame_payload), flush=True)

            if writer is not None:
                # Render bounding box and ID on the video
                for obj in tracked_objs:
                    l, t, r, b = [int(v) for v in obj['bbox']]
                    tid = obj['id']
                    label = obj['label']
                    cv2.rectangle(frame, (l, t), (r, b), (0, 165, 255), 2)
                    cv2.putText(frame, f"ID:{tid} {label}", (l, max(20, t - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
                writer.write(frame)

            if fps_limit and fps_limit > 0:
                target_delay = 1.0 / fps_limit
                elapsed = time.time() - next_frame_time
                if elapsed < target_delay:
                    time.sleep(target_delay - elapsed)
                next_frame_time = time.time()

    finally:
        cap.release()
        if writer:
            writer.release()
        elapsed_total = time.time() - t0
        sys.stderr.write(f"\n[Vision] Completed: {frame_idx} frames processed in {elapsed_total:.2f}s ({frame_idx/max(elapsed_total,0.001):.1f} FPS)\n")


def main():
    parser = argparse.ArgumentParser(description="Gaja-Rakshak Real-Time AI Vision Pipeline")
    parser.add_argument("--video", "-v", required=True, help="Path to input video file")
    parser.add_argument("--model", "-m", default="yolov8n.pt", help="YOLOv8 weights (default: yolov8n.pt)")
    parser.add_argument("--conf", type=float, default=0.35, help="Confidence threshold (default: 0.35)")
    parser.add_argument("--save-annotated", help="Path to save annotated MP4 with detection bounding boxes")
    parser.add_argument("--max-frames", type=int, help="Stop after N frames (optional)")
    parser.add_argument("--fps", type=float, default=0.0, help="Rate-limit output to target FPS (0 for max speed)")
    args = parser.parse_args()

    run_pipeline(
        video_path=args.video,
        model_name=args.model,
        conf_thresh=args.conf,
        save_annotated=args.save_annotated,
        max_frames=args.max_frames,
        fps_limit=args.fps
    )


if __name__ == "__main__":
    main()
