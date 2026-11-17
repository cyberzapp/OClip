from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import cv2
import numpy as np


def _get_cascades() -> Tuple[Optional[Any], Optional[Any]]:
    cls = getattr(cv2, "CascadeClassifier", None)
    data = getattr(cv2, "data", None)
    if cls is None or data is None:
        return None, None
    frontal = cls(data.haarcascades + "haarcascade_frontalface_default.xml")
    profile = cls(data.haarcascades + "haarcascade_profileface.xml")
    return frontal, profile


def _mouth_motion_score(
    prev_gray: Optional[np.ndarray],
    gray: np.ndarray,
    fx: int,
    fy: int,
    fw: int,
    fh: int,
) -> float:
    """Measure pixel motion in the lower half (mouth/jaw) of a face bounding box."""
    if prev_gray is None or prev_gray.shape != gray.shape:
        return 0.0
    my0 = max(0, fy + int(fh * 0.52))
    my1 = min(gray.shape[0], fy + fh)
    mx0 = max(0, fx + int(fw * 0.15))
    mx1 = min(gray.shape[1], fx + int(fw * 0.85))
    if my1 <= my0 + 4 or mx1 <= mx0 + 4:
        return 0.0
    diff = cv2.absdiff(prev_gray[my0:my1, mx0:mx1], gray[my0:my1, mx0:mx1])
    return float(np.mean(diff))


def _detect_faces_with_profile(
    gray: np.ndarray,
    frontal: Optional[Any],
    profile: Optional[Any],
) -> List[Tuple[int, int, int, int]]:
    faces: List[Tuple[int, int, int, int]] = []
    if frontal is not None:
        f1 = frontal.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
        for (x, y, w, h) in f1:
            faces.append((int(x), int(y), int(w), int(h)))
    if not faces and profile is not None:
        f2 = profile.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
        for (x, y, w, h) in f2:
            faces.append((int(x), int(y), int(w), int(h)))
        if not faces:
            # Also check flipped frame for right-facing profiles
            flipped = cv2.flip(gray, 1)
            f3 = profile.detectMultiScale(flipped, scaleFactor=1.15, minNeighbors=5, minSize=(28, 28))
            gw = gray.shape[1]
            for (x, y, w, h) in f3:
                faces.append((int(gw - x - w), int(y), int(w), int(h)))
    return faces


def _quantize_speaker_shots(
    keyframes: List[Dict[str, float]],
    total_dur: float,
    min_shot_sec: float = 1.0,
    switch_threshold: float = 0.14,
) -> List[Dict[str, float]]:
    """
    Convert raw per-frame keyframes into clean, stable camera shots so the
    vertical crop snaps to the active speaker without micro-jitter.
    """
    if not keyframes:
        return [{"start": 0.0, "end": round(total_dur, 2), "cx": 0.5, "cy": 0.45}]

    raw_shots: List[Dict[str, float]] = [{
        "start": 0.0,
        "end": total_dur,
        "cx": keyframes[0]["cx"],
        "cy": keyframes[0]["cy"],
        "_count": 1,
    }]

    for kf in keyframes[1:]:
        curr = raw_shots[-1]
        if abs(kf["cx"] - curr["cx"]) < switch_threshold:
            n = curr["_count"]
            curr["cx"] = round((curr["cx"] * n + kf["cx"]) / (n + 1), 4)
            curr["cy"] = round((curr["cy"] * n + kf["cy"]) / (n + 1), 4)
            curr["_count"] = n + 1
        else:
            curr["end"] = round(kf["t"], 2)
            raw_shots.append({
                "start": round(kf["t"], 2),
                "end": round(total_dur, 2),
                "cx": kf["cx"],
                "cy": kf["cy"],
                "_count": 1,
            })

    # Merge ultra-short shots (< min_shot_sec) into neighbor to prevent flicker
    merged: List[Dict[str, float]] = []
    for sh in raw_shots:
        sh.pop("_count", None)
        if merged and (sh["end"] - sh["start"]) < min_shot_sec:
            merged[-1]["end"] = sh["end"]
        else:
            merged.append(sh)
    if merged:
        merged[0]["start"] = 0.0
        merged[-1]["end"] = round(total_dur, 2)
    return merged or [{"start": 0.0, "end": round(total_dur, 2), "cx": 0.5, "cy": 0.45}]


def analyze_video_framing(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    sample_fps: float = 3.0,
) -> Dict[str, Any]:
    """
    Active-speaker detection across a clip segment:
    Measures mouth/jaw motion energy when multiple faces are present so the
    vertical camera always follows whoever is actually speaking.
    """
    cap = cv2.VideoCapture(str(video_path))
    duration = max(0.5, end_sec - start_sec)
    if not cap.isOpened():
        return {
            "width": 1920,
            "height": 1080,
            "speakerCount": 1,
            "keyframes": [{"t": 0.0, "cx": 0.5, "cy": 0.45}],
            "shots": [{"start": 0.0, "end": round(duration, 2), "cx": 0.5, "cy": 0.45}],
            "clusters": [{"cx": 0.5, "cy": 0.45}],
        }

    vid_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)
    frontal, profile = _get_cascades()

    step_sec = max(0.28, 1.0 / sample_fps)
    t = start_sec
    keyframes: List[Dict[str, float]] = []
    all_centers: List[Tuple[float, float]] = []
    max_faces_in_frame = 0
    prev_gray: Optional[np.ndarray] = None
    prev_cx, prev_cy = 0.5, 0.45

    while t <= end_sec:
        frame_idx = int(t * vid_fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ok, frame = cap.read()
        if not ok:
            break
        scale = min(1.0, 480.0 / max(1, width))
        small = cv2.resize(frame, (int(width * scale), int(height * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        faces = _detect_faces_with_profile(gray, frontal, profile)

        if faces:
            max_faces_in_frame = max(max_faces_in_frame, len(faces))
            scored: List[Tuple[float, Tuple[int, int, int, int]]] = []
            for (fx, fy, fw, fh) in faces[:4]:
                cx = (fx + fw / 2.0) / small.shape[1]
                cy = (fy + fh / 2.0) / small.shape[0]
                all_centers.append((cx, cy))
                motion = _mouth_motion_score(prev_gray, gray, fx, fy, fw, fh)
                area_norm = (fw * fh) / float(small.shape[0] * small.shape[1])
                # Prioritize active mouth movement over static face size
                score = motion * 3.0 + area_norm * 10.0
                scored.append((score, (fx, fy, fw, fh)))

            scored.sort(key=lambda item: item[0], reverse=True)
            fx, fy, fw, fh = scored[0][1]
            raw_cx = (fx + fw / 2.0) / small.shape[1]
            raw_cy = (fy + fh / 2.0) / small.shape[0]

            # Snap immediately on large speaker switch, smooth small head movements
            if abs(raw_cx - prev_cx) > 0.18:
                prev_cx, prev_cy = raw_cx, raw_cy
            else:
                prev_cx = 0.65 * prev_cx + 0.35 * raw_cx
                prev_cy = 0.65 * prev_cy + 0.35 * raw_cy

        prev_gray = gray
        keyframes.append({
            "t": round(t - start_sec, 2),
            "cx": round(prev_cx, 4),
            "cy": round(prev_cy, 4),
        })
        t += step_sec

    cap.release()

    clusters: List[Dict[str, float]] = []
    if all_centers:
        sorted_x = sorted(all_centers, key=lambda c: c[0])
        groups: List[List[Tuple[float, float]]] = [[sorted_x[0]]]
        for pt in sorted_x[1:]:
            if abs(pt[0] - groups[-1][-1][0]) < 0.18:
                groups[-1].append(pt)
            else:
                groups.append([pt])
        groups.sort(key=len, reverse=True)
        for g in groups[:4]:
            avg_x = sum(p[0] for p in g) / len(g)
            avg_y = sum(p[1] for p in g) / len(g)
            clusters.append({"cx": round(avg_x, 4), "cy": round(avg_y, 4)})
        clusters.sort(key=lambda c: c["cx"])
    if not clusters:
        clusters = [{"cx": 0.5, "cy": 0.45}]

    shots = _quantize_speaker_shots(keyframes, duration)

    return {
        "width": width,
        "height": height,
        "speakerCount": max(1, min(4, max_faces_in_frame or len(clusters))),
        "keyframes": keyframes or [{"t": 0.0, "cx": 0.5, "cy": 0.45}],
        "shots": shots,
        "clusters": clusters,
    }


def track_manual_subject(
    video_path: Path,
    start_sec: float,
    end_sec: float,
    init_box_norm: Dict[str, float],
    sample_fps: float = 4.0,
) -> List[Dict[str, float]]:
    """
    Manual Subject Tracking ('Reframe Anything' Tracker):
    Given a user-drawn normalized box {x, y, w, h} at start_sec, track the subject
    using OpenCV template matching across the segment.
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return [{"t": 0.0, "cx": init_box_norm["x"] + init_box_norm["w"] / 2, "cy": init_box_norm["y"] + init_box_norm["h"] / 2}]

    vid_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1920)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1080)

    cap.set(cv2.CAP_PROP_POS_FRAMES, int(start_sec * vid_fps))
    ok, first = cap.read()
    if not ok:
        cap.release()
        return [{"t": 0.0, "cx": 0.5, "cy": 0.5}]

    bx = max(0, int(init_box_norm["x"] * width))
    by = max(0, int(init_box_norm["y"] * height))
    bw = max(24, int(init_box_norm["w"] * width))
    bh = max(24, int(init_box_norm["h"] * height))
    bx = min(bx, max(0, width - bw))
    by = min(by, max(0, height - bh))

    tmpl = cv2.cvtColor(first[by:by + bh, bx:bx + bw], cv2.COLOR_BGR2GRAY)
    cx = (bx + bw / 2.0) / width
    cy = (by + bh / 2.0) / height
    keyframes = [{"t": 0.0, "cx": round(cx, 4), "cy": round(cy, 4)}]

    step_sec = max(0.25, 1.0 / sample_fps)
    t = start_sec + step_sec
    while t <= end_sec:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * vid_fps))
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if gray.shape[0] > tmpl.shape[0] and gray.shape[1] > tmpl.shape[1]:
            res = cv2.matchTemplate(gray, tmpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val > 0.35:
                nx, ny = max_loc
                raw_cx = (nx + bw / 2.0) / width
                raw_cy = (ny + bh / 2.0) / height
                cx = 0.65 * cx + 0.35 * raw_cx
                cy = 0.65 * cy + 0.35 * raw_cy
        keyframes.append({
            "t": round(t - start_sec, 2),
            "cx": round(cx, 4),
            "cy": round(cy, 4),
        })
        t += step_sec

    cap.release()
    return keyframes
