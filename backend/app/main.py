import asyncio
import json
import shutil
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .config import ASSETS_DIR, DATA_DIR, EXPORTS_DIR, PROJECTS_DIR, UPLOADS_DIR, get_key, save_env_keys
from .presets import ASPECT_RATIOS, CAPTION_PRESETS, CLIP_DURATIONS, GENRES, LAYOUT_MODES
from .services import ai_engine, credits, media_ingest, renderer, tracker, transcribe

db.init_db()

app = FastAPI(title="OClip Local Studio API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _media_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    p = Path(path).resolve()
    try:
        rel = p.relative_to(DATA_DIR.resolve())
        return f"/api/media/{rel.as_posix()}"
    except Exception:
        return None


def _enrich_clip(c: Dict[str, Any]) -> Dict[str, Any]:
    c["previewUrl"] = _media_url(c.get("preview_path"))
    c["exportUrl"] = _media_url(c.get("export_path"))
    c["thumbnailUrl"] = _media_url(c.get("thumbnail_path"))
    return c


def _enrich_project(p: Dict[str, Any]) -> Dict[str, Any]:
    p["sourceMediaUrl"] = _media_url(p.get("source_path"))
    p["thumbnailUrl"] = _media_url(p.get("thumbnail_path"))
    return p


def _build_initial_editing_script(
    clip_data: Dict[str, Any],
    framing: Dict[str, Any],
    render_pref: Dict[str, Any],
    brand_kit: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    kit_cfg = (brand_kit or {}).get("config", {})
    template_id = render_pref.get("captionTemplateId") or kit_cfg.get("captionTemplateId") or "preset-fancy-Karaoke"
    aspect = render_pref.get("aspectRatio") or kit_cfg.get("aspectRatio") or "portrait"
    layout = render_pref.get("layoutMode") or kit_cfg.get("layoutMode") or "card"
    if not render_pref.get("enableAutoLayout", True):
        layout = "fit"

    sfx_list = []
    if render_pref.get("enableAutoSfx"):
        sfx_list = [{"id": "sfx_0", "name": "whoosh", "t": 0.1, "volume": 0.45}]

    return {
        "aspectRatio": aspect,
        "layoutMode": layout,
        "cardFrameRatio": render_pref.get("cardFrameRatio", "3:4"),
        "framing": framing,
        "captions": {
            "enabled": render_pref.get("enableCaption", True),
            "templateId": template_id,
            "fontFamily": kit_cfg.get("fontFamily", "Montserrat"),
            "fontSize": kit_cfg.get("fontSize", 64),
            "uppercase": kit_cfg.get("uppercase", True),
            "primaryColor": kit_cfg.get("primaryColor", "#FFFFFF"),
            "highlightColor": kit_cfg.get("highlightColor", "#04F827"),
            "secondaryColor": kit_cfg.get("secondaryColor", "#FFD400"),
            "enableEmoji": render_pref.get("enableEmoji", True),
            "positionY": 76 if layout == "card" else 72,
            "wordsPerLine": 3,
        },
        "headline": {
            "enabled": render_pref.get("enableAutoHeadline", True),
            "text": clip_data.get("headline", ""),
            "colorStyle": render_pref.get("headlineColorStyle", "yellow"),
            "persistent": layout == "card",
            "durationSec": 999.0 if layout == "card" else 4.5,
        },
        "viralHook": {
            "enabled": render_pref.get("enableViralHook", False),
            "text": clip_data.get("viral_hook", ""),
        },
        "textOverlays": [],
        "brolls": [],
        "speechCleanup": {
            "pauseThresholdSec": 0.5,
            "removedPauses": [],
            "badTakes": [],
        },
        "enhance": {
            "speechEnhance": render_pref.get("enableSpeechEnhance", False),
            "noiseReduction": 0.7,
            "voiceBoost": 0.65,
            "autoColor": render_pref.get("enableAutoColor", False),
            "colorIntensity": 0.7,
            "censorStyle": "**",
            "censorAudioMode": "beep",
            "upscale": False,
        },
        "voiceover": {},
        "sfx": sfx_list,
        "music": {
            "path": kit_cfg.get("musicPath"),
            "volume": kit_cfg.get("musicVolume", 0.12),
        },
    }


async def _run_project_pipeline(project_id: str, custom_srt_text: Optional[str] = None) -> None:
    proj = db.get_project(project_id)
    if not proj:
        return
    proj_dir = PROJECTS_DIR / project_id
    proj_dir.mkdir(parents=True, exist_ok=True)
    try:
        # 1. Ingest video
        if proj["source_type"] == "url" and proj.get("source_url"):
            db.update_project(project_id, stage="downloading", progress=12, status_message="Downloading video via yt-dlp...")
            dl = await asyncio.to_thread(media_ingest.download_url, proj["source_url"], proj_dir)
            src_path = dl["path"]
            db.update_project(project_id, source_path=str(src_path), title=proj["title"] if proj["title"] != "Untitled Project" else dl["title"])
        else:
            src_path = Path(proj["source_path"])

        db.update_project(project_id, stage="probing", progress=25, status_message="Inspecting video streams & generating thumbnail...")
        info = await asyncio.to_thread(media_ingest.probe_media, src_path)
        thumb_path = proj_dir / "source_thumb.jpg"
        await asyncio.to_thread(media_ingest.make_thumbnail, src_path, thumb_path, min(2.0, info["duration"] * 0.2))
        db.update_project(
            project_id,
            duration_sec=info["duration"],
            width=info["width"],
            height=info["height"],
            fps=info["fps"],
            thumbnail_path=str(thumb_path),
        )

        # 2. Transcribe
        brand_kits = db.list_brand_kits()
        brand_kit = next((k for k in brand_kits if k["id"] == proj.get("brand_kit_id")), brand_kits[0] if brand_kits else None)
        vocab = (brand_kit or {}).get("config", {}).get("vocabulary", [])
        import_pref = proj.get("importPref") or {}

        if custom_srt_text:
            db.update_project(project_id, stage="transcribing", progress=45, status_message="Parsing uploaded SRT captions...")
            transcript = transcribe.parse_srt(custom_srt_text)
        else:
            db.update_project(project_id, stage="transcribing", progress=40, status_message="Transcribing audio with local Whisper ASR...")
            wav_path = proj_dir / "audio_16k.wav"
            has_wav = await asyncio.to_thread(media_ingest.extract_audio_wav, src_path, wav_path)
            if has_wav:
                def _on_whisper_progress(frac: float) -> None:
                    pct = 40 + int(22 * frac)
                    done_m = int((info["duration"] * frac) // 60)
                    tot_m = max(1, int(info["duration"] // 60))
                    db.update_project(project_id, progress=pct, status_message=f"Transcribing audio ({done_m}m / {tot_m}m)...")

                transcript = await asyncio.to_thread(
                    transcribe.transcribe_audio,
                    wav_path,
                    import_pref.get("sourceLang"),
                    vocab,
                    "base",
                    info["duration"],
                    _on_whisper_progress,
                )
            else:
                transcript = []
        db.update_project(project_id, transcript=transcript, progress=60)

        # 3. Curate clips (or single-video edit mode)
        render_pref = proj.get("renderPref") or {}
        curation_pref = proj.get("curationPref") or {}
        mode = render_pref.get("mode", "clip")

        db.update_project(project_id, stage="curating", progress=68, status_message="Running ClipAnything AI curation & Virality Scoring...")
        if mode == "single":
            dur = info["duration"]
            curated = [{
                "title": proj.get("title") or "Full Video Edit",
                "start_sec": 0.0,
                "end_sec": round(dur, 2),
                "duration_sec": round(dur, 2),
                "virality_score": 88,
                "viralityBreakdown": {"hook": 86, "flow": 90, "value": 88, "trend": 85, "rationale": "Full-length recipe edit."},
                "headline": proj.get("title") or "",
                "viral_hook": "",
                "keywords": ["full-edit"],
                "hashtags": ["#shorts", "#reels"],
                "genre": curation_pref.get("genre", "Auto"),
                "socialCopy": {},
            }]
        else:
            curated = await asyncio.to_thread(ai_engine.curate_clips, transcript, info["duration"], src_path, curation_pref)

        # 4. Track & Render each clip
        total_clips = max(1, len(curated))
        for idx, cd in enumerate(curated):
            pct = 72 + int(26 * (idx / total_clips))
            db.update_project(project_id, stage="rendering", progress=pct, status_message=f"Reframing & rendering clip {idx + 1}/{total_clips}: {cd['title'][:36]}...")
            clip_id = f"clip_{uuid.uuid4().hex[:10]}"
            framing = await asyncio.to_thread(tracker.analyze_video_framing, src_path, cd["start_sec"], cd["end_sec"])
            es = _build_initial_editing_script(cd, framing, render_pref, brand_kit)

            # Auto B-roll if enabled in recipe
            if render_pref.get("enableBroll"):
                spots = await asyncio.to_thread(ai_engine.plan_broll_spots, transcript, cd["start_sec"], cd["end_sec"])
                for sp in spots[:2]:
                    asset = await ai_engine.fetch_or_generate_broll(sp["query"], sp["ai_prompt"], mode="ai_image")
                    es["brolls"].append({
                        "id": f"br_{uuid.uuid4().hex[:6]}",
                        "start_sec": sp["start_sec"],
                        "end_sec": sp["end_sec"],
                        "query": sp["query"],
                        "assetPath": asset["path"],
                        "assetUrl": _media_url(asset["path"]),
                        "layout": "fill",
                        "source": asset["source"],
                    })

            # Optional dubbing
            if render_pref.get("enableDubbing"):
                target_lang = render_pref.get("targetLang", "es")
                scoped_p = [p for p in transcript if p["end"] >= cd["start_sec"] and p["start"] <= cd["end_sec"]]
                tr_p = await asyncio.to_thread(ai_engine.translate_paragraphs, scoped_p, target_lang)
                dub_txt = " ".join(p["text"] for p in tr_p)
                if dub_txt.strip():
                    vo_wav = await ai_engine.generate_voiceover(dub_txt)
                    es["voiceover"] = {"audioPath": str(vo_wav), "audioUrl": _media_url(str(vo_wav)), "start_sec": 0.0, "originalVolume": 0.15, "text": dub_txt}

            clip_record = {
                "id": clip_id,
                **cd,
                "editingScript": es,
            }
            out_mp4 = proj_dir / f"{clip_id}_preview.mp4"
            clip_thumb = proj_dir / f"{clip_id}_thumb.jpg"
            await asyncio.to_thread(renderer.render_clip, src_path, out_mp4, clip_record, transcript, brand_kit, "720p")
            await asyncio.to_thread(media_ingest.make_thumbnail, out_mp4, clip_thumb, 0.5)
            clip_record["preview_path"] = str(out_mp4)
            clip_record["thumbnail_path"] = str(clip_thumb)
            db.create_clip(project_id, clip_record)

        # Charge exact credits based on actual probed duration & selected recipe/parameters
        rng = curation_pref.get("range") or {}
        est = credits.estimate_project_credits(
            recipe_id=proj.get("recipe_id") or "recipe-clip-long",
            duration_sec=info["duration"],
            has_prompt=bool((curation_pref.get("topicKeywords") or "").strip()),
            has_custom_srt=bool(custom_srt_text),
            start_sec=rng.get("startSec"),
            end_sec=rng.get("endSec"),
            render_pref=render_pref,
        )
        cost = est["estimatedCredits"]
        db.record_credit_change(
            action="project",
            description=f"{proj.get('title', 'Project')} ({proj.get('recipe_id') or 'recipe'}, {est['effectiveMinutes']:.1f}m, {len(curated)} clips)",
            amount=-cost,
            project_id=project_id,
        )

        db.update_project(project_id, stage="completed", progress=100, status_message=f"Ready: {len(curated)} clips generated ({cost} credits used).")
    except Exception as exc:
        db.update_project(project_id, stage="failed", progress=100, status_message="Processing failed", error=str(exc))


# -------------------- API Endpoints --------------------

@app.get("/api/health")
def health():
    return {
        "ok": True,
        "ffmpeg": shutil.which("ffmpeg") is not None,
        "ytdlp": shutil.which("yt-dlp") is not None,
        "keys": {
            "GEMINI_API_KEY": bool(get_key("GEMINI_API_KEY")),
            "PEXELS_API_KEY": bool(get_key("PEXELS_API_KEY")),
            "ELEVENLABS_API_KEY": bool(get_key("ELEVENLABS_API_KEY")),
        },
    }


class KeysUpdate(BaseModel):
    GEMINI_API_KEY: Optional[str] = None
    PEXELS_API_KEY: Optional[str] = None
    ELEVENLABS_API_KEY: Optional[str] = None


@app.post("/api/settings/keys")
def update_keys(payload: KeysUpdate):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    save_env_keys(updates)
    return health()


@app.get("/api/credits")
def get_credits():
    wallet = db.get_credit_wallet()
    wallet["recipeRates"] = credits.RECIPE_RATES_PER_MIN
    return wallet


class CreditEstimateReq(BaseModel):
    recipeId: str = "recipe-clip-long"
    durationSec: float = 180.0
    hasPrompt: bool = False
    hasCustomSrt: bool = False
    startSec: Optional[float] = None
    endSec: Optional[float] = None
    renderPref: Optional[Dict[str, Any]] = None


@app.post("/api/credits/estimate")
def estimate_credits_endpoint(payload: CreditEstimateReq):
    return credits.estimate_project_credits(
        recipe_id=payload.recipeId,
        duration_sec=payload.durationSec,
        has_prompt=payload.hasPrompt,
        has_custom_srt=payload.hasCustomSrt,
        start_sec=payload.startSec,
        end_sec=payload.endSec,
        render_pref=payload.renderPref,
    )


class CreditTopupReq(BaseModel):
    amount: int = 1000


@app.post("/api/credits/topup")
def topup_credits(payload: CreditTopupReq):
    amt = max(1, min(100000, payload.amount))
    res = db.record_credit_change("topup", f"Manual local credit top-up (+{amt})", amt)
    return {**res, **db.get_credit_wallet()}


@app.get("/api/presets")
def get_presets():
    return {
        "genres": GENRES,
        "clipDurations": CLIP_DURATIONS,
        "aspectRatios": ASPECT_RATIOS,
        "layoutModes": LAYOUT_MODES,
        "captionPresets": CAPTION_PRESETS,
    }


@app.get("/api/music")
def get_builtin_music():
    tracks = media_ingest.ensure_builtin_music()
    return {
        "tracks": [
            {**t, "url": _media_url(t["path"])}
            for t in tracks
        ]
    }


@app.get("/api/recipes")
def get_recipes():
    return {"recipes": db.list_recipes()}


class RecipeSave(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    settings: Dict[str, Any]


@app.post("/api/recipes")
def save_recipe(payload: RecipeSave):
    return db.save_recipe(payload.id, payload.name, payload.description, payload.settings)


@app.delete("/api/recipes/{recipe_id}")
def remove_recipe(recipe_id: str):
    if not db.delete_recipe(recipe_id):
        raise HTTPException(status_code=400, detail="Cannot delete built-in or missing recipe")
    return {"ok": True}


@app.get("/api/brand-kits")
def get_brand_kits():
    return {"brandKits": db.list_brand_kits()}


class BrandKitSave(BaseModel):
    id: Optional[str] = None
    name: str
    is_default: bool = False
    config: Dict[str, Any]


@app.post("/api/brand-kits")
def save_brand_kit(payload: BrandKitSave):
    return db.save_brand_kit(payload.id, payload.name, payload.config, payload.is_default)


@app.post("/api/assets/upload")
async def upload_asset(file: UploadFile = File(...), kind: str = Form("logo")):
    ext = Path(file.filename or "asset.bin").suffix
    target = ASSETS_DIR / f"{kind}_{uuid.uuid4().hex[:8]}{ext}"
    target.write_bytes(await file.read())
    return {"path": str(target), "url": _media_url(str(target)), "filename": file.filename}


@app.get("/api/projects")
def list_projects():
    return {"projects": [_enrich_project(p) for p in db.list_projects()]}


@app.post("/api/projects")
async def create_project(
    background_tasks: BackgroundTasks,
    title: str = Form("Untitled Project"),
    videoUrl: Optional[str] = Form(None),
    recipeId: Optional[str] = Form("recipe-clip-long"),
    brandKitId: Optional[str] = Form("kit-default"),
    curationPref: str = Form("{}"),
    renderPref: str = Form("{}"),
    importPref: str = Form("{}"),
    file: Optional[UploadFile] = File(None),
    srtFile: Optional[UploadFile] = File(None),
):
    if not videoUrl and not file:
        raise HTTPException(status_code=400, detail="Provide either a videoUrl or upload a video file.")

    cp = json.loads(curationPref or "{}")
    rp = json.loads(renderPref or "{}")
    ip = json.loads(importPref or "{}")

    src_path = None
    src_type = "url"
    if file and file.filename:
        src_type = "upload"
        ext = Path(file.filename).suffix or ".mp4"
        dest = UPLOADS_DIR / f"{uuid.uuid4().hex[:10]}{ext}"
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        src_path = str(dest)
        if title == "Untitled Project":
            title = Path(file.filename).stem

    srt_text = None
    if srtFile and srtFile.filename:
        srt_text = (await srtFile.read()).decode("utf-8", errors="ignore")

    proj = db.create_project(title, src_type, videoUrl, src_path, cp, rp, ip, recipeId, brandKitId)
    background_tasks.add_task(_run_project_pipeline, proj["id"], srt_text)
    return _enrich_project(proj)


@app.get("/api/projects/{project_id}")
def get_project_detail(project_id: str):
    p = db.get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    clips = [_enrich_clip(c) for c in db.list_clips(project_id=project_id)]
    return {"project": _enrich_project(p), "clips": clips}


@app.delete("/api/projects/{project_id}")
def remove_project(project_id: str):
    if not db.delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    proj_dir = PROJECTS_DIR / project_id
    if proj_dir.exists():
        shutil.rmtree(proj_dir, ignore_errors=True)
    return {"ok": True}


class RerunRequest(BaseModel):
    topicKeywords: str = ""
    genre: str = "Auto"
    clipDurations: List[List[int]] = [[15, 65]]


@app.post("/api/projects/{project_id}/rerun")
async def rerun_project(project_id: str, payload: RerunRequest, background_tasks: BackgroundTasks):
    p = db.get_project(project_id)
    if not p or not p.get("source_path"):
        raise HTTPException(status_code=404, detail="Project source video missing")
    cp = dict(p.get("curationPref") or {})
    cp["topicKeywords"] = payload.topicKeywords
    cp["genre"] = payload.genre
    cp["clipDurations"] = payload.clipDurations
    db.update_project(project_id, curationPref=cp, stage="curating", progress=65, status_message="Re-running ClipAnything prompt...")

    async def _recurate():
        try:
            proj = db.get_project(project_id)
            src_path = Path(proj["source_path"])
            transcript = proj.get("transcript") or []
            curated = await asyncio.to_thread(ai_engine.curate_clips, transcript, proj["duration_sec"], src_path, cp)
            db.delete_clips_for_project(project_id)
            brand_kits = db.list_brand_kits()
            brand_kit = next((k for k in brand_kits if k["id"] == proj.get("brand_kit_id")), brand_kits[0] if brand_kits else None)
            proj_dir = PROJECTS_DIR / project_id
            rp = proj.get("renderPref") or {}
            for idx, cd in enumerate(curated):
                db.update_project(project_id, stage="rendering", progress=75 + int(20 * idx / max(1, len(curated))), status_message=f"Rendering clip {idx + 1}/{len(curated)}...")
                clip_id = f"clip_{uuid.uuid4().hex[:10]}"
                framing = await asyncio.to_thread(tracker.analyze_video_framing, src_path, cd["start_sec"], cd["end_sec"])
                es = _build_initial_editing_script(cd, framing, rp, brand_kit)
                clip_record = {"id": clip_id, **cd, "editingScript": es}
                out_mp4 = proj_dir / f"{clip_id}_preview.mp4"
                clip_thumb = proj_dir / f"{clip_id}_thumb.jpg"
                await asyncio.to_thread(renderer.render_clip, src_path, out_mp4, clip_record, transcript, brand_kit, "720p")
                await asyncio.to_thread(media_ingest.make_thumbnail, out_mp4, clip_thumb, 0.5)
                clip_record["preview_path"] = str(out_mp4)
                clip_record["thumbnail_path"] = str(clip_thumb)
                db.create_clip(project_id, clip_record)
            cost = credits.action_credit_cost("reclip", proj["duration_sec"])
            db.record_credit_change("reclip", f"Re-Clip prompt on {proj['title']}", -cost, project_id=project_id)
            db.update_project(project_id, stage="completed", progress=100, status_message=f"Re-prompt complete: {len(curated)} clips ({cost} credits used).")
        except Exception as exc:
            db.update_project(project_id, stage="failed", progress=100, error=str(exc))

    background_tasks.add_task(_recurate)
    return {"ok": True}


@app.get("/api/clips")
def query_clips(projectId: Optional[str] = Query(None), q: Optional[str] = Query(None)):
    return {"clips": [_enrich_clip(c) for c in db.list_clips(project_id=projectId, q=q)]}


@app.get("/api/clips/{clip_id}")
def get_clip_detail(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    return {"clip": _enrich_clip(c), "project": _enrich_project(p) if p else None}


class ClipPatch(BaseModel):
    title: Optional[str] = None
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    headline: Optional[str] = None
    editingScript: Optional[Dict[str, Any]] = None
    transcript: Optional[List[Dict[str, Any]]] = None


@app.patch("/api/clips/{clip_id}")
def patch_clip(clip_id: str, payload: ClipPatch):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    updates: Dict[str, Any] = {}
    if payload.title is not None:
        updates["title"] = payload.title
    if payload.start_sec is not None:
        updates["start_sec"] = payload.start_sec
    if payload.end_sec is not None:
        updates["end_sec"] = payload.end_sec
    if payload.start_sec is not None or payload.end_sec is not None:
        s = payload.start_sec if payload.start_sec is not None else c["start_sec"]
        e = payload.end_sec if payload.end_sec is not None else c["end_sec"]
        updates["duration_sec"] = round(max(1.0, e - s), 2)
    if payload.headline is not None:
        updates["headline"] = payload.headline
    if payload.editingScript is not None:
        updates["editingScript"] = payload.editingScript
    if payload.transcript is not None:
        db.update_project(c["project_id"], transcript=payload.transcript)
    updated = db.update_clip(clip_id, **updates)
    return _enrich_clip(updated)


class RenderRequest(BaseModel):
    resolution: str = "1080p"


@app.post("/api/clips/{clip_id}/render")
async def render_clip_endpoint(clip_id: str, payload: RenderRequest):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    if not p or not p.get("source_path"):
        raise HTTPException(status_code=400, detail="Source video not found")
    brand_kits = db.list_brand_kits()
    brand_kit = next((k for k in brand_kits if k["id"] == p.get("brand_kit_id")), brand_kits[0] if brand_kits else None)

    proj_dir = PROJECTS_DIR / p["id"]
    out_name = f"{clip_id}_{payload.resolution}.mp4" if payload.resolution != "720p" else f"{clip_id}_preview.mp4"
    out_path = proj_dir / out_name
    await asyncio.to_thread(renderer.render_clip, Path(p["source_path"]), out_path, c, p.get("transcript") or [], brand_kit, payload.resolution)
    thumb = proj_dir / f"{clip_id}_thumb.jpg"
    await asyncio.to_thread(media_ingest.make_thumbnail, out_path, thumb, 0.5)
    field = "export_path" if payload.resolution in ("1080p", "4k") else "preview_path"
    updated = db.update_clip(clip_id, **{field: str(out_path), "preview_path": str(out_path), "thumbnail_path": str(thumb)})
    return _enrich_clip(updated)


@app.post("/api/clips/{clip_id}/duplicate")
def duplicate_clip(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    new_c = dict(c)
    new_c["id"] = f"clip_{uuid.uuid4().hex[:10]}"
    new_c["title"] = f"{c['title']} (Copy)"
    created = db.create_clip(c["project_id"], new_c)
    return _enrich_clip(created)


@app.post("/api/clips/{clip_id}/split")
async def split_clip(clip_id: str, splitSec: float = Query(...)):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    abs_split = c["start_sec"] + splitSec
    if abs_split <= c["start_sec"] + 1.5 or abs_split >= c["end_sec"] - 1.5:
        raise HTTPException(status_code=400, detail="Split point too close to clip edges")
    orig_end = c["end_sec"]
    db.update_clip(clip_id, end_sec=round(abs_split, 2), duration_sec=round(abs_split - c["start_sec"], 2))
    second = dict(c)
    second["id"] = f"clip_{uuid.uuid4().hex[:10]}"
    second["title"] = f"{c['title']} (Part 2)"
    second["start_sec"] = round(abs_split, 2)
    second["end_sec"] = round(orig_end, 2)
    second["duration_sec"] = round(orig_end - abs_split, 2)
    created = db.create_clip(c["project_id"], second)
    return {"first": _enrich_clip(db.get_clip(clip_id)), "second": _enrich_clip(created)}


# -------------------- Editor AI Tools --------------------

@app.post("/api/clips/{clip_id}/broll/plan")
async def plan_broll(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    spots = await asyncio.to_thread(ai_engine.plan_broll_spots, p.get("transcript") or [], c["start_sec"], c["end_sec"])
    return {"spots": spots}


class BRollApplyRequest(BaseModel):
    spots: List[Dict[str, Any]]
    mode: str = "ai_image"  # ai_image | stock_video
    layout: str = "fill"    # fill | pip | split


@app.post("/api/clips/{clip_id}/broll/apply")
async def apply_broll(clip_id: str, payload: BRollApplyRequest):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    es = dict(c.get("editingScript") or {})
    brolls = list(es.get("brolls") or [])
    for sp in payload.spots:
        asset = await ai_engine.fetch_or_generate_broll(sp.get("query", "highlight"), sp.get("ai_prompt", sp.get("query", "")), payload.mode)
        brolls.append({
            "id": f"br_{uuid.uuid4().hex[:6]}",
            "start_sec": float(sp["start_sec"]),
            "end_sec": float(sp["end_sec"]),
            "query": sp.get("query", ""),
            "assetPath": asset["path"],
            "assetUrl": _media_url(asset["path"]),
            "layout": payload.layout,
            "source": asset["source"],
        })
    es["brolls"] = brolls
    updated = db.update_clip(clip_id, editingScript=es)
    cost = credits.action_credit_cost("broll", count=len(payload.spots))
    db.record_credit_change("broll", f"AI B-Roll ({len(payload.spots)} spots) on {c['title']}", -cost, project_id=c["project_id"], clip_id=clip_id)
    return _enrich_clip(updated)


@app.post("/api/clips/{clip_id}/bad-takes")
async def find_bad_takes(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    scoped = [para for para in (p.get("transcript") or []) if para["end"] >= c["start_sec"] and para["start"] <= c["end_sec"]]
    bad = await asyncio.to_thread(ai_engine.detect_bad_takes, scoped)
    pauses = transcribe.detect_pauses(scoped, threshold_sec=float((c.get("editingScript") or {}).get("speechCleanup", {}).get("pauseThresholdSec", 0.5)))
    return {"badTakes": bad, "pauses": pauses}


class VoiceoverReq(BaseModel):
    text: str
    voice: str = "Samantha"
    start_sec: float = 0.0
    originalVolume: float = 0.25


@app.post("/api/clips/{clip_id}/voiceover")
async def create_voiceover(clip_id: str, payload: VoiceoverReq):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    wav = await ai_engine.generate_voiceover(payload.text, payload.voice)
    es = dict(c.get("editingScript") or {})
    es["voiceover"] = {
        "audioPath": str(wav),
        "audioUrl": _media_url(str(wav)),
        "start_sec": payload.start_sec,
        "originalVolume": payload.originalVolume,
        "text": payload.text,
        "voice": payload.voice,
    }
    updated = db.update_clip(clip_id, editingScript=es)
    cost = credits.action_credit_cost("voiceover")
    db.record_credit_change("voiceover", f"AI Voiceover on {c['title']}", -cost, project_id=c["project_id"], clip_id=clip_id)
    return _enrich_clip(updated)


class TranslateReq(BaseModel):
    targetLang: str = "es"
    dubAudio: bool = False


@app.post("/api/clips/{clip_id}/translate")
async def translate_clip(clip_id: str, payload: TranslateReq):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    tr = list(p.get("transcript") or [])
    in_scope = [para for para in tr if para["end"] >= c["start_sec"] and para["start"] <= c["end_sec"]]
    out_scope = [para for para in tr if not (para["end"] >= c["start_sec"] and para["start"] <= c["end_sec"])]
    translated = await asyncio.to_thread(ai_engine.translate_paragraphs, in_scope, payload.targetLang)
    merged = sorted(out_scope + translated, key=lambda x: x["start"])
    db.update_project(p["id"], transcript=merged)

    if payload.dubAudio:
        dub_text = " ".join(para["text"] for para in translated)
        if dub_text.strip():
            wav = await ai_engine.generate_voiceover(dub_text)
            es = dict(c.get("editingScript") or {})
            es["voiceover"] = {"audioPath": str(wav), "audioUrl": _media_url(str(wav)), "start_sec": 0.0, "originalVolume": 0.15, "text": dub_text}
            db.update_clip(clip_id, editingScript=es)

    act = "dub" if payload.dubAudio else "translate"
    cost = credits.action_credit_cost(act, c["duration_sec"])
    db.record_credit_change(act, f"{'Dub' if payload.dubAudio else 'Translate'} ({payload.targetLang}) on {c['title']}", -cost, project_id=c["project_id"], clip_id=clip_id)
    return {"clip": _enrich_clip(db.get_clip(clip_id)), "transcript": merged}


@app.post("/api/clips/{clip_id}/auto-sfx")
def apply_auto_sfx(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    es = dict(c.get("editingScript") or {})
    sfx = [{"id": "sfx_hook", "name": "whoosh", "t": 0.05, "volume": 0.45}]
    for idx, br in enumerate(es.get("brolls", [])):
        sfx.append({"id": f"sfx_br_{idx}", "name": "pop", "t": max(0.0, float(br["start_sec"]) - 0.05), "volume": 0.4})
    if float(c["duration_sec"]) > 8:
        sfx.append({"id": "sfx_mid", "name": "ding", "t": round(float(c["duration_sec"]) * 0.5, 2), "volume": 0.35})
    es["sfx"] = sfx
    updated = db.update_clip(clip_id, editingScript=es)
    cost = credits.action_credit_cost("auto_sfx", c["duration_sec"])
    db.record_credit_change("auto_sfx", f"Auto SFX on {c['title']}", -cost, project_id=c["project_id"], clip_id=clip_id)
    return _enrich_clip(updated)


class ManualTrackReq(BaseModel):
    x: float
    y: float
    w: float
    h: float


@app.post("/api/clips/{clip_id}/track-subject")
async def track_subject(clip_id: str, payload: ManualTrackReq):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    kfs = await asyncio.to_thread(
        tracker.track_manual_subject,
        Path(p["source_path"]),
        c["start_sec"],
        c["end_sec"],
        payload.model_dump(),
    )
    es = dict(c.get("editingScript") or {})
    shots = tracker._quantize_speaker_shots(kfs, max(0.5, c["end_sec"] - c["start_sec"]))
    es["framing"] = {**(es.get("framing") or {}), "keyframes": kfs, "shots": shots, "manualTracked": True}
    es["layoutMode"] = "fill"
    updated = db.update_clip(clip_id, editingScript=es)
    cost = credits.action_credit_cost("track_subject")
    db.record_credit_change("track_subject", f"Subject Tracker on {c['title']}", -cost, project_id=c["project_id"], clip_id=clip_id)
    return _enrich_clip(updated)


@app.post("/api/clips/{clip_id}/social-copy")
async def regen_social_copy(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    scoped = [para["text"] for para in (p.get("transcript") or []) if para["end"] >= c["start_sec"] and para["start"] <= c["end_sec"]]
    copy_data = await asyncio.to_thread(ai_engine.generate_social_copy, c["title"], " ".join(scoped))
    updated = db.update_clip(clip_id, socialCopy=copy_data, hashtags=copy_data.get("hashtags", c.get("hashtags", [])))
    return _enrich_clip(updated)


# -------------------- Downloads & Exports --------------------

@app.get("/api/clips/{clip_id}/download")
async def download_clip(clip_id: str, resolution: str = Query("1080p")):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    brand_kits = db.list_brand_kits()
    brand_kit = next((k for k in brand_kits if k["id"] == p.get("brand_kit_id")), brand_kits[0] if brand_kits else None)
    proj_dir = PROJECTS_DIR / p["id"]
    out_path = proj_dir / f"{clip_id}_{resolution}.mp4"
    if not out_path.exists():
        await asyncio.to_thread(renderer.render_clip, Path(p["source_path"]), out_path, c, p.get("transcript") or [], brand_kit, resolution)
    return FileResponse(path=str(out_path), filename=f"{c['title'][:40].replace(' ', '_')}_{resolution}.mp4", media_type="video/mp4")


@app.get("/api/clips/{clip_id}/srt")
def download_srt(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    scoped = [para for para in (p.get("transcript") or []) if para["end"] >= c["start_sec"] and para["start"] <= c["end_sec"]]
    srt = transcribe.paragraphs_to_srt(scoped, offset_sec=c["start_sec"])
    return PlainTextResponse(srt, headers={"Content-Disposition": f'attachment; filename="{clip_id}.srt"'})


@app.get("/api/clips/{clip_id}/xml")
async def export_xml(clip_id: str):
    c = db.get_clip(clip_id)
    if not c:
        raise HTTPException(status_code=404, detail="Clip not found")
    p = db.get_project(c["project_id"])
    scoped = [para for para in (p.get("transcript") or []) if para["end"] >= c["start_sec"] and para["start"] <= c["end_sec"]]
    zip_path = await asyncio.to_thread(renderer.export_nle_xml_bundle, c, Path(p["source_path"]), scoped)
    return FileResponse(path=str(zip_path), filename=f"{clip_id}_premiere_davinci_xml.zip", media_type="application/zip")


class BulkDownloadReq(BaseModel):
    clipIds: List[str]


@app.post("/api/clips/bulk-download")
def bulk_download(payload: BulkDownloadReq):
    zip_path = EXPORTS_DIR / f"bulk_{uuid.uuid4().hex[:8]}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for cid in payload.clipIds:
            c = db.get_clip(cid)
            if c and c.get("preview_path") and Path(c["preview_path"]).exists():
                zf.write(c["preview_path"], arcname=f"{c['title'][:32].replace(' ', '_')}_{cid}.mp4")
    return FileResponse(path=str(zip_path), filename="oclip_bulk_clips.zip", media_type="application/zip")


# -------------------- Collections & Social Scheduler --------------------

@app.get("/api/collections")
def get_collections():
    return {"collections": db.list_collections()}


class ColCreate(BaseModel):
    name: str


@app.post("/api/collections")
def create_col(payload: ColCreate):
    return db.create_collection(payload.name)


class ColItem(BaseModel):
    clipId: str


@app.post("/api/collections/{col_id}/items")
def add_col_item(col_id: str, payload: ColItem):
    db.add_to_collection(col_id, payload.clipId)
    return {"ok": True}


@app.delete("/api/collections/{col_id}/items/{clip_id}")
def del_col_item(col_id: str, clip_id: str):
    db.remove_from_collection(col_id, clip_id)
    return {"ok": True}


@app.get("/api/schedule")
def get_schedule():
    posts = db.list_scheduled_posts()
    for p in posts:
        p["clip_thumbnail"] = _media_url(p.get("clip_thumbnail"))
        p["clip_preview"] = _media_url(p.get("clip_preview"))
    return {"posts": posts}


class ScheduleCreate(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    clipId: str
    platform: str
    title: str
    post_copy: str = Field("", alias="copy")
    hashtags: List[str] = []
    scheduledAt: str


@app.post("/api/schedule")
def create_schedule(payload: ScheduleCreate):
    return db.create_scheduled_post(payload.clipId, payload.platform, payload.title, payload.post_copy, payload.hashtags, payload.scheduledAt)


@app.delete("/api/schedule/{post_id}")
def delete_schedule(post_id: str):
    if not db.delete_scheduled_post(post_id):
        raise HTTPException(status_code=404, detail="Scheduled post not found")
    return {"ok": True}


@app.get("/api/media/{subpath:path}")
def serve_media(subpath: str):
    target = (DATA_DIR / subpath).resolve()
    if not str(target).startswith(str(DATA_DIR.resolve())) or not target.exists():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(path=str(target))
