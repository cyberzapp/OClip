import base64
import json
import math
import subprocess
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
import cv2
import httpx
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field
from ..config import BROLL_DIR, get_key


class ViralityBreakdownSchema(BaseModel):
    hook: int = Field(ge=0, le=99)
    flow: int = Field(ge=0, le=99)
    value: int = Field(ge=0, le=99)
    trend: int = Field(ge=0, le=99)
    rationale: str


class CuratedClipSchema(BaseModel):
    title: str
    start_sec: float
    end_sec: float
    virality_score: int = Field(ge=0, le=99)
    virality_breakdown: ViralityBreakdownSchema
    headline: str
    viral_hook: str
    keywords: List[str]
    hashtags: List[str]
    youtube_copy: str
    tiktok_copy: str
    linkedin_copy: str


class CurationResultSchema(BaseModel):
    clips: List[CuratedClipSchema]


class BadTakeSchema(BaseModel):
    paragraph_id: str
    reason: str
    word_ids: List[str]


class BadTakesResultSchema(BaseModel):
    bad_takes: List[BadTakeSchema]


class BRollSpotSchema(BaseModel):
    start_sec: float
    end_sec: float
    query: str
    ai_prompt: str
    reason: str


class BRollPlanResultSchema(BaseModel):
    spots: List[BRollSpotSchema]


class TranslatedLineSchema(BaseModel):
    id: str
    text: str


class TranslationResultSchema(BaseModel):
    lines: List[TranslatedLineSchema]


class SocialCopyResultSchema(BaseModel):
    youtube: str
    tiktok: str
    instagram: str
    linkedin: str
    x: str
    hashtags: List[str]


def _get_gemini_client():
    api_key = get_key("GEMINI_API_KEY")
    if not api_key:
        return None
    from google import genai
    return genai.Client(api_key=api_key)


def _sample_video_frames(video_path: Optional[Path], start_sec: float, end_sec: float, max_frames: int = 8) -> List[bytes]:
    if not video_path or not video_path.exists():
        return []
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return []
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    dur = max(1.0, end_sec - start_sec)
    step = dur / max(1, max_frames)
    frames: List[bytes] = []
    for i in range(max_frames):
        t = start_sec + (i + 0.5) * step
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, img = cap.read()
        if not ok:
            continue
        h, w = img.shape[:2]
        scale = min(1.0, 512.0 / max(1, w))
        small = cv2.resize(img, (int(w * scale), int(h * scale)))
        ok2, buf = cv2.imencode(".jpg", small, [int(cv2.IMWRITE_JPEG_QUALITY), 75])
        if ok2:
            frames.append(buf.tobytes())
    cap.release()
    return frames


def curate_clips(
    paragraphs: List[Dict[str, Any]],
    duration_sec: float,
    video_path: Optional[Path] = None,
    curation_pref: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    ClipAnything multimodal curation:
    Uses Gemini when GEMINI_API_KEY is configured, otherwise uses a transcript
    energy + boundary scoring heuristic so the app always works locally.
    """
    pref = curation_pref or {}
    prompt_keywords = (pref.get("topicKeywords") or pref.get("prompt") or "").strip()
    genre = pref.get("genre") or "Auto"
    rng = pref.get("range") or {}
    min_t = float(rng.get("startSec") or 0.0)
    max_t = float(rng.get("endSec") or duration_sec)
    if max_t <= min_t:
        max_t = duration_sec

    dur_buckets = pref.get("clipDurations") or [[15, 65]]
    min_len = float(min(b[0] for b in dur_buckets))
    max_len = float(max(b[1] for b in dur_buckets))

    # Filter transcript to requested timeframe
    scoped = [p for p in paragraphs if p["end"] >= min_t and p["start"] <= max_t]
    if not scoped:
        scoped = paragraphs

    client = _get_gemini_client()
    if client and scoped:
        try:
            from google.genai import types
            # Pass up to 1,500 segments so full-length podcasts aren't truncated at the start
            step = max(1, len(scoped) // 1500)
            transcript_lines = [
                f"[{p['start']:.2f} - {p['end']:.2f}] {p['text']}"
                for p in scoped[::step]
            ]
            instruction = (
                "You are an elite viral short-form video producer (like OpusClip ClipAnything).\n"
                "Your #1 job is to find the MOST SHOCKING, UNUSUAL, CONTROVERSIAL, SURPRISING, or EMOTIONAL moments "
                "from the host, guest, or narrator — moments that make viewers stop scrolling immediately.\n\n"
                "CRITICAL RULES FOR CLIP SELECTION:\n"
                "1. HOOK-FIRST START TIME: Every clip MUST start (`start_sec`) on the EXACT second the speaker says "
                "a shocking claim, bold/contrarian opinion, surprising statistic/number, weird confession, or curiosity-gap question. "
                "NEVER include slow greetings, throat-clearing, or boring setup before the hook.\n"
                "2. SELF-CONTAINED PAYOFF: End (`end_sec`) right after the insight, story, or reaction lands cleanly.\n"
                "3. VIRAL SIGNALS TO HUNT FOR: unusual words, counter-intuitive claims ('everyone thinks X, but actually Y'), "
                "dramatic numbers, strong disagreements, laughter/shock, and memorable one-liners.\n"
                f"Target timeframe: {min_t:.1f}s to {max_t:.1f}s (total video {duration_sec:.1f}s).\n"
                f"Preferred clip duration: {min_len:.0f}s to {max_len:.0f}s.\n"
                f"Genre: {genre}.\n"
                f"User ClipAnything prompt / focus topics: {prompt_keywords or 'Shocking claims, unusual quotes, viral hooks, bold insights'}.\n"
                "Return up to 8 non-overlapping clips ordered by virality_score (0-99) descending. "
                "Write a punchy 5-8 word headline, set `viral_hook` to the exact opening hook quote, and score Hook/Flow/Value/Trend (0-99).\n\n"
                "Transcript:\n" + "\n".join(transcript_lines)
            )
            contents: List[Any] = [instruction]
            for fb in _sample_video_frames(video_path, min_t, max_t, max_frames=8):
                contents.append(types.Part.from_bytes(data=fb, mime_type="image/jpeg"))

            resp = client.models.generate_content(
                model="gemini-3.8-flash",
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=CurationResultSchema.model_json_schema(),
                ),
            )
            parsed = CurationResultSchema.model_validate_json(resp.text)
            results: List[Dict[str, Any]] = []
            for c in parsed.clips:
                s = max(min_t, min(c.start_sec, max_t - 4))
                e = min(max_t, max(s + 4.0, c.end_sec))
                results.append({
                    "title": c.title,
                    "start_sec": round(s, 2),
                    "end_sec": round(e, 2),
                    "duration_sec": round(e - s, 2),
                    "virality_score": int(c.virality_score),
                    "viralityBreakdown": c.virality_breakdown.model_dump(),
                    "headline": c.headline,
                    "viral_hook": c.viral_hook,
                    "keywords": c.keywords,
                    "hashtags": c.hashtags,
                    "genre": genre,
                    "socialCopy": {
                        "youtube": c.youtube_copy,
                        "tiktok": c.tiktok_copy,
                        "instagram": c.tiktok_copy,
                        "linkedin": c.linkedin_copy,
                        "x": c.youtube_copy[:240],
                    },
                })
            if results:
                return results
        except Exception as exc:
            print(f"[ai_engine] Gemini curate_clips fallback triggered: {exc}")

    return _heuristic_curate(scoped, min_t, max_t, min_len, max_len, prompt_keywords, genre)


def _heuristic_curate(
    paragraphs: List[Dict[str, Any]],
    min_t: float,
    max_t: float,
    min_len: float,
    max_len: float,
    prompt_keywords: str,
    genre: str,
) -> List[Dict[str, Any]]:
    total = max(1.0, max_t - min_t)
    if not paragraphs:
        # Silent or non-speech video fallback: slice into evenly spaced highlights
        target = min(max_len, max(min_len, 25.0))
        clips = []
        cur = min_t
        idx = 1
        while cur < max_t - 2.0 and len(clips) < 6:
            end = min(max_t, cur + target)
            if end - cur < 4.0 and clips:
                break
            clips.append({
                "title": f"Highlight Segment #{idx}",
                "start_sec": round(cur, 2),
                "end_sec": round(end, 2),
                "duration_sec": round(end - cur, 2),
                "virality_score": max(62, 86 - idx * 4),
                "viralityBreakdown": {
                    "hook": 78, "flow": 80, "value": 74, "trend": 76,
                    "rationale": "Local visual segment fallback (configure GEMINI_API_KEY for multimodal AI curation).",
                },
                "headline": f"Must-Watch Moment #{idx}",
                "viral_hook": "Watch what happens next...",
                "keywords": ["highlight", "clip"],
                "hashtags": ["#shorts", "#reels", "#viral"],
                "genre": genre,
                "socialCopy": {
                    "youtube": f"Highlight Segment #{idx} #shorts",
                    "tiktok": f"Wait for this moment #{idx} #fyp",
                    "instagram": f"Highlight #{idx} #reels",
                    "linkedin": f"Key takeaway from segment #{idx}.",
                    "x": f"Highlight #{idx}",
                },
            })
            cur = end
            idx += 1
        return clips

    # Hook-first scoring: score every paragraph as a potential shocking/viral opening hook
    target_len = min(max_len, max(min_len, min(45.0, total)))
    kw_terms = [k.strip().lower() for k in prompt_keywords.replace(",", " ").split() if len(k.strip()) > 2]
    shock_cues = {
        "why", "how", "secret", "never", "always", "mistake", "best", "worst", "truth",
        "actually", "stop", "biggest", "imagine", "nobody", "everyone", "insane", "crazy",
        "shocking", "unbelievable", "weird", "illegal", "lie", "wrong", "million", "billion",
        "percent", "killed", "died", "banned", "exposed", "impossible", "destroy", "hack",
    }

    def _hook_score(text: str) -> int:
        low = text.lower()
        words = [w.strip(".,!?\"'") for w in low.split()]
        hits = sum(1 for w in words if w in shock_cues)
        kw_hits = sum(1 for k in kw_terms if k in low)
        has_num = 6 if any(ch.isdigit() for ch in text) else 0
        has_q = 7 if "?" in text else 0
        has_ex = 5 if "!" in text else 0
        return hits * 9 + kw_hits * 12 + has_num + has_q + has_ex

    scored_starts = sorted(
        [(idx, _hook_score(p["text"])) for idx, p in enumerate(paragraphs)],
        key=lambda x: x[1],
        reverse=True,
    )

    candidates: List[Dict[str, Any]] = []
    used_ranges: List[tuple[float, float]] = []
    for i, h_raw in scored_starts:
        if len(candidates) >= 8:
            break
        start = paragraphs[i]["start"]
        if any(not (start + target_len * 0.4 < us or start > ue - 2.0) for us, ue in used_ranges):
            continue
        j = i
        texts: List[str] = []
        while j < len(paragraphs):
            texts.append(paragraphs[j]["text"])
            cur_dur = paragraphs[j]["end"] - start
            if cur_dur >= target_len or j == len(paragraphs) - 1:
                break
            j += 1
        end = paragraphs[j]["end"]
        dur = end - start
        if dur < min(8.0, total * 0.5) and j < len(paragraphs) - 1:
            j += 1
            texts.append(paragraphs[j]["text"])
            end = paragraphs[j]["end"]
            dur = end - start

        joined = " ".join(texts)
        low = joined.lower()
        words = joined.split()
        hook_hits = sum(1 for w in words[:22] if w.lower().strip(".,!?") in shock_cues)
        kw_hits = sum(1 for k in kw_terms if k in low)
        q_bonus = 6 if "?" in joined[:120] else 0
        density = min(15, int(len(words) / max(1.0, dur) * 4))

        hook_score = min(96, 68 + hook_hits * 7 + q_bonus + kw_hits * 8 + (6 if h_raw > 0 else 0))
        flow_score = min(95, 72 + (8 if dur >= 15 else 2))
        value_score = min(96, 70 + density + kw_hits * 9)
        trend_score = min(94, 71 + hook_hits * 4 + (5 if 20 <= dur <= 60 else 0))
        overall = int(round(0.35 * hook_score + 0.22 * flow_score + 0.26 * value_score + 0.17 * trend_score))

        snippet_words = [w.strip(".,!?\"'") for w in words if len(w.strip(".,!?\"'")) > 3]
        top_kw = list(dict.fromkeys([w.lower() for w in snippet_words[:4]])) or ["highlight", "insight"]
        headline = " ".join(words[:7]).strip(".,!?") or f"Clip {len(candidates) + 1}"
        if len(headline) > 48:
            headline = headline[:45].rstrip() + "..."

        s_clamped = round(max(min_t, start), 2)
        e_clamped = round(min(max_t, end), 2)
        used_ranges.append((s_clamped, e_clamped))

        candidates.append({
            "title": headline,
            "start_sec": s_clamped,
            "end_sec": e_clamped,
            "duration_sec": round(e_clamped - s_clamped, 2),
            "virality_score": overall,
            "viralityBreakdown": {
                "hook": hook_score,
                "flow": flow_score,
                "value": value_score,
                "trend": trend_score,
                "rationale": f"Hook-first score ({hook_hits} shock/hook cues, pacing {density}).",
            },
            "headline": headline,
            "viral_hook": paragraphs[i]["text"],
            "keywords": top_kw,
            "hashtags": [f"#{k}" for k in top_kw[:3]] + ["#shorts", "#opusclip"],
            "genre": genre,
            "socialCopy": {
                "youtube": f"{headline} {' '.join('#' + k for k in top_kw[:3])} #shorts",
                "tiktok": f"{headline} 👀 {' '.join('#' + k for k in top_kw[:3])} #fyp",
                "instagram": f"{headline}\n\n{' '.join('#' + k for k in top_kw[:3])} #reels",
                "linkedin": f"Key takeaway: {joined[:160]}...",
                "x": f"{headline} — {joined[:140]}",
            },
        })

    candidates.sort(key=lambda c: c["virality_score"], reverse=True)
    return candidates[:8]


def detect_bad_takes(paragraphs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    client = _get_gemini_client()
    if client and paragraphs:
        try:
            from google.genai import types
            lines = [f"{p['id']}: " + " ".join(f"{w['id']}:{w['word']}" for w in p.get("words", [])) for p in paragraphs]
            prompt = (
                "Identify any bad takes, false starts, stutters, or repeated sentences where the speaker restarts "
                "and re-says the thought cleanly right after. Only flag clear retakes/self-corrections.\n\n"
                + "\n".join(lines[:150])
            )
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=BadTakesResultSchema.model_json_schema(),
                ),
            )
            parsed = BadTakesResultSchema.model_validate_json(resp.text)
            return [b.model_dump() for b in parsed.bad_takes]
        except Exception as exc:
            print(f"[ai_engine] bad_takes fallback: {exc}")

    # Local repetition heuristic
    bad = []
    for p in paragraphs:
        words = p.get("words", [])
        if len(words) >= 6:
            tokens = [w["word"].lower().strip(".,!?") for w in words]
            for idx in range(len(tokens) - 3):
                if tokens[idx:idx + 2] == tokens[idx + 2:idx + 4]:
                    bad.append({
                        "paragraph_id": p["id"],
                        "reason": "Repeated phrase / restart detected",
                        "word_ids": [words[idx]["id"], words[idx + 1]["id"]],
                    })
                    break
    return bad


def plan_broll_spots(paragraphs: List[Dict[str, Any]], clip_start: float, clip_end: float) -> List[Dict[str, Any]]:
    scoped = [p for p in paragraphs if p["end"] >= clip_start and p["start"] <= clip_end]
    client = _get_gemini_client()
    if client and scoped:
        try:
            from google.genai import types
            lines = [f"[{p['start'] - clip_start:.2f} - {p['end'] - clip_start:.2f}] {p['text']}" for p in scoped]
            prompt = (
                f"Analyze this short clip transcript (0s to {clip_end - clip_start:.1f}s) and suggest 2-4 B-roll "
                "insertion moments (each 2.5s-4.5s) where visual imagery reinforces what is being said. "
                "Return clip-relative timestamps, a concise stock search query, and a detailed AI image prompt.\n\n"
                + "\n".join(lines)
            )
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=BRollPlanResultSchema.model_json_schema(),
                ),
            )
            parsed = BRollPlanResultSchema.model_validate_json(resp.text)
            return [s.model_dump() for s in parsed.spots]
        except Exception as exc:
            print(f"[ai_engine] plan_broll fallback: {exc}")

    dur = max(4.0, clip_end - clip_start)
    spots = []
    for idx, p in enumerate(scoped[:3]):
        rel_s = max(1.0, round(p["start"] - clip_start, 2))
        rel_e = min(dur - 0.5, round(rel_s + 3.2, 2))
        if rel_e - rel_s < 1.5:
            continue
        words = [w.strip(".,!?") for w in p["text"].split() if len(w) > 4][:3]
        query = " ".join(words) or "modern technology workspace"
        spots.append({
            "start_sec": rel_s,
            "end_sec": rel_e,
            "query": query,
            "ai_prompt": f"Cinematic 4k editorial visual representing: {p['text'][:120]}",
            "reason": "Illustrates key spoken concept",
        })
    return spots


async def fetch_or_generate_broll(query: str, ai_prompt: str, mode: str = "ai_image") -> Dict[str, Any]:
    """
    Fetch stock media via PEXELS_API_KEY, generate AI image via Gemini,
    or render a clean procedural visual card locally so B-roll always works.
    """
    uid = uuid.uuid4().hex[:10]
    pexels_key = get_key("PEXELS_API_KEY")
    if mode == "stock_video" and pexels_key:
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.get(
                    "https://api.pexels.com/videos/search",
                    params={"query": query, "per_page": 3, "orientation": "portrait"},
                    headers={"Authorization": pexels_key},
                )
                if r.status_code == 200:
                    vids = r.json().get("videos", [])
                    if vids:
                        files = vids[0].get("video_files", [])
                        mp4 = next((f for f in files if f.get("file_type") == "video/mp4"), files[0])
                        dl = await client.get(mp4["link"])
                        out_mp4 = BROLL_DIR / f"broll_{uid}.mp4"
                        out_mp4.write_bytes(dl.content)
                        return {"type": "video", "path": str(out_mp4), "source": "pexels"}
        except Exception as exc:
            print(f"[ai_engine] Pexels video fallback: {exc}")

    if mode == "ai_image" or not pexels_key:
        client = _get_gemini_client()
        if client:
            try:
                resp = client.models.generate_images(
                    model="imagen-3.0-generate-002",
                    prompt=ai_prompt or query,
                    config={"number_of_images": 1, "aspect_ratio": "9:16"},
                )
                if resp.generated_images:
                    img_bytes = resp.generated_images[0].image.image_bytes
                    out_png = BROLL_DIR / f"broll_{uid}.png"
                    out_png.write_bytes(img_bytes)
                    return {"type": "image", "path": str(out_png), "source": "gemini-imagen"}
            except Exception as exc:
                print(f"[ai_engine] Gemini image gen fallback: {exc}")

    # Procedural crisp visual card fallback (works 100% offline on Mac)
    out_png = BROLL_DIR / f"broll_{uid}.png"
    _render_procedural_broll_card(out_png, query)
    return {"type": "image", "path": str(out_png), "source": "local-card"}


def _render_procedural_broll_card(out_path: Path, label: str) -> None:
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), (15, 23, 42))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(18 + 38 * math.sin(t * math.pi))
        g = int(24 + 42 * t)
        b = int(58 + 80 * (1 - t))
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    # Geometric accent rings
    draw.ellipse([180, 420, 900, 1140], outline=(99, 102, 241), width=6)
    draw.ellipse([260, 500, 820, 1060], outline=(56, 189, 248), width=4)
    font = ImageFont.load_default(size=54)
    text = label.upper()[:36]
    draw.text((w // 2, 780), text, fill=(248, 250, 252), anchor="mm", font=font)
    sub_font = ImageFont.load_default(size=30)
    draw.text((w // 2, 860), "B-ROLL VISUAL", fill=(148, 163, 184), anchor="mm", font=sub_font)
    img.save(out_path)


def translate_paragraphs(paragraphs: List[Dict[str, Any]], target_lang: str) -> List[Dict[str, Any]]:
    client = _get_gemini_client()
    if not client or not paragraphs:
        return paragraphs
    try:
        from google.genai import types
        payload = [{"id": p["id"], "text": p["text"]} for p in paragraphs]
        prompt = (
            f"Translate each transcript line naturally into language '{target_lang}' for short-form video subtitles. "
            "Preserve IDs exactly.\n\n" + json.dumps(payload, ensure_ascii=False)
        )
        resp = client.models.generate_content(
            model="gemini-flash-latest",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_json_schema=TranslationResultSchema.model_json_schema(),
            ),
        )
        parsed = TranslationResultSchema.model_validate_json(resp.text)
        by_id = {l.id: l.text for l in parsed.lines}
        out = []
        for p in paragraphs:
            np = dict(p)
            new_text = by_id.get(p["id"], p["text"])
            np["text"] = new_text
            tokens = new_text.split()
            dur = max(0.2, p["end"] - p["start"])
            step = dur / max(1, len(tokens))
            np["words"] = [
                {
                    "id": f"{p['id']}_tr_{idx}",
                    "word": tok,
                    "start": round(p["start"] + idx * step, 3),
                    "end": round(p["start"] + (idx + 1) * step, 3),
                    "isFillerWord": False,
                    "isProfanity": False,
                    "deleted": False,
                    "censored": False,
                }
                for idx, tok in enumerate(tokens)
            ]
            out.append(np)
        return out
    except Exception as exc:
        print(f"[ai_engine] translate fallback: {exc}")
        return paragraphs


async def generate_voiceover(text: str, voice: str = "Samantha", out_wav: Optional[Path] = None) -> Path:
    """Generate TTS voiceover using ElevenLabs if key set, else native macOS `say` + ffmpeg."""
    target = out_wav or (BROLL_DIR / f"vo_{uuid.uuid4().hex[:8]}.wav")
    el_key = get_key("ELEVENLABS_API_KEY")
    if el_key:
        try:
            voice_id = voice if len(voice) > 14 else "21m00Tcm4TlvDq8ikWAM"
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                    headers={"xi-api-key": el_key, "Content-Type": "application/json"},
                    json={"text": text, "model_id": "eleven_multilingual_v2"},
                )
                if r.status_code == 200:
                    mp3 = target.with_suffix(".mp3")
                    mp3.write_bytes(r.content)
                    subprocess.run(["ffmpeg", "-y", "-i", str(mp3), "-ar", "44100", "-ac", "1", str(target)], capture_output=True, check=True)
                    return target
        except Exception as exc:
            print(f"[ai_engine] ElevenLabs fallback to macOS say: {exc}")

    # macOS native `say`
    aiff = target.with_suffix(".aiff")
    subprocess.run(["say", "-v", voice or "Samantha", "-o", str(aiff), text], capture_output=True)
    if aiff.exists():
        subprocess.run(["ffmpeg", "-y", "-i", str(aiff), "-ar", "44100", "-ac", "1", str(target)], capture_output=True, check=True)
        aiff.unlink(missing_ok=True)
    return target


def generate_social_copy(title: str, transcript_text: str) -> Dict[str, Any]:
    client = _get_gemini_client()
    if client:
        try:
            from google.genai import types
            prompt = (
                "Write high-converting short-form social media descriptions and hashtags for YouTube Shorts, "
                "TikTok, Instagram Reels, LinkedIn, and X based on this clip.\n"
                f"Title: {title}\nTranscript: {transcript_text[:2000]}"
            )
            resp = client.models.generate_content(
                model="gemini-flash-latest",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_json_schema=SocialCopyResultSchema.model_json_schema(),
                ),
            )
            return SocialCopyResultSchema.model_validate_json(resp.text).model_dump()
        except Exception as exc:
            print(f"[ai_engine] social copy fallback: {exc}")

    return {
        "youtube": f"{title} — Watch till the end! #shorts #creator",
        "tiktok": f"{title} 👀 Save this for later! #fyp #viral",
        "instagram": f"{title}\n\nWhat do you think? Drop a comment below 👇\n#reels #tips",
        "linkedin": f"{title}\n\n{transcript_text[:200]}...",
        "x": f"{title} — {transcript_text[:180]}",
        "hashtags": ["#shorts", "#reels", "#fyp", "#creator"],
    }
