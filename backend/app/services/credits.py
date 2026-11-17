"""Transparent OpusClip-style credit calculator for local & API-key actions."""

from typing import Any, Dict, List, Optional


RECIPE_RATES_PER_MIN: Dict[str, Dict[str, Any]] = {
    "recipe-clip-long": {
        "label": "Clip long video",
        "basePerMin": 1.0,
        "features": ["Whisper ASR", "Gemini ClipAnything", "Center Card / Reframe", "Captions + Headline"],
    },
    "recipe-cleanup-recording": {
        "label": "Clean up recording",
        "basePerMin": 2.5,
        "features": ["Whisper ASR", "Speech Cleanup", "Speech Enhancement", "Auto Color"],
    },
    "recipe-auto-edit-talking": {
        "label": "Auto-edit talking videos",
        "basePerMin": 11.5,
        "features": ["ClipAnything", "Captions", "Viral Hook", "AI B-Roll", "Speech Enhance", "Auto SFX"],
    },
    "recipe-captions": {
        "label": "Captions",
        "basePerMin": 0.5,
        "features": ["Whisper ASR", "Animated Captions"],
    },
    "recipe-reframe": {
        "label": "Reframe",
        "basePerMin": 0.5,
        "features": ["Active Speaker Tracking", "Aspect Reframe"],
    },
    "recipe-social-edits": {
        "label": "Social edits",
        "basePerMin": 8.5,
        "features": ["ClipAnything", "Captions", "Viral Hook", "Auto SFX"],
    },
    "recipe-ai-broll": {
        "label": "AI B-roll",
        "basePerMin": 4.0,
        "features": ["Whisper ASR", "Captions", "AI B-Roll Planner & Visuals"],
    },
    "recipe-translate-dub": {
        "label": "Translate & dub",
        "basePerMin": 10.0,
        "features": ["Whisper ASR", "Gemini Translation", "Voice Dubbing"],
    },
}


def estimate_project_credits(
    recipe_id: str,
    duration_sec: float = 60.0,
    has_prompt: bool = False,
    has_custom_srt: bool = False,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
    render_pref: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    effective_sec = max(10.0, duration_sec or 60.0)
    if start_sec is not None and end_sec is not None and end_sec > start_sec:
        effective_sec = max(10.0, end_sec - start_sec)
    elif start_sec is not None and start_sec > 0 and duration_sec > start_sec:
        effective_sec = max(10.0, duration_sec - start_sec)

    minutes = max(0.5, effective_sec / 60.0)
    spec = RECIPE_RATES_PER_MIN.get(recipe_id)

    breakdown: List[Dict[str, Any]] = []
    if spec:
        base_cost = round(spec["basePerMin"] * minutes, 1)
        breakdown.append({
            "item": f"Recipe: {spec['label']} ({spec['basePerMin']}/min × {minutes:.1f}m)",
            "credits": base_cost,
        })
    else:
        # Custom recipe computed from its settings flags
        rp = render_pref or {}
        rate = 0.5
        if rp.get("mode", "clip") == "clip":
            rate += 0.5
        if rp.get("enableSpeechEnhance"):
            rate += 1.5
        if rp.get("enableBroll"):
            rate += 3.0
        if rp.get("enableAutoSfx"):
            rate += 7.0
        if rp.get("enableDubbing"):
            rate += 9.0
        if rp.get("enableAutoColor"):
            rate += 0.5
        base_cost = round(rate * minutes, 1)
        breakdown.append({
            "item": f"Custom Recipe ({rate:.1f}/min × {minutes:.1f}m)",
            "credits": base_cost,
        })

    if has_prompt:
        breakdown.append({"item": "ClipAnything Custom Prompt", "credits": 1.0})

    if has_custom_srt:
        discount = round(-0.3 * minutes, 1)
        breakdown.append({"item": "Custom .SRT provided (skips Whisper ASR)", "credits": discount})

    total = max(1, int(round(sum(b["credits"] for b in breakdown))))
    return {
        "estimatedCredits": total,
        "effectiveMinutes": round(minutes, 2),
        "breakdown": breakdown,
    }


def action_credit_cost(action: str, duration_sec: float = 30.0, count: int = 1) -> int:
    mins = max(0.5, duration_sec / 60.0)
    if action == "reclip":
        return max(1, int(round(1.0 * mins)))
    if action == "broll":
        return max(1, 3 * max(1, count))
    if action == "auto_sfx":
        return max(2, int(round(7.0 * mins)))
    if action == "voiceover":
        return 3
    if action == "translate":
        return 2
    if action == "dub":
        return max(3, int(round(10.0 * mins)))
    if action == "track_subject":
        return 1
    if action == "upscale_4k":
        return max(5, int(round(10.0 * mins)))
    if action == "speech_enhance":
        return max(2, int(round(6.0 * mins)))
    return 1
