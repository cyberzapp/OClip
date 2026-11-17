import html
import subprocess
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from PIL import Image, ImageDraw, ImageFont
from ..config import EXPORTS_DIR
from ..presets import ASPECT_RATIOS, CAPTION_PRESETS
from .media_ingest import ensure_builtin_sfx, probe_media
from .transcribe import paragraphs_to_srt


def _hex_to_rgba(hex_color: str, alpha: int = 255) -> Tuple[int, int, int, int]:
    h = (hex_color or "#FFFFFF").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return (r, g, b, alpha)


def _find_preset(template_id: Optional[str]) -> Dict[str, Any]:
    for p in CAPTION_PRESETS:
        if p["templateId"] == template_id:
            return p
    return CAPTION_PRESETS[0]


def _load_font(font_family: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    fam = (font_family or "").lower()
    candidates: List[str] = []
    if "impact" in fam:
        candidates.append("/System/Library/Fonts/Supplemental/Impact.ttf")
    if "georgia" in fam:
        candidates.append("/System/Library/Fonts/Supplemental/Georgia Bold.ttf")
    if "courier" in fam:
        candidates.append("/System/Library/Fonts/Supplemental/Courier New Bold.ttf")
    if "comic" in fam:
        candidates.append("/System/Library/Fonts/Supplemental/Comic Sans MS Bold.ttf")
    if "montserrat" in fam or "poppins" in fam:
        candidates.extend([
            "/System/Library/Fonts/Supplemental/Arial Black.ttf",
            "/System/Library/Fonts/Avenir Next.ttc",
        ])
    candidates.extend([
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/HelveticaNeue.ttc",
        "/System/Library/Fonts/ArialHB.ttc",
    ])
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size=size)
            except Exception:
                continue
    return ImageFont.load_default(size=size)


def _build_keep_segments(
    clip_start: float,
    clip_end: float,
    transcript: List[Dict[str, Any]],
    removed_pauses: List[Dict[str, Any]],
) -> List[Tuple[float, float]]:
    cut_intervals: List[Tuple[float, float]] = []
    for p in transcript:
        for w in p.get("words", []):
            if w.get("deleted") and w["end"] > clip_start and w["start"] < clip_end:
                cut_intervals.append((max(clip_start, w["start"]), min(clip_end, w["end"])))
    for ps in removed_pauses:
        if ps["end"] > clip_start and ps["start"] < clip_end:
            cut_intervals.append((max(clip_start, ps["start"]), min(clip_end, ps["end"])))

    if not cut_intervals:
        return [(clip_start, clip_end)]

    cut_intervals.sort()
    merged: List[Tuple[float, float]] = [cut_intervals[0]]
    for s, e in cut_intervals[1:]:
        if s <= merged[-1][1] + 0.04:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))

    kept: List[Tuple[float, float]] = []
    cursor = clip_start
    for cs, ce in merged:
        if cs - cursor > 0.08:
            kept.append((cursor, cs))
        cursor = max(cursor, ce)
    if clip_end - cursor > 0.08:
        kept.append((cursor, clip_end))
    return kept or [(clip_start, clip_end)]


def _remap_time(orig_t: float, kept: List[Tuple[float, float]]) -> Optional[float]:
    acc = 0.0
    for s, e in kept:
        if s - 0.05 <= orig_t <= e + 0.05:
            clamped = max(s, min(e, orig_t))
            return acc + (clamped - s)
        acc += (e - s)
    return None


def _draw_caption_cue_png(
    out_png: Path,
    out_w: int,
    out_h: int,
    words: List[Dict[str, Any]],
    active_idx: Optional[int],
    preset: Dict[str, Any],
    caption_cfg: Dict[str, Any],
    headline_text: Optional[str],
    headline_cfg: Optional[Dict[str, Any]] = None,
) -> None:
    img = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_family = caption_cfg.get("fontFamily") or preset["fontFamily"]
    base_size = int(caption_cfg.get("fontSize") or preset["fontSize"])
    scaled_size = max(24, int(base_size * (out_w / 1080.0)))
    font = _load_font(font_family, scaled_size)
    pop_font = _load_font(font_family, int(scaled_size * 1.12))

    # Draw Auto Headline at top if active (with bold Red/Yellow styles & line-wrap)
    if headline_text:
        h_cfg = headline_cfg or {}
        color_style = h_cfg.get("colorStyle", "yellow")
        hl_font_size = max(26, int(scaled_size * (0.95 if color_style in ("yellow", "red") else 0.72)))
        hl_font = _load_font("Impact" if color_style in ("yellow", "red") else font_family, hl_font_size)
        hl_display = headline_text.upper() if color_style in ("yellow", "red", "red-banner", "yellow-banner") else headline_text
        max_hl_w = int(out_w * 0.88)
        hl_words = hl_display.split()
        hl_lines: List[str] = []
        curr = ""
        for hw in hl_words:
            cand = f"{curr} {hw}".strip()
            bb = draw.textbbox((0, 0), cand, font=hl_font)
            if bb[2] - bb[0] <= max_hl_w or not curr:
                curr = cand
            else:
                hl_lines.append(curr)
                curr = hw
        if curr:
            hl_lines.append(curr)
        hl_lines = hl_lines[:3]

        line_metrics = [draw.textbbox((0, 0), ln, font=hl_font) for ln in hl_lines]
        max_tw = max((m[2] - m[0]) for m in line_metrics)
        line_h = max((m[3] - m[1]) for m in line_metrics) + 12
        total_hl_h = line_h * len(hl_lines)
        pad_x, pad_y = int(out_w * 0.035), int(out_h * 0.012)
        by0 = int(out_h * 0.065)

        if color_style in ("yellow", "red"):
            text_rgba = (255, 230, 0, 255) if color_style == "yellow" else (255, 46, 84, 255)
            hl_stroke = max(2, int(6 * (out_w / 1080.0)))
            for li, ln in enumerate(hl_lines):
                ly = by0 + li * line_h + line_h // 2
                draw.text((out_w // 2 + 3, ly + 4), ln, font=hl_font, fill=(0, 0, 0, 220), anchor="mm")
                draw.text((out_w // 2, ly), ln, font=hl_font, fill=text_rgba, stroke_width=hl_stroke, stroke_fill=(0, 0, 0, 255), anchor="mm")
        else:
            if color_style == "red-banner":
                bg_rgba, fg_rgba = (220, 38, 38, 245), (255, 255, 255, 255)
            elif color_style == "yellow-banner":
                bg_rgba, fg_rgba = (250, 204, 21, 245), (17, 24, 39, 255)
            else:
                bg_rgba, fg_rgba = (109, 40, 217, 235), (255, 255, 255, 255)
            bx0 = max(24, (out_w - max_tw) // 2 - pad_x)
            bx1 = min(out_w - 24, (out_w + max_tw) // 2 + pad_x)
            by1 = by0 + total_hl_h + pad_y * 2
            draw.rounded_rectangle([bx0, by0, bx1, by1], radius=18, fill=bg_rgba)
            for li, ln in enumerate(hl_lines):
                ly = by0 + pad_y + li * line_h + line_h // 2
                draw.text((out_w // 2, ly), ln, font=hl_font, fill=fg_rgba, anchor="mm")

    if not words:
        img.save(out_png)
        return

    anim = preset.get("animation", "word_highlight")
    primary_rgba = _hex_to_rgba(caption_cfg.get("primaryColor") or preset["primaryColor"])
    highlight_rgba = _hex_to_rgba(caption_cfg.get("highlightColor") or preset["highlightColor"])
    stroke_rgba = _hex_to_rgba(caption_cfg.get("strokeColor") or preset.get("strokeColor", "#000000"))
    box_rgba = _hex_to_rgba(preset.get("boxColor") or caption_cfg.get("highlightColor") or preset["highlightColor"], alpha=240)
    stroke_w = max(1, int(caption_cfg.get("strokeWidth", preset.get("strokeWidth", 5)) * (out_w / 1080.0)))
    pos_y = int(out_h * (float(caption_cfg.get("positionY", preset.get("positionY", 72))) / 100.0))

    visible_words = words[: active_idx + 1] if (anim == "typewriter" and active_idx is not None) else words
    space_w = int(scaled_size * 0.32)
    max_line_w = int(out_w * 0.88)

    # Measure words and wrap into balanced lines so captions never clip off-screen
    measured_words = []
    for idx, w in enumerate(visible_words):
        f_use = pop_font if (anim == "word_pop" and idx == active_idx) else font
        bb = draw.textbbox((0, 0), w["text"], font=f_use, stroke_width=stroke_w)
        ww = bb[2] - bb[0]
        wh = bb[3] - bb[1]
        measured_words.append((w["text"], f_use, ww, wh, idx == active_idx))

    lines: List[List[Tuple[str, Any, int, int, bool]]] = [[]]
    line_widths: List[int] = [0]
    for item in measured_words:
        ww = item[2]
        sep = space_w if lines[-1] else 0
        if lines[-1] and line_widths[-1] + sep + ww > max_line_w:
            lines.append([item])
            line_widths.append(ww)
        else:
            lines[-1].append(item)
            line_widths[-1] += sep + ww

    line_step = int(scaled_size * 1.25)
    start_y = pos_y - ((len(lines) - 1) * line_step) // 2

    for l_idx, line_items in enumerate(lines):
        ly = start_y + l_idx * line_step
        cursor_x = max(24, (out_w - line_widths[l_idx]) // 2)
        for text, f_use, ww, wh, is_active in line_items:
            if is_active and anim == "box_highlight":
                draw.rounded_rectangle(
                    [cursor_x - 10, ly - wh // 2 - 8, cursor_x + ww + 10, ly + wh // 2 + 12],
                    radius=12,
                    fill=box_rgba,
                )
                fill_c = highlight_rgba
            elif is_active:
                fill_c = highlight_rgba
            else:
                fill_c = primary_rgba

            if preset.get("shadowEnabled", True):
                draw.text((cursor_x + 3, ly + 4), text, font=f_use, fill=(0, 0, 0, 180), anchor="lm")
            draw.text(
                (cursor_x, ly),
                text,
                font=f_use,
                fill=fill_c,
                stroke_width=stroke_w,
                stroke_fill=stroke_rgba,
                anchor="lm",
            )
            cursor_x += ww + space_w

    img.save(out_png)


def _generate_caption_concat(
    work_dir: Path,
    clip_id: str,
    out_w: int,
    out_h: int,
    total_dur: float,
    kept_segments: List[Tuple[float, float]],
    transcript: List[Dict[str, Any]],
    editing_script: Dict[str, Any],
) -> Optional[Path]:
    caption_cfg = editing_script.get("captions", {})
    preset = _find_preset(caption_cfg.get("templateId"))
    cap_enabled = caption_cfg.get("enabled", True) and preset.get("animation") != "none"

    headline_cfg = editing_script.get("headline", {})
    hl_enabled = bool(headline_cfg.get("enabled") and headline_cfg.get("text"))
    hl_text = headline_cfg.get("text", "") if hl_enabled else ""
    is_persistent = headline_cfg.get("persistent", editing_script.get("layoutMode") == "card")
    hl_dur = (total_dur + 5.0) if is_persistent else float(headline_cfg.get("durationSec", 4.5))

    if not cap_enabled and not hl_enabled:
        return None

    uppercase = caption_cfg.get("uppercase", preset["uppercase"])
    wpl = max(1, int(caption_cfg.get("wordsPerLine", preset.get("wordsPerLine", 3))))

    active_words: List[Dict[str, Any]] = []
    if cap_enabled:
        for p in transcript:
            for w in p.get("words", []):
                if w.get("deleted"):
                    continue
                rs = _remap_time(w["start"], kept_segments)
                re_ = _remap_time(w["end"], kept_segments)
                if rs is None or re_ is None or re_ <= rs:
                    continue
                txt = "***" if w.get("censored") else w["word"]
                if uppercase:
                    txt = txt.upper()
                active_words.append({"text": txt, "start": rs, "end": re_})

    # Build piecewise-constant cue intervals with strictly monotonic timestamps
    cues: List[Tuple[float, float, List[Dict[str, Any]], Optional[int]]] = []
    prev_end = 0.0
    for i in range(0, len(active_words), wpl):
        chunk = active_words[i:i + wpl]
        for wi, w in enumerate(chunk):
            st = max(prev_end, w["start"])
            nxt = chunk[wi + 1]["start"] if wi + 1 < len(chunk) else w["end"]
            en = max(st + 0.05, nxt)
            cues.append((st, en, chunk, wi))
            prev_end = en

    cue_dir = work_dir / f"{clip_id}_cues"
    cue_dir.mkdir(parents=True, exist_ok=True)
    blank_png = cue_dir / "blank.png"
    Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0)).save(blank_png)

    # Split intervals around headline end time if headline enabled
    timeline_slices: List[Tuple[float, float, List[Dict[str, Any]], Optional[int], Optional[str]]] = []
    cursor = 0.0
    for st, en, chunk, wi in cues:
        if st > cursor + 0.02:
            if hl_enabled and cursor < hl_dur < st:
                timeline_slices.append((cursor, hl_dur, [], None, hl_text))
                timeline_slices.append((hl_dur, st, [], None, None))
            else:
                timeline_slices.append((cursor, st, [], None, hl_text if (hl_enabled and cursor < hl_dur) else None))
        if hl_enabled and st < hl_dur < en:
            timeline_slices.append((st, hl_dur, chunk, wi, hl_text))
            timeline_slices.append((hl_dur, en, chunk, wi, None))
        else:
            timeline_slices.append((st, en, chunk, wi, hl_text if (hl_enabled and st < hl_dur) else None))
        cursor = max(cursor, en)

    if total_dur > cursor + 0.02:
        if hl_enabled and cursor < hl_dur < total_dur:
            timeline_slices.append((cursor, hl_dur, [], None, hl_text))
            timeline_slices.append((hl_dur, total_dur, [], None, None))
        else:
            timeline_slices.append((cursor, total_dur, [], None, hl_text if (hl_enabled and cursor < hl_dur) else None))

    if not timeline_slices:
        return None

    ffconcat_lines = ["ffconcat version 1.0"]
    last_png = blank_png
    for idx, (st, en, chunk, wi, htxt) in enumerate(timeline_slices):
        dur = max(0.03, en - st)
        if not chunk and not htxt:
            png_path = blank_png
        else:
            png_path = cue_dir / f"cue_{idx:04d}.png"
            _draw_caption_cue_png(png_path, out_w, out_h, chunk, wi, preset, caption_cfg, htxt, headline_cfg)
        ffconcat_lines.append(f"file '{png_path.as_posix()}'")
        ffconcat_lines.append(f"duration {dur:.4f}")
        last_png = png_path
    # Repeat final frame per ffconcat spec
    ffconcat_lines.append(f"file '{last_png.as_posix()}'")

    concat_file = work_dir / f"{clip_id}_cues.ffconcat"
    concat_file.write_text("\n".join(ffconcat_lines) + "\n", encoding="utf-8")
    return concat_file


def render_clip(
    source_path: Path,
    out_path: Path,
    clip: Dict[str, Any],
    transcript: List[Dict[str, Any]],
    brand_kit: Optional[Dict[str, Any]] = None,
    resolution: str = "1080p",
) -> Path:
    info = probe_media(source_path)
    src_w, src_h = info["width"], info["height"]
    has_audio = info["has_audio"]

    es = clip.get("editingScript") or {}
    aspect_key = es.get("aspectRatio", "portrait")
    dims = ASPECT_RATIOS.get(aspect_key, ASPECT_RATIOS["portrait"])
    out_w, out_h = dims["width"], dims["height"]
    if resolution == "4k":
        out_w, out_h = out_w * 2, out_h * 2
    elif resolution == "720p":
        out_w = int(round(out_w * 2 / 3 / 2) * 2)
        out_h = int(round(out_h * 2 / 3 / 2) * 2)

    clip_start = float(clip["start_sec"])
    clip_end = float(clip["end_sec"])
    removed_pauses = es.get("speechCleanup", {}).get("removedPauses", [])
    kept = _build_keep_segments(clip_start, clip_end, transcript, removed_pauses)
    total_kept_dur = sum(e - s for s, e in kept)

    work_dir = out_path.parent
    work_dir.mkdir(parents=True, exist_ok=True)
    concat_file = _generate_caption_concat(
        work_dir, clip["id"], out_w, out_h, total_kept_dur, kept, transcript, es
    )

    framing = es.get("framing", {})
    kfs = framing.get("keyframes", [{"t": 0.0, "cx": 0.5, "cy": 0.45}])
    avg_cx = sum(k["cx"] for k in kfs) / max(1, len(kfs))
    avg_cy = sum(k["cy"] for k in kfs) / max(1, len(kfs))
    layout = es.get("layoutMode", "fill")

    inputs = ["-i", str(source_path)]
    filter_parts: List[str] = []

    if len(kept) == 1:
        ks, ke = kept[0]
        filter_parts.append(f"[0:v]trim=start={ks:.3f}:end={ke:.3f},setpts=PTS-STARTPTS[vtrim]")
        if has_audio:
            filter_parts.append(f"[0:a]atrim=start={ks:.3f}:end={ke:.3f},asetpts=PTS-STARTPTS[atrim]")
    else:
        v_segs, a_segs = [], []
        for idx, (ks, ke) in enumerate(kept):
            filter_parts.append(f"[0:v]trim=start={ks:.3f}:end={ke:.3f},setpts=PTS-STARTPTS[vs{idx}]")
            v_segs.append(f"[vs{idx}]")
            if has_audio:
                filter_parts.append(f"[0:a]atrim=start={ks:.3f}:end={ke:.3f},asetpts=PTS-STARTPTS[as{idx}]")
                a_segs.append(f"[as{idx}]")
        filter_parts.append(f"{''.join(v_segs)}concat=n={len(kept)}:v=1:a=0[vtrim]")
        if has_audio:
            filter_parts.append(f"{''.join(a_segs)}concat=n={len(kept)}:v=0:a=1[atrim]")

    target_ar = out_w / out_h
    if layout == "card":
        # Center Card (3:4 / 1:1 / 4:3) on 9:16 black canvas with active-speaker tracking + room on top for Bold Headline
        card_ratio_str = es.get("cardFrameRatio", "3:4")
        ratio_map = {"3:4": 0.75, "1:1": 1.0, "4:3": 4.0 / 3.0}
        card_ar = ratio_map.get(card_ratio_str, 0.75)
        box_w = out_w
        box_h = min(int(out_h * 0.68), int(round(box_w / card_ar / 2) * 2))
        box_y = max(int(out_h * 0.21), (out_h - box_h) // 2 + int(out_h * 0.03))

        crop_w = int(min(src_w, src_h * card_ar)) // 2 * 2
        crop_h = int(min(src_h, crop_w / card_ar)) // 2 * 2
        shots = framing.get("shots") or []
        if len(shots) > 1:
            def _cx_to_x_card(cx_val: float) -> int:
                return max(0, min(src_w - crop_w, int(cx_val * src_w - crop_w / 2)))
            def _cy_to_y_card(cy_val: float) -> int:
                return max(0, min(src_h - crop_h, int(cy_val * src_h - crop_h / 2)))
            x_expr = str(_cx_to_x_card(shots[-1]["cx"]))
            y_expr = str(_cy_to_y_card(shots[-1]["cy"]))
            for sh in reversed(shots[:-1]):
                x_expr = f"if(lt(t,{sh['end']:.2f}),{_cx_to_x_card(sh['cx'])},{x_expr})"
                y_expr = f"if(lt(t,{sh['end']:.2f}),{_cy_to_y_card(sh['cy'])},{y_expr})"
            filter_parts.append(
                f"[vtrim]crop=w={crop_w}:h={crop_h}:x='{x_expr}':y='{y_expr}',scale={box_w}:{box_h}:flags=lanczos,pad={out_w}:{out_h}:0:{box_y}:black[vreframed]"
            )
        else:
            cx_use = shots[0]["cx"] if shots else avg_cx
            cy_use = shots[0]["cy"] if shots else avg_cy
            crop_x = max(0, min(src_w - crop_w, int(cx_use * src_w - crop_w / 2)))
            crop_y = max(0, min(src_h - crop_h, int(cy_use * src_h - crop_h / 2)))
            filter_parts.append(
                f"[vtrim]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={box_w}:{box_h}:flags=lanczos,pad={out_w}:{out_h}:0:{box_y}:black[vreframed]"
            )
    elif layout == "fit":
        filter_parts.append(
            f"[vtrim]split=2[bg][fg];"
            f"[bg]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},boxblur=24:4[bgb];"
            f"[fg]scale={out_w}:-2:force_original_aspect_ratio=decrease[fgfit];"
            f"[bgb][fgfit]overlay=(W-w)/2:(H-h)/2[vreframed]"
        )
    elif layout == "split" and src_w >= src_h:
        clusters = framing.get("clusters") or [{"cx": 0.28, "cy": 0.45}, {"cx": 0.72, "cy": 0.45}]
        c1 = clusters[0]["cx"]
        c2 = clusters[1]["cx"] if len(clusters) > 1 else min(0.85, c1 + 0.42)
        half_h = out_h // 2
        crop_w = int(min(src_w, src_h * (out_w / half_h)))
        x1 = max(0, min(src_w - crop_w, int(c1 * src_w - crop_w / 2)))
        x2 = max(0, min(src_w - crop_w, int(c2 * src_w - crop_w / 2)))
        filter_parts.append(
            f"[vtrim]split=2[sp1][sp2];"
            f"[sp1]crop={crop_w}:{src_h}:{x1}:0,scale={out_w}:{half_h}[top];"
            f"[sp2]crop={crop_w}:{src_h}:{x2}:0,scale={out_w}:{half_h}[bot];"
            f"[top][bot]vstack=inputs=2[vreframed]"
        )
    elif layout == "screenshare" and src_w >= src_h:
        top_h = int(out_h * 0.55) // 2 * 2
        bot_h = out_h - top_h
        filter_parts.append(
            f"[vtrim]split=2[sc][sp];"
            f"[sc]scale={out_w}:{top_h}:force_original_aspect_ratio=decrease,pad={out_w}:{top_h}:(ow-iw)/2:(oh-ih)/2:black[sct];"
            f"[sp]crop=ih*({out_w}/{bot_h}):ih:{int(avg_cx * src_w)}-iw/2:0,scale={out_w}:{bot_h}[spb];"
            f"[sct][spb]vstack=inputs=2[vreframed]"
        )
    elif layout == "gameplay" and src_w >= src_h:
        top_h = int(out_h * 0.30) // 2 * 2
        bot_h = out_h - top_h
        filter_parts.append(
            f"[vtrim]split=2[cam][gm];"
            f"[cam]crop={int(src_w * 0.35)}:{int(src_h * 0.45)}:{int(avg_cx * src_w - src_w * 0.175)}:0,scale={out_w}:{top_h}[camt];"
            f"[gm]scale={out_w}:{bot_h}:force_original_aspect_ratio=increase,crop={out_w}:{bot_h}[gmb];"
            f"[camt][gmb]vstack=inputs=2[vreframed]"
        )
    else:
        crop_w = int(min(src_w, src_h * target_ar))
        crop_h = int(min(src_h, crop_w / target_ar))
        shots = framing.get("shots") or []
        if len(shots) > 1:
            # Dynamic per-shot active-speaker camera switching
            def _cx_to_x(cx_val: float) -> int:
                return max(0, min(src_w - crop_w, int(cx_val * src_w - crop_w / 2)))

            def _cy_to_y(cy_val: float) -> int:
                return max(0, min(src_h - crop_h, int(cy_val * src_h - crop_h / 2)))

            x_expr = str(_cx_to_x(shots[-1]["cx"]))
            y_expr = str(_cy_to_y(shots[-1]["cy"]))
            for sh in reversed(shots[:-1]):
                sx = _cx_to_x(sh["cx"])
                sy = _cy_to_y(sh["cy"])
                x_expr = f"if(lt(t,{sh['end']:.2f}),{sx},{x_expr})"
                y_expr = f"if(lt(t,{sh['end']:.2f}),{sy},{y_expr})"
            filter_parts.append(
                f"[vtrim]crop=w={crop_w}:h={crop_h}:x='{x_expr}':y='{y_expr}',scale={out_w}:{out_h}:flags=lanczos[vreframed]"
            )
        else:
            cx_use = shots[0]["cx"] if shots else avg_cx
            cy_use = shots[0]["cy"] if shots else avg_cy
            crop_x = max(0, min(src_w - crop_w, int(cx_use * src_w - crop_w / 2)))
            crop_y = max(0, min(src_h - crop_h, int(cy_use * src_h - crop_h / 2)))
            filter_parts.append(
                f"[vtrim]crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={out_w}:{out_h}:flags=lanczos[vreframed]"
            )

    v_curr = "vreframed"

    enhance_cfg = es.get("enhance", {})
    if enhance_cfg.get("sharpHdr"):
        filter_parts.append(
            f"[{v_curr}]eq=contrast=1.18:brightness=0.02:saturation=1.28:gamma=0.95,unsharp=5:5:1.25:5:5:0.5[vhdr]"
        )
        v_curr = "vhdr"
    elif enhance_cfg.get("autoColor"):
        intensity = float(enhance_cfg.get("colorIntensity", 0.7))
        contrast = round(1.0 + 0.12 * intensity, 3)
        sat = round(1.0 + 0.16 * intensity, 3)
        bright = round(0.03 * intensity, 3)
        filter_parts.append(f"[{v_curr}]eq=contrast={contrast}:brightness={bright}:saturation={sat}[vcolor]")
        v_curr = "vcolor"

    if resolution == "4k" or enhance_cfg.get("upscale"):
        filter_parts.append(f"[{v_curr}]unsharp=5:5:0.8:5:5:0.4[vsharp]")
        v_curr = "vsharp"

    # B-roll overlays
    brolls = [b for b in es.get("brolls", []) if b.get("assetPath") and Path(b["assetPath"]).exists()]
    for b_idx, br in enumerate(brolls):
        in_idx = inputs.count("-i")
        bp = Path(br["assetPath"])
        is_img = bp.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
        if is_img:
            inputs.extend(["-loop", "1", "-t", f"{max(0.5, br['end_sec'] - br['start_sec']):.2f}", "-i", str(bp)])
        else:
            inputs.extend(["-stream_loop", "-1", "-i", str(bp)])
        bs = float(br.get("start_sec", 0))
        be = float(br.get("end_sec", bs + 3))
        b_layout = br.get("layout", "fill")
        if b_layout == "pip":
            bw = int(out_w * 0.42)
            bh = int(out_h * 0.30)
            filter_parts.append(
                f"[{in_idx}:v]scale={bw}:{bh}:force_original_aspect_ratio=increase,crop={bw}:{bh},setpts=PTS-STARTPTS+{bs:.2f}/TB[br{b_idx}];"
                f"[{v_curr}][br{b_idx}]overlay=x={out_w - bw - 40}:y=80:enable='between(t,{bs:.2f},{be:.2f})'[vbr{b_idx}]"
            )
        else:
            filter_parts.append(
                f"[{in_idx}:v]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,crop={out_w}:{out_h},setpts=PTS-STARTPTS+{bs:.2f}/TB[br{b_idx}];"
                f"[{v_curr}][br{b_idx}]overlay=0:0:enable='between(t,{bs:.2f},{be:.2f})'[vbr{b_idx}]"
            )
        v_curr = f"vbr{b_idx}"

    # Brand logo overlay
    logo_path = (brand_kit or {}).get("config", {}).get("logoPath")
    if logo_path and Path(logo_path).exists():
        in_idx = inputs.count("-i")
        inputs.extend(["-i", str(logo_path)])
        lw = int(out_w * 0.16)
        filter_parts.append(
            f"[{in_idx}:v]scale={lw}:-1[logo];"
            f"[{v_curr}][logo]overlay=x=W-w-36:y=36[vlogo]"
        )
        v_curr = "vlogo"

    # Overlay animated captions & headline via Pillow ffconcat stream
    if concat_file is not None:
        in_idx = inputs.count("-i")
        inputs.extend(["-f", "concat", "-safe", "0", "-i", str(concat_file)])
        filter_parts.append(f"[{v_curr}][{in_idx}:v]overlay=0:0:eof_action=pass[vout]")
    else:
        filter_parts.append(f"[{v_curr}]null[vout]")

    # Audio pipeline
    a_curr = None
    if has_audio:
        a_curr = "atrim"
        censor_mode = enhance_cfg.get("censorAudioMode", "beep")
        censored_words = [
            w for p in transcript for w in p.get("words", [])
            if w.get("censored") and not w.get("deleted")
        ]
        censor_ranges = []
        for cw in censored_words:
            rs = _remap_time(cw["start"], kept)
            re_ = _remap_time(cw["end"], kept)
            if rs is not None and re_ is not None and re_ > rs:
                censor_ranges.append((rs, re_))
        if censor_ranges:
            cond = "+".join(f"between(t,{rs:.2f},{re_:.2f})" for rs, re_ in censor_ranges)
            if censor_mode in ("mute", "beep"):
                filter_parts.append(f"[{a_curr}]volume=enable='{cond}':volume=0[amuted]")
                a_curr = "amuted"
            if censor_mode == "beep":
                in_idx = inputs.count("-i")
                inputs.extend(["-f", "lavfi", "-t", f"{total_kept_dur:.2f}", "-i", "sine=frequency=1000:sample_rate=44100"])
                filter_parts.append(
                    f"[{in_idx}:a]volume=enable='not({cond})':volume=0,volume=0.25[beeps];"
                    f"[{a_curr}][beeps]amix=inputs=2:duration=first:normalize=0[acens]"
                )
                a_curr = "acens"

        if enhance_cfg.get("speechEnhance"):
            nr = float(enhance_cfg.get("noiseReduction", 0.7))
            nf = int(-15 - 20 * nr)
            filter_parts.append(
                f"[{a_curr}]highpass=f=85,lowpass=f=12000,afftdn=nf={nf},loudnorm=I=-14:TP=-1.5:LRA=11[aenh]"
            )
            a_curr = "aenh"

        vo_cfg = es.get("voiceover", {})
        vo_path = vo_cfg.get("audioPath")
        if vo_path and Path(vo_path).exists():
            in_idx = inputs.count("-i")
            inputs.extend(["-i", str(vo_path)])
            orig_vol = float(vo_cfg.get("originalVolume", 0.25))
            delay_ms = int(float(vo_cfg.get("start_sec", 0)) * 1000)
            filter_parts.append(
                f"[{a_curr}]volume={orig_vol:.2f}[aorig_duck];"
                f"[{in_idx}:a]adelay={delay_ms}|{delay_ms}[avox];"
                f"[aorig_duck][avox]amix=inputs=2:duration=first:normalize=0[avo]"
            )
            a_curr = "avo"

        sfx_list = es.get("sfx", [])
        if sfx_list:
            sfx_bank = ensure_builtin_sfx()
            for s_idx, sx in enumerate(sfx_list[:6]):
                sp = sfx_bank.get(sx.get("name", "whoosh"))
                if sp and sp.exists():
                    in_idx = inputs.count("-i")
                    inputs.extend(["-i", str(sp)])
                    delay_ms = max(0, int(float(sx.get("t", 0)) * 1000))
                    vol = float(sx.get("volume", 0.45))
                    filter_parts.append(
                        f"[{in_idx}:a]adelay={delay_ms}|{delay_ms},volume={vol:.2f}[sfx{s_idx}];"
                        f"[{a_curr}][sfx{s_idx}]amix=inputs=2:duration=first:normalize=0[asfx{s_idx}]"
                    )
                    a_curr = f"asfx{s_idx}"

        music_path = (es.get("music") or {}).get("path") or (brand_kit or {}).get("config", {}).get("musicPath")
        if music_path and Path(music_path).exists():
            in_idx = inputs.count("-i")
            inputs.extend(["-stream_loop", "-1", "-i", str(music_path)])
            mvol = float((es.get("music") or {}).get("volume", 0.12))
            filter_parts.append(
                f"[{in_idx}:a]volume={mvol:.2f}[amus];"
                f"[{a_curr}][amus]amix=inputs=2:duration=first:normalize=0[amix]"
            )
            a_curr = "amix"

    cmd = ["ffmpeg", "-y", *inputs, "-filter_complex", ";".join(filter_parts), "-map", "[vout]"]
    if a_curr:
        cmd.extend(["-map", f"[{a_curr}]", "-c:a", "aac", "-b:a", "192k"])
    else:
        cmd.append("-an")
    cmd.extend([
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(out_path),
    ])
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg render failed: {res.stderr[-600:]}")
    return out_path


def export_nle_xml_bundle(
    clip: Dict[str, Any],
    source_path: Path,
    transcript: List[Dict[str, Any]],
) -> Path:
    bundle_zip = EXPORTS_DIR / f"{clip['id']}_premiere_davinci_xml.zip"
    xml_path = EXPORTS_DIR / f"{clip['id']}.xml"
    srt_path = EXPORTS_DIR / f"{clip['id']}.srt"

    srt_text = paragraphs_to_srt(transcript, offset_sec=float(clip["start_sec"]))
    srt_path.write_text(srt_text, encoding="utf-8")

    dur_frames = max(30, int(float(clip["duration_sec"]) * 30))
    start_frame = int(float(clip["start_sec"]) * 30)
    end_frame = start_frame + dur_frames
    safe_title = html.escape(clip["title"])
    file_url = f"file://{source_path}"

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
  <sequence id="sequence-1">
    <name>{safe_title}</name>
    <duration>{dur_frames}</duration>
    <rate>
      <timebase>30</timebase>
      <ntsc>FALSE</ntsc>
    </rate>
    <media>
      <video>
        <format>
          <samplecharacteristics>
            <width>1080</width>
            <height>1920</height>
          </samplecharacteristics>
        </format>
        <track>
          <clipitem id="clipitem-1">
            <name>{safe_title}</name>
            <duration>{dur_frames}</duration>
            <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
            <start>0</start>
            <end>{dur_frames}</end>
            <in>{start_frame}</in>
            <out>{end_frame}</out>
            <file id="file-1">
              <name>{html.escape(source_path.name)}</name>
              <pathurl>{html.escape(file_url)}</pathurl>
            </file>
          </clipitem>
        </track>
      </video>
      <audio>
        <track>
          <clipitem id="audioitem-1">
            <name>{safe_title}</name>
            <duration>{dur_frames}</duration>
            <rate><timebase>30</timebase><ntsc>FALSE</ntsc></rate>
            <start>0</start>
            <end>{dur_frames}</end>
            <in>{start_frame}</in>
            <out>{end_frame}</out>
            <file id="file-1"/>
          </clipitem>
        </track>
      </audio>
    </media>
  </sequence>
</xmeml>
"""
    xml_path.write_text(xml_content, encoding="utf-8")

    with zipfile.ZipFile(bundle_zip, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(xml_path, arcname=f"{clip['id']}.xml")
        zf.write(srt_path, arcname=f"{clip['id']}.srt")
        if clip.get("preview_path") and Path(clip["preview_path"]).exists():
            zf.write(clip["preview_path"], arcname=f"{clip['id']}_rendered.mp4")

    return bundle_zip
