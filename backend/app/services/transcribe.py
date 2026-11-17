import re
import wave
from pathlib import Path
from typing import Any, Dict, List, Optional
import numpy as np
from faster_whisper import WhisperModel
from ..presets import FILLER_WORDS, PROFANITY_LIST

_MODEL_CACHE: Dict[str, WhisperModel] = {}


def get_whisper_model(size: str = "base") -> WhisperModel:
    if size not in _MODEL_CACHE:
        _MODEL_CACHE[size] = WhisperModel(size, device="cpu", compute_type="int8")
    return _MODEL_CACHE[size]


def _clean_token(w: str) -> str:
    return re.sub(r"[^a-z0-9']+", "", w.lower())


def _load_wav_float32(wav_path: Path) -> np.ndarray:
    with wave.open(str(wav_path), "rb") as wf:
        frames = wf.readframes(wf.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def transcribe_audio(
    audio_path: Path,
    language: Optional[str] = None,
    vocabulary: Optional[List[str]] = None,
    model_size: str = "base",
) -> List[Dict[str, Any]]:
    """Transcribe audio with faster-whisper returning paragraph & word-level timings."""
    model = get_whisper_model(model_size)
    prompt = None
    if vocabulary:
        prompt = "Key terms and names: " + ", ".join(vocabulary[:40])
    lang_arg = None if (not language or language == "auto") else language

    audio_input: Any = _load_wav_float32(audio_path) if audio_path.suffix.lower() == ".wav" else str(audio_path)

    segments, _info = model.transcribe(
        audio_input,
        language=lang_arg,
        initial_prompt=prompt,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 350},
    )

    paragraphs: List[Dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        words = []
        if seg.words:
            for w_idx, w in enumerate(seg.words):
                token_raw = w.word.strip()
                cleaned = _clean_token(token_raw)
                words.append({
                    "id": f"w_{idx}_{w_idx}",
                    "word": token_raw,
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                    "isFillerWord": cleaned in FILLER_WORDS,
                    "isProfanity": cleaned in PROFANITY_LIST,
                    "deleted": False,
                    "censored": False,
                })
        else:
            # Fallback if word timestamps unavailable
            parts = seg.text.strip().split()
            dur = max(0.2, float(seg.end) - float(seg.start))
            step = dur / max(1, len(parts))
            for w_idx, token_raw in enumerate(parts):
                cleaned = _clean_token(token_raw)
                ws = float(seg.start) + w_idx * step
                we = ws + step
                words.append({
                    "id": f"w_{idx}_{w_idx}",
                    "word": token_raw,
                    "start": round(ws, 3),
                    "end": round(we, 3),
                    "isFillerWord": cleaned in FILLER_WORDS,
                    "isProfanity": cleaned in PROFANITY_LIST,
                    "deleted": False,
                    "censored": False,
                })

        paragraphs.append({
            "id": f"p_{idx}",
            "start": round(float(seg.start), 3),
            "end": round(float(seg.end), 3),
            "text": seg.text.strip(),
            "speaker": "Speaker 1",
            "words": words,
        })
    return paragraphs


def detect_pauses(paragraphs: List[Dict[str, Any]], threshold_sec: float = 0.5) -> List[Dict[str, Any]]:
    """Find silent gaps between consecutive words >= threshold_sec."""
    all_words = [w for p in paragraphs for w in p.get("words", []) if not w.get("deleted")]
    pauses = []
    for i in range(len(all_words) - 1):
        gap = all_words[i + 1]["start"] - all_words[i]["end"]
        if gap >= threshold_sec:
            pauses.append({
                "id": f"pause_{i}",
                "start": round(all_words[i]["end"], 3),
                "end": round(all_words[i + 1]["start"], 3),
                "duration": round(gap, 3),
            })
    return pauses


def parse_srt(srt_text: str) -> List[Dict[str, Any]]:
    """Parse uploaded custom SRT into paragraph/word format."""
    blocks = re.split(r"\r?\n\r?\n", srt_text.strip())
    paragraphs: List[Dict[str, Any]] = []

    def to_sec(ts: str) -> float:
        ts = ts.replace(",", ".").strip()
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    for idx, b in enumerate(blocks):
        lines = [l.strip() for l in b.splitlines() if l.strip()]
        if len(lines) < 2:
            continue
        time_line = lines[1] if "-->" in lines[1] else lines[0]
        if "-->" not in time_line:
            continue
        s_str, e_str = [x.strip() for x in time_line.split("-->", 1)]
        start, end = to_sec(s_str), to_sec(e_str.split()[0])
        text_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        text = " ".join(text_lines)
        tokens = text.split()
        step = max(0.05, (end - start) / max(1, len(tokens)))
        words = []
        for wi, tok in enumerate(tokens):
            cl = _clean_token(tok)
            ws = start + wi * step
            words.append({
                "id": f"w_{idx}_{wi}",
                "word": tok,
                "start": round(ws, 3),
                "end": round(ws + step, 3),
                "isFillerWord": cl in FILLER_WORDS,
                "isProfanity": cl in PROFANITY_LIST,
                "deleted": False,
                "censored": False,
            })
        paragraphs.append({
            "id": f"p_{idx}",
            "start": round(start, 3),
            "end": round(end, 3),
            "text": text,
            "speaker": "Speaker 1",
            "words": words,
        })
    return paragraphs


def paragraphs_to_srt(paragraphs: List[Dict[str, Any]], offset_sec: float = 0.0) -> str:
    def fmt(sec: float) -> str:
        sec = max(0.0, sec)
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        if ms >= 1000:
            ms -= 1000
            s += 1
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    out: List[str] = []
    idx = 1
    for p in paragraphs:
        words = [w for w in p.get("words", []) if not w.get("deleted")]
        if not words:
            continue
        # Chunk into ~6 words per subtitle cue
        for i in range(0, len(words), 6):
            chunk = words[i:i + 6]
            st = chunk[0]["start"] - offset_sec
            en = chunk[-1]["end"] - offset_sec
            txt = " ".join("***" if w.get("censored") else w["word"] for w in chunk)
            out.append(f"{idx}\n{fmt(st)} --> {fmt(en)}\n{txt}\n")
            idx += 1
    return "\n".join(out)
