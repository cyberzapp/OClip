import json
import math
import struct
import subprocess
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
from ..config import MUSIC_DIR, SFX_DIR


def probe_media(path: Path) -> Dict[str, Any]:
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", "-show_streams", str(path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    data = json.loads(res.stdout)
    fmt = data.get("format", {})
    streams = data.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), {})
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    fps = 30.0
    if v.get("r_frame_rate") and "/" in v["r_frame_rate"]:
        num, den = v["r_frame_rate"].split("/", 1)
        if float(den) > 0:
            fps = round(float(num) / float(den), 3)
    return {
        "duration": float(fmt.get("duration") or v.get("duration") or 0.0),
        "width": int(v.get("width") or 1920),
        "height": int(v.get("height") or 1080),
        "fps": fps,
        "has_audio": a is not None,
        "title": fmt.get("tags", {}).get("title") or path.stem,
    }


def download_url(url: str, out_dir: Path) -> Dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    template = str(out_dir / "source.%(ext)s")
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "-f", "bestvideo[ext=mp4][height<=1080]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "--merge-output-format", "mp4",
        "--print-json",
        "-o", template,
        url,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {res.stderr.strip()[:400]}")
    info = {}
    for line in res.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                info = json.loads(line)
            except Exception:
                pass
    mp4s = sorted(out_dir.glob("source*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not mp4s:
        files = [p for p in out_dir.iterdir() if p.is_file()]
        if not files:
            raise RuntimeError("No media file produced by yt-dlp")
        target = files[0]
    else:
        target = mp4s[0]
    return {"path": target, "title": info.get("title") or target.stem}


def extract_audio_wav(video_path: Path, out_wav: Path) -> bool:
    info = probe_media(video_path)
    if not info["has_audio"]:
        return False
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(out_wav),
    ]
    subprocess.run(cmd, capture_output=True, check=True)
    return True


def make_thumbnail(video_path: Path, out_jpg: Path, timestamp_sec: float = 1.0) -> Path:
    cmd = [
        "ffmpeg", "-y", "-ss", f"{max(0.0, timestamp_sec):.2f}",
        "-i", str(video_path),
        "-vframes", "1", "-q:v", "3",
        str(out_jpg),
    ]
    subprocess.run(cmd, capture_output=True)
    return out_jpg


def ensure_builtin_sfx() -> Dict[str, Path]:
    """Synthesize clean WAV sound effects locally so Auto SFX works without external assets."""
    specs = {
        "whoosh": _gen_whoosh,
        "pop": _gen_pop,
        "ding": _gen_ding,
        "riser": _gen_riser,
    }
    paths: Dict[str, Path] = {}
    for name, fn in specs.items():
        p = SFX_DIR / f"{name}.wav"
        if not p.exists():
            fn(p)
        paths[name] = p
    return paths


def _write_wav(path: Path, samples: list[float], sr: int = 44100) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        frames = bytearray()
        for s in samples:
            val = max(-32767, min(32767, int(s * 32767)))
            frames.extend(struct.pack("<h", val))
        wf.writeframes(bytes(frames))


def _gen_whoosh(path: Path) -> None:
    import random
    sr = 44100
    dur = 0.45
    n = int(sr * dur)
    rng = random.Random(42)
    lp = 0.0
    out = []
    for i in range(n):
        t = i / n
        env = math.sin(math.pi * t) ** 1.6
        noise = rng.uniform(-1.0, 1.0)
        alpha = 0.05 + 0.35 * math.sin(math.pi * t)
        lp = lp + alpha * (noise - lp)
        out.append(lp * env * 0.6)
    _write_wav(path, out, sr)


BUILTIN_MUSIC_SPECS = [
    {"id": "emotional-sorrow", "name": "Emotional / Heartfelt", "mood": "Sad / Emotional / Deep", "filename": "emotional-sorrow.mp3"},
    {"id": "emotional-piano", "name": "Emotional Piano", "mood": "Touching / Storytelling", "filename": "emotional-piano.mp3"},
    {"id": "serious-city", "name": "Serious / Late Night", "mood": "Serious / Podcast / Dark", "filename": "serious-city.mp3"},
    {"id": "lofi-podcast", "name": "Lo-Fi Creator Beat", "mood": "Chill / Podcast / Focus", "filename": "lofi-podcast.mp3"},
    {"id": "calm-story", "name": "Calm Inspiration", "mood": "Warm / Motivational", "filename": "calm-story.mp3"},
    {"id": "inspiring-harp", "name": "Cinematic / Dreamy", "mood": "Dramatic / Reveal", "filename": "inspiring-harp.mp3"},
]


def ensure_builtin_music() -> List[Dict[str, Any]]:
    """Return curated real MP3 background songs stored in data/music."""
    tracks: List[Dict[str, Any]] = []
    for spec in BUILTIN_MUSIC_SPECS:
        p = MUSIC_DIR / spec["filename"]
        if p.exists():
            tracks.append({
                "id": spec["id"],
                "name": spec["name"],
                "mood": spec["mood"],
                "path": str(p),
            })
    return tracks


def _gen_pop(path: Path) -> None:
    sr = 44100
    dur = 0.14
    n = int(sr * dur)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / sr
        freq = 580 * math.exp(-t * 22) + 180
        phase += 2 * math.pi * freq / sr
        env = math.exp(-t * 28)
        out.append(math.sin(phase) * env * 0.7)
    _write_wav(path, out, sr)


BUILTIN_MUSIC_SPECS = [
    {"id": "emotional-sorrow", "name": "Emotional / Heartfelt", "mood": "Sad / Emotional / Deep", "filename": "emotional-sorrow.mp3"},
    {"id": "emotional-piano", "name": "Emotional Piano", "mood": "Touching / Storytelling", "filename": "emotional-piano.mp3"},
    {"id": "serious-city", "name": "Serious / Late Night", "mood": "Serious / Podcast / Dark", "filename": "serious-city.mp3"},
    {"id": "lofi-podcast", "name": "Lo-Fi Creator Beat", "mood": "Chill / Podcast / Focus", "filename": "lofi-podcast.mp3"},
    {"id": "calm-story", "name": "Calm Inspiration", "mood": "Warm / Motivational", "filename": "calm-story.mp3"},
    {"id": "inspiring-harp", "name": "Cinematic / Dreamy", "mood": "Dramatic / Reveal", "filename": "inspiring-harp.mp3"},
]


def ensure_builtin_music() -> List[Dict[str, Any]]:
    """Return curated real MP3 background songs stored in data/music."""
    tracks: List[Dict[str, Any]] = []
    for spec in BUILTIN_MUSIC_SPECS:
        p = MUSIC_DIR / spec["filename"]
        if p.exists():
            tracks.append({
                "id": spec["id"],
                "name": spec["name"],
                "mood": spec["mood"],
                "path": str(p),
            })
    return tracks


def _gen_ding(path: Path) -> None:
    sr = 44100
    dur = 0.55
    n = int(sr * dur)
    out = []
    for i in range(n):
        t = i / sr
        env = math.exp(-t * 7.5)
        s = 0.65 * math.sin(2 * math.pi * 1046.5 * t) + 0.35 * math.sin(2 * math.pi * 1567.98 * t)
        out.append(s * env * 0.5)
    _write_wav(path, out, sr)


BUILTIN_MUSIC_SPECS = [
    {"id": "emotional-sorrow", "name": "Emotional / Heartfelt", "mood": "Sad / Emotional / Deep", "filename": "emotional-sorrow.mp3"},
    {"id": "emotional-piano", "name": "Emotional Piano", "mood": "Touching / Storytelling", "filename": "emotional-piano.mp3"},
    {"id": "serious-city", "name": "Serious / Late Night", "mood": "Serious / Podcast / Dark", "filename": "serious-city.mp3"},
    {"id": "lofi-podcast", "name": "Lo-Fi Creator Beat", "mood": "Chill / Podcast / Focus", "filename": "lofi-podcast.mp3"},
    {"id": "calm-story", "name": "Calm Inspiration", "mood": "Warm / Motivational", "filename": "calm-story.mp3"},
    {"id": "inspiring-harp", "name": "Cinematic / Dreamy", "mood": "Dramatic / Reveal", "filename": "inspiring-harp.mp3"},
]


def ensure_builtin_music() -> List[Dict[str, Any]]:
    """Return curated real MP3 background songs stored in data/music."""
    tracks: List[Dict[str, Any]] = []
    for spec in BUILTIN_MUSIC_SPECS:
        p = MUSIC_DIR / spec["filename"]
        if p.exists():
            tracks.append({
                "id": spec["id"],
                "name": spec["name"],
                "mood": spec["mood"],
                "path": str(p),
            })
    return tracks


def _gen_riser(path: Path) -> None:
    sr = 44100
    dur = 0.8
    n = int(sr * dur)
    out = []
    phase = 0.0
    for i in range(n):
        t = i / dur
        freq = 160 + 680 * (t ** 2)
        phase += 2 * math.pi * freq / sr
        env = (t ** 1.4) * (1.0 - max(0.0, (t - 0.88) / 0.12))
        out.append(math.sin(phase) * env * 0.45)
    _write_wav(path, out, sr)


BUILTIN_MUSIC_SPECS = [
    {"id": "emotional-sorrow", "name": "Emotional / Heartfelt", "mood": "Sad / Emotional / Deep", "filename": "emotional-sorrow.mp3"},
    {"id": "emotional-piano", "name": "Emotional Piano", "mood": "Touching / Storytelling", "filename": "emotional-piano.mp3"},
    {"id": "serious-city", "name": "Serious / Late Night", "mood": "Serious / Podcast / Dark", "filename": "serious-city.mp3"},
    {"id": "lofi-podcast", "name": "Lo-Fi Creator Beat", "mood": "Chill / Podcast / Focus", "filename": "lofi-podcast.mp3"},
    {"id": "calm-story", "name": "Calm Inspiration", "mood": "Warm / Motivational", "filename": "calm-story.mp3"},
    {"id": "inspiring-harp", "name": "Cinematic / Dreamy", "mood": "Dramatic / Reveal", "filename": "inspiring-harp.mp3"},
]


def ensure_builtin_music() -> List[Dict[str, Any]]:
    """Return curated real MP3 background songs stored in data/music."""
    tracks: List[Dict[str, Any]] = []
    for spec in BUILTIN_MUSIC_SPECS:
        p = MUSIC_DIR / spec["filename"]
        if p.exists():
            tracks.append({
                "id": spec["id"],
                "name": spec["name"],
                "mood": spec["mood"],
                "path": str(p),
            })
    return tracks
