"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  Captions,
  Check,
  Crosshair,
  Download,
  Eraser,
  FileCode2,
  Film,
  Languages,
  LayoutGrid,
  Loader2,
  Mic,
  Music,
  Pause,
  Play,
  Plus,
  Scissors,
  ShieldAlert,
  Sparkles,
  Trash2,
  Volume2,
  Wand2,
} from "lucide-react";
import { CaptionPreset, Clip, Project, TranscriptParagraph } from "@/lib/types";

interface Props {
  clip: Clip;
  project: Project;
  captionPresets: CaptionPreset[];
  onBack: () => void;
  onUpdated: (clip: Clip, transcript?: TranscriptParagraph[]) => void;
}

type InspectorTab = "captions" | "layout" | "broll" | "enhance";

export default function ClipEditor({ clip: initialClip, project: initialProject, captionPresets, onBack, onUpdated }: Props) {
  const [clip, setClip] = useState<Clip>(initialClip);
  const [transcript, setTranscript] = useState<TranscriptParagraph[]>(initialProject.transcript || []);
  const [tab, setTab] = useState<InspectorTab>("captions");
  const [currentTime, setCurrentTime] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [showSafeZone, setShowSafeZone] = useState(false);
  const [hideDeleted, setHideDeleted] = useState(false);
  const [saving, setSaving] = useState(false);
  const [rendering, setRendering] = useState(false);
  const [styleDirty, setStyleDirty] = useState(false);
  const [statusMsg, setStatusMsg] = useState<string | null>(null);

  // Speech cleanup state
  const [pauseThreshold, setPauseThreshold] = useState(
    initialClip.editingScript?.speechCleanup?.pauseThresholdSec ?? 0.5
  );
  const [badTakes, setBadTakes] = useState<{ paragraph_id: string; reason: string; word_ids: string[] }[]>(
    initialClip.editingScript?.speechCleanup?.badTakes || []
  );

  // B-roll planner state
  const [brollSpots, setBrollSpots] = useState<{ start_sec: number; end_sec: number; query: string; ai_prompt: string; reason: string }[]>([]);
  const [brollMode, setBrollMode] = useState<"ai_image" | "stock_video">("ai_image");
  const [brollLayout, setBrollLayout] = useState<"fill" | "pip">("fill");
  const [brollLoading, setBrollLoading] = useState(false);

  // Voiceover / Dubbing state
  const [voText, setVoText] = useState("");
  const [voVoice, setVoVoice] = useState("Samantha");
  const [voOrigVol, setVoOrigVol] = useState(0.25);
  const [targetLang, setTargetLang] = useState("es");
  const [dubAudio, setDubAudio] = useState(false);

  // Manual subject tracking
  const [trackingMode, setTrackingMode] = useState(false);
  const [dragBox, setDragBox] = useState<{ startX: number; startY: number; x: number; y: number; w: number; h: number } | null>(null);

  const videoRef = useRef<HTMLVideoElement>(null);
  const previewWrapRef = useRef<HTMLDivElement>(null);

  // Built-in background music library
  const [musicTracks, setMusicTracks] = useState<{ id: string; name: string; mood: string; path: string; url: string }[]>([]);
  const [previewTrackId, setPreviewTrackId] = useState<string | null>(null);
  const musicPreviewRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    setClip(initialClip);
  }, [initialClip]);

  useEffect(() => {
    fetch("/api/music")
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d?.tracks && setMusicTracks(d.tracks))
      .catch(() => {});
    return () => {
      musicPreviewRef.current?.pause();
    };
  }, []);

  const es = clip.editingScript;

  const scopedParagraphs = useMemo(
    () =>
      transcript.filter(
        (p) => p.end >= clip.start_sec - 0.2 && p.start <= clip.end_sec + 0.2
      ),
    [transcript, clip.start_sec, clip.end_sec]
  );

  const activeCaptionWords = useMemo(() => {
    const absT = clip.start_sec + currentTime;
    const allWords = scopedParagraphs.flatMap((p) => p.words).filter((w) => !w.deleted);
    const wpl = es.captions?.wordsPerLine || 3;
    for (let i = 0; i < allWords.length; i += wpl) {
      const chunk = allWords.slice(i, i + wpl);
      if (chunk.length === 0) continue;
      if (absT >= chunk[0].start - 0.08 && absT <= chunk[chunk.length - 1].end + 0.15) {
        return { chunk, absT };
      }
    }
    return null;
  }, [scopedParagraphs, currentTime, clip.start_sec, es.captions?.wordsPerLine]);

  // Keyboard shortcuts (Space, J/K/L)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
      const vid = videoRef.current;
      if (!vid) return;
      if (e.code === "Space") {
        e.preventDefault();
        if (vid.paused) vid.play();
        else vid.pause();
      } else if (e.key.toLowerCase() === "j") {
        vid.currentTime = Math.max(0, vid.currentTime - 2);
      } else if (e.key.toLowerCase() === "l") {
        vid.currentTime = Math.min(vid.duration || 60, vid.currentTime + 2);
      } else if (e.key.toLowerCase() === "k") {
        vid.pause();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const persistEdits = async (nextClip: Clip, nextTranscript?: TranscriptParagraph[]) => {
    setSaving(true);
    try {
      const res = await fetch(`/api/clips/${nextClip.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          title: nextClip.title,
          start_sec: nextClip.start_sec,
          end_sec: nextClip.end_sec,
          headline: nextClip.headline,
          editingScript: nextClip.editingScript,
          ...(nextTranscript ? { transcript: nextTranscript } : {}),
        }),
      });
      if (res.ok) {
        const updated = (await res.json()) as Clip;
        setClip(updated);
        onUpdated(updated, nextTranscript);
      }
    } finally {
      setSaving(false);
    }
  };

  const renderClip = async (resolution: "720p" | "1080p" | "4k" = "720p") => {
    setRendering(true);
    setStatusMsg(`Rendering ${resolution} preview via FFmpeg...`);
    try {
      await persistEdits(clip, transcript);
      const res = await fetch(`/api/clips/${clip.id}/render`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resolution }),
      });
      if (res.ok) {
        const updated = (await res.json()) as Clip;
        // bust browser video cache
        const bust = updated.previewUrl ? `${updated.previewUrl}?t=${Date.now()}` : null;
        const withBust = { ...updated, previewUrl: bust };
        setClip(withBust);
        setStyleDirty(false);
        onUpdated(withBust, transcript);
        setStatusMsg(`${resolution} render complete!`);
      } else {
        setStatusMsg("Render failed — check backend logs.");
      }
    } finally {
      setRendering(false);
    }
  };

  const toggleWordDeleted = (wordId: string) => {
    const next = transcript.map((p) => ({
      ...p,
      words: p.words.map((w) => (w.id === wordId ? { ...w, deleted: !w.deleted } : w)),
    }));
    setTranscript(next);
    persistEdits(clip, next);
  };

  const removeAllFillers = () => {
    const next = transcript.map((p) => {
      if (p.end < clip.start_sec || p.start > clip.end_sec) return p;
      return {
        ...p,
        words: p.words.map((w) => (w.isFillerWord ? { ...w, deleted: true } : w)),
      };
    });
    setTranscript(next);
    setStatusMsg("Filler words marked for cut — click Re-Render to bake cuts.");
    persistEdits(clip, next);
  };

  const censorProfanity = () => {
    const next = transcript.map((p) => {
      if (p.end < clip.start_sec || p.start > clip.end_sec) return p;
      return {
        ...p,
        words: p.words.map((w) => (w.isProfanity ? { ...w, censored: !w.censored } : w)),
      };
    });
    setTranscript(next);
    setStatusMsg("Profanity toggled (** + beep on render).");
    persistEdits(clip, next);
  };

  const detectBadTakesAndPauses = async () => {
    setStatusMsg("Scanning transcript for bad takes & pauses...");
    const res = await fetch(`/api/clips/${clip.id}/bad-takes`, { method: "POST" });
    if (res.ok) {
      const data = await res.json();
      setBadTakes(data.badTakes || []);
      const pauses = (data.pauses || []).filter((p: { duration: number }) => p.duration >= pauseThreshold);
      const nextClip: Clip = {
        ...clip,
        editingScript: {
          ...es,
          speechCleanup: {
            pauseThresholdSec: pauseThreshold,
            removedPauses: pauses,
            badTakes: data.badTakes || [],
          },
        },
      };
      setClip(nextClip);
      persistEdits(nextClip);
      setStatusMsg(`Found ${(data.badTakes || []).length} bad takes and ${pauses.length} pauses ≥ ${pauseThreshold}s.`);
    }
  };

  const applyPreset = (preset: CaptionPreset) => {
    const nextClip: Clip = {
      ...clip,
      editingScript: {
        ...es,
        captions: {
          ...es.captions,
          enabled: preset.animation !== "none",
          templateId: preset.templateId,
          fontFamily: preset.fontFamily,
          fontSize: preset.fontSize,
          uppercase: preset.uppercase,
          primaryColor: preset.primaryColor,
          highlightColor: preset.highlightColor,
          secondaryColor: preset.secondaryColor,
          positionY: preset.positionY,
          wordsPerLine: preset.wordsPerLine,
        },
      },
    };
    setClip(nextClip);
    persistEdits(nextClip);
  };

  const findBrollSpots = async () => {
    setBrollLoading(true);
    try {
      const res = await fetch(`/api/clips/${clip.id}/broll/plan`, { method: "POST" });
      if (res.ok) {
        const data = await res.json();
        setBrollSpots(data.spots || []);
      }
    } finally {
      setBrollLoading(false);
    }
  };

  const applyBrollSpots = async () => {
    if (brollSpots.length === 0) return;
    setBrollLoading(true);
    try {
      const res = await fetch(`/api/clips/${clip.id}/broll/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spots: brollSpots, mode: brollMode, layout: brollLayout }),
      });
      if (res.ok) {
        const updated = (await res.json()) as Clip;
        setClip(updated);
        onUpdated(updated);
        setStatusMsg("B-roll added to timeline! Re-render to composite.");
      }
    } finally {
      setBrollLoading(false);
    }
  };

  const generateVoiceover = async () => {
    if (!voText.trim()) return;
    setStatusMsg("Generating AI voiceover...");
    const res = await fetch(`/api/clips/${clip.id}/voiceover`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: voText, voice: voVoice, start_sec: 0, originalVolume: voOrigVol }),
    });
    if (res.ok) {
      const updated = (await res.json()) as Clip;
      setClip(updated);
      setStatusMsg("Voiceover added to timeline!");
    }
  };

  const applyAutoSfx = async () => {
    const res = await fetch(`/api/clips/${clip.id}/auto-sfx`, { method: "POST" });
    if (res.ok) {
      const updated = (await res.json()) as Clip;
      setClip(updated);
      setStatusMsg("Auto SFX placed on timeline!");
    }
  };

  const translateClip = async () => {
    setStatusMsg(`Translating captions to ${targetLang}...`);
    const res = await fetch(`/api/clips/${clip.id}/translate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ targetLang, dubAudio }),
    });
    if (res.ok) {
      const data = await res.json();
      setTranscript(data.transcript);
      setClip(data.clip);
      onUpdated(data.clip, data.transcript);
      setStatusMsg("Translation complete! Re-render to bake subtitles.");
    }
  };

  const splitAtPlayhead = async () => {
    const res = await fetch(`/api/clips/${clip.id}/split?splitSec=${currentTime.toFixed(2)}`, { method: "POST" });
    if (res.ok) {
      setStatusMsg("Clip split into two parts! Return to Results to see both.");
    } else {
      setStatusMsg("Move playhead at least 1.5s away from clip edges to split.");
    }
  };

  const aspectClass =
    es.aspectRatio === "square"
      ? "aspect-square max-w-[380px]"
      : es.aspectRatio === "landscape"
      ? "aspect-video max-w-[540px]"
      : es.aspectRatio === "four-five"
      ? "aspect-[4/5] max-w-[340px]"
      : "aspect-[9/16] max-w-[300px]";

  const activeBroll = (es.brolls || []).find(
    (b) => currentTime >= b.start_sec && currentTime <= b.end_sec
  );

  const handleTrackerMouseDown = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!trackingMode || !previewWrapRef.current) return;
    const rect = previewWrapRef.current.getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    const y = (e.clientY - rect.top) / rect.height;
    setDragBox({ startX: x, startY: y, x, y, w: 0, h: 0 });
  };

  const handleTrackerMouseMove = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!trackingMode || !dragBox || !previewWrapRef.current) return;
    const rect = previewWrapRef.current.getBoundingClientRect();
    const cx = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const cy = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    setDragBox({
      ...dragBox,
      x: Math.min(dragBox.startX, cx),
      y: Math.min(dragBox.startY, cy),
      w: Math.abs(cx - dragBox.startX),
      h: Math.abs(cy - dragBox.startY),
    });
  };

  const handleTrackerMouseUp = async () => {
    if (!trackingMode || !dragBox) return;
    setTrackingMode(false);
    if (dragBox.w > 0.05 && dragBox.h > 0.05) {
      setStatusMsg("Tracking selected subject across frames...");
      const res = await fetch(`/api/clips/${clip.id}/track-subject`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: dragBox.x, y: dragBox.y, w: dragBox.w, h: dragBox.h }),
      });
      if (res.ok) {
        const updated = (await res.json()) as Clip;
        setClip(updated);
        setStatusMsg("Subject tracked! Re-render to apply crop.");
      }
    }
    setDragBox(null);
  };

  return (
    <div className="flex h-screen flex-col bg-[#08090e] text-gray-100">
      {/* Top Bar */}
      <header className="flex items-center justify-between border-b border-white/10 bg-[#0e111a] px-4 py-2.5">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onBack}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs font-medium text-gray-300 hover:bg-white/10"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Results
          </button>
          <div>
            <input
              type="text"
              value={clip.title}
              onChange={(e) => setClip({ ...clip, title: e.target.value })}
              onBlur={() => persistEdits(clip)}
              aria-label="Clip title"
              className="bg-transparent text-sm font-semibold text-white focus:outline-none focus:ring-1 focus:ring-violet-500 rounded px-1"
            />
            <div className="flex items-center gap-2 text-[11px] text-gray-400">
              <span>Virality: <strong className="text-emerald-400">{clip.virality_score}/99</strong></span>
              <span>•</span>
              <span>{clip.duration_sec.toFixed(1)}s</span>
              {saving && <span className="text-violet-400">Saving...</span>}
              {statusMsg && <span className="text-amber-300">• {statusMsg}</span>}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => renderClip("720p")}
            disabled={rendering}
            className="flex items-center gap-1.5 rounded-lg border border-violet-500/40 bg-violet-600/20 px-3 py-1.5 text-xs font-medium text-violet-200 hover:bg-violet-600/30 disabled:opacity-50"
          >
            {rendering ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Wand2 className="h-3.5 w-3.5" />}
            Re-Render
          </button>
          <a
            href={`/api/clips/${clip.id}/srt`}
            className="flex items-center gap-1 rounded-lg border border-white/10 px-2.5 py-1.5 text-xs text-gray-300 hover:bg-white/10"
          >
            .SRT
          </a>
          <a
            href={`/api/clips/${clip.id}/xml`}
            className="flex items-center gap-1.5 rounded-lg border border-white/10 px-3 py-1.5 text-xs text-gray-200 hover:bg-white/10"
            title="Export Premiere Pro / DaVinci Resolve XML + SRT ZIP"
          >
            <FileCode2 className="h-3.5 w-3.5 text-sky-400" />
            Export XML
          </a>
          <a
            href={`/api/clips/${clip.id}/download?resolution=1080p`}
            className="flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 text-xs font-semibold text-white hover:bg-violet-500"
          >
            <Download className="h-3.5 w-3.5" />
            Export 1080p
          </a>
          <a
            href={`/api/clips/${clip.id}/download?resolution=4k`}
            className="flex items-center gap-1 rounded-lg border border-amber-500/40 bg-amber-500/10 px-2.5 py-1.5 text-xs font-medium text-amber-300 hover:bg-amber-500/20"
          >
            4K
          </a>
        </div>
      </header>

      {/* Main 3-Pane Studio */}
      <div className="grid min-h-0 flex-1 grid-cols-12">
        {/* Left: Transcript & Speech Cleanup */}
        <aside className="col-span-4 flex min-h-0 flex-col border-r border-white/10 bg-[#0b0d14]">
          <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 p-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-gray-400">
              Transcript & Speech Cleanup
            </span>
            <div className="flex flex-wrap gap-1.5">
              <button
                type="button"
                onClick={removeAllFillers}
                className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-amber-300 hover:bg-white/10"
              >
                <Eraser className="h-3 w-3" /> Fillers
              </button>
              <button
                type="button"
                onClick={detectBadTakesAndPauses}
                className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-sky-300 hover:bg-white/10"
              >
                <Sparkles className="h-3 w-3" /> Pauses & Bad Takes
              </button>
              <button
                type="button"
                onClick={censorProfanity}
                className="flex items-center gap-1 rounded-md bg-white/5 px-2 py-1 text-[11px] text-rose-300 hover:bg-white/10"
              >
                <ShieldAlert className="h-3 w-3" /> Censor
              </button>
            </div>
          </div>

          <div className="flex items-center justify-between border-b border-white/5 px-3 py-2 text-[11px] text-gray-400">
            <label className="flex items-center gap-2">
              Pause ≥ {pauseThreshold}s
              <input
                type="range"
                min={0.3}
                max={2.0}
                step={0.1}
                value={pauseThreshold}
                onChange={(e) => setPauseThreshold(parseFloat(e.target.value))}
                className="w-20"
              />
            </label>
            <label className="flex cursor-pointer items-center gap-1.5">
              <input
                type="checkbox"
                checked={hideDeleted}
                onChange={(e) => setHideDeleted(e.target.checked)}
              />
              Hide deleted
            </label>
          </div>

          <div className="flex-1 space-y-3 overflow-y-auto p-3">
            {scopedParagraphs.length === 0 && (
              <p className="text-xs text-gray-500">No speech words detected in this clip timeframe.</p>
            )}
            {scopedParagraphs.map((para) => {
              const isBad = badTakes.some((b) => b.paragraph_id === para.id);
              return (
                <div
                  key={para.id}
                  className={`rounded-xl border p-2.5 ${
                    isBad ? "border-amber-500/40 bg-amber-500/5" : "border-white/5 bg-white/[0.02]"
                  }`}
                >
                  <div className="mb-1 flex items-center justify-between text-[10px] text-gray-500">
                    <span>{para.speaker || "Speaker 1"} • {Math.max(0, para.start - clip.start_sec).toFixed(1)}s</span>
                    {isBad && <span className="text-amber-400">Possible retake</span>}
                  </div>
                  <div className="flex flex-wrap gap-1 leading-relaxed">
                    {para.words
                      .filter((w) => !(hideDeleted && w.deleted))
                      .map((w) => {
                        const isActive =
                          clip.start_sec + currentTime >= w.start &&
                          clip.start_sec + currentTime <= w.end;
                        return (
                          <button
                            key={w.id}
                            type="button"
                            onClick={() => {
                              if (videoRef.current) {
                                videoRef.current.currentTime = Math.max(0, w.start - clip.start_sec);
                              }
                            }}
                            onContextMenu={(e) => {
                              e.preventDefault();
                              toggleWordDeleted(w.id);
                            }}
                            title="Click to seek • Right-click to cut/restore word"
                            className={`rounded px-1 py-0.5 text-xs transition ${
                              w.deleted
                                ? "bg-rose-950/50 text-gray-500 line-through"
                                : isActive
                                ? "bg-violet-600 text-white"
                                : w.isFillerWord
                                ? "bg-amber-500/20 text-amber-200 hover:bg-amber-500/30"
                                : w.censored
                                ? "bg-rose-500/20 text-rose-300"
                                : "text-gray-200 hover:bg-white/10"
                            }`}
                          >
                            {w.censored ? "***" : w.word}
                          </button>
                        );
                      })}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="border-t border-white/10 px-3 py-1.5 text-[10px] text-gray-500">
            Tip: Click any word to seek • Right-click any word to cut/restore from final video.
          </div>
        </aside>

        {/* Center: Canvas Video Preview */}
        <main className="col-span-4 flex min-h-0 flex-col items-center justify-between bg-[#06070b] p-4">
          <div className="flex w-full items-center justify-between text-xs text-gray-400">
            <div className="flex items-center gap-2">
              <span className="rounded bg-white/10 px-2 py-0.5 text-[11px] text-gray-200">
                {es.aspectRatio.toUpperCase()}
              </span>
              <span className="rounded bg-white/10 px-2 py-0.5 text-[11px] text-gray-200">
                Layout: {es.layoutMode}
              </span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => setShowSafeZone(!showSafeZone)}
                className={`rounded-lg px-2 py-1 text-[11px] ${
                  showSafeZone ? "bg-violet-600 text-white" : "bg-white/5 text-gray-300"
                }`}
              >
                Safe Zone
              </button>
              <button
                type="button"
                onClick={() => setTrackingMode(!trackingMode)}
                className={`flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] ${
                  trackingMode ? "bg-amber-500 text-black font-semibold" : "bg-white/5 text-gray-300"
                }`}
              >
                <Crosshair className="h-3 w-3" /> Track Subject
              </button>
            </div>
          </div>

          {/* Video Canvas */}
          <div
            ref={previewWrapRef}
            onMouseDown={handleTrackerMouseDown}
            onMouseMove={handleTrackerMouseMove}
            onMouseUp={handleTrackerMouseUp}
            className={`relative my-2 w-full overflow-hidden rounded-2xl border border-white/15 bg-black shadow-2xl ${aspectClass} ${
              trackingMode ? "cursor-crosshair ring-2 ring-amber-400" : ""
            }`}
          >
            {clip.previewUrl ? (
              <video
                ref={videoRef}
                src={clip.previewUrl}
                onTimeUpdate={(e) => setCurrentTime(e.currentTarget.currentTime)}
                onPlay={() => setPlaying(true)}
                onPause={() => setPlaying(false)}
                className="h-full w-full object-contain"
                playsInline
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-gray-500">
                No preview rendered yet
              </div>
            )}

            {/* Live Headline Preview Overlay (only shown if no rendered video yet or user has unbaked style edits) */}
            {(!clip.previewUrl || styleDirty) && es.headline?.enabled && es.headline?.text && (es.headline?.persistent || es.layoutMode === "card" || currentTime < 4.5) && (
              <div
                className={`pointer-events-none absolute top-[6%] left-3 right-3 text-center text-xs font-extrabold uppercase tracking-tight ${
                  es.headline.colorStyle === "red"
                    ? "text-[#FF2E54] drop-shadow-[0_2px_4px_rgba(0,0,0,0.95)]"
                    : es.headline.colorStyle === "red-banner"
                    ? "rounded-lg bg-red-600/95 px-3 py-1.5 text-white shadow-lg"
                    : es.headline.colorStyle === "yellow-banner"
                    ? "rounded-lg bg-yellow-400/95 px-3 py-1.5 text-gray-950 shadow-lg"
                    : "text-[#FFE600] drop-shadow-[0_2px_4px_rgba(0,0,0,0.95)]"
                }`}
              >
                {es.headline.text}
              </div>
            )}

            {/* Live B-Roll indicator */}
            {activeBroll && (
              <div className="pointer-events-none absolute top-3 left-3 rounded-md bg-emerald-600/80 px-2 py-0.5 text-[10px] font-medium text-white">
                B-Roll: {activeBroll.query} ({activeBroll.layout})
              </div>
            )}

            {/* Live Caption Overlay Preview (only shown if no rendered video yet or user has unbaked style edits) */}
            {(!clip.previewUrl || styleDirty) && es.captions?.enabled && activeCaptionWords && (
              <div
                className="pointer-events-none absolute left-4 right-4 text-center font-extrabold drop-shadow-[0_2px_6px_rgba(0,0,0,0.95)]"
                style={{ top: `${es.captions.positionY ?? 72}%`, fontSize: "15px" }}
              >
                {activeCaptionWords.chunk.map((cw) => {
                  const active = activeCaptionWords.absT >= cw.start && activeCaptionWords.absT <= cw.end;
                  const txt = cw.censored ? "***" : es.captions.uppercase ? cw.word.toUpperCase() : cw.word;
                  return (
                    <span
                      key={cw.id}
                      style={{ color: active ? es.captions.highlightColor : es.captions.primaryColor }}
                      className="mx-1 inline-block"
                    >
                      {txt}
                    </span>
                  );
                })}
              </div>
            )}

            {/* TikTok/Reels Safe Zone Guide */}
            {showSafeZone && (
              <div className="pointer-events-none absolute inset-0 border-2 border-dashed border-amber-400/50">
                <div className="absolute right-2 bottom-16 flex flex-col gap-3 text-[9px] text-amber-300/80">
                  <div className="h-7 w-7 rounded-full border border-amber-400/50 bg-amber-400/10" />
                  <div className="h-7 w-7 rounded-full border border-amber-400/50 bg-amber-400/10" />
                  <div className="h-7 w-7 rounded-full border border-amber-400/50 bg-amber-400/10" />
                </div>
                <div className="absolute bottom-3 left-3 right-12 h-12 rounded border border-amber-400/40 bg-amber-400/10 px-2 py-1 text-[9px] text-amber-200">
                  Platform UI Safe Zone
                </div>
              </div>
            )}

            {/* Subject Tracker Selection Box */}
            {dragBox && (
              <div
                className="pointer-events-none absolute border-2 border-amber-400 bg-amber-400/20"
                style={{
                  left: `${dragBox.x * 100}%`,
                  top: `${dragBox.y * 100}%`,
                  width: `${dragBox.w * 100}%`,
                  height: `${dragBox.h * 100}%`,
                }}
              />
            )}
          </div>

          {/* Playback Controls */}
          <div className="flex w-full items-center gap-3 rounded-xl border border-white/10 bg-[#0e111a] px-3 py-2">
            <button
              type="button"
              onClick={() => {
                if (!videoRef.current) return;
                if (videoRef.current.paused) videoRef.current.play();
                else videoRef.current.pause();
              }}
              className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-600 text-white hover:bg-violet-500"
              aria-label={playing ? "Pause" : "Play"}
            >
              {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </button>
            <input
              type="range"
              min={0}
              max={clip.duration_sec || 30}
              step={0.05}
              value={currentTime}
              onChange={(e) => {
                const t = parseFloat(e.target.value);
                setCurrentTime(t);
                if (videoRef.current) videoRef.current.currentTime = t;
              }}
              className="flex-1"
            />
            <span className="font-mono text-xs text-gray-400">
              {currentTime.toFixed(1)}s / {clip.duration_sec.toFixed(1)}s
            </span>
            <button
              type="button"
              onClick={splitAtPlayhead}
              title="Split clip into 2 at playhead"
              className="flex items-center gap-1 rounded-lg border border-white/10 px-2 py-1 text-[11px] text-gray-300 hover:bg-white/10"
            >
              <Scissors className="h-3 w-3" /> Split
            </button>
          </div>
        </main>

        {/* Right: Inspector Panel */}
        <aside className="col-span-4 flex min-h-0 flex-col border-l border-white/10 bg-[#0b0d14]">
          <div className="grid grid-cols-4 border-b border-white/10 text-xs">
            {(
              [
                { id: "captions", label: "Captions", icon: Captions },
                { id: "layout", label: "Layout", icon: LayoutGrid },
                { id: "broll", label: "B-Roll", icon: Film },
                { id: "enhance", label: "AI Enhance", icon: Sparkles },
              ] as const
            ).map((item) => {
              const Icon = item.icon;
              return (
                <button
                  key={item.id}
                  type="button"
                  onClick={() => setTab(item.id)}
                  className={`flex items-center justify-center gap-1.5 py-3 font-medium transition ${
                    tab === item.id
                      ? "border-b-2 border-violet-500 bg-white/[0.03] text-white"
                      : "text-gray-400 hover:text-gray-200"
                  }`}
                >
                  <Icon className="h-3.5 w-3.5" />
                  {item.label}
                </button>
              );
            })}
          </div>

          <div className="flex-1 space-y-5 overflow-y-auto p-4 text-xs">
            {tab === "captions" && (
              <>
                <div>
                  <h3 className="mb-2 font-semibold text-gray-200">Animated Presets</h3>
                  <div className="grid grid-cols-3 gap-2">
                    {captionPresets.map((pr) => {
                      const active = es.captions?.templateId === pr.templateId;
                      return (
                        <button
                          key={pr.templateId}
                          type="button"
                          onClick={() => applyPreset(pr)}
                          className={`rounded-xl border p-2 text-left transition ${
                            active
                              ? "border-violet-500 bg-violet-600/20"
                              : "border-white/10 bg-white/[0.02] hover:border-white/25"
                          }`}
                        >
                          <div
                            className="mb-1 truncate text-xs font-extrabold"
                            style={{ color: pr.highlightColor }}
                          >
                            {pr.uppercase ? pr.name.toUpperCase() : pr.name}
                          </div>
                          <div className="text-[10px] text-gray-400">{pr.fontFamily}</div>
                        </button>
                      );
                    })}
                  </div>
                </div>

                <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <div className="flex items-center justify-between">
                    <span>Font Size ({es.captions.fontSize}px)</span>
                    <input
                      type="range"
                      min={32}
                      max={92}
                      value={es.captions.fontSize}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, captions: { ...es.captions, fontSize: parseInt(e.target.value, 10) } } };
                        setClip(nc);
                      }}
                      onMouseUp={() => persistEdits(clip)}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Vertical Position ({es.captions.positionY ?? 72}%)</span>
                    <input
                      type="range"
                      min={15}
                      max={88}
                      value={es.captions.positionY ?? 72}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, captions: { ...es.captions, positionY: parseInt(e.target.value, 10) } } };
                        setClip(nc);
                      }}
                      onMouseUp={() => persistEdits(clip)}
                    />
                  </div>
                  <div className="flex items-center justify-between">
                    <span>Highlight Color</span>
                    <input
                      type="color"
                      value={es.captions.highlightColor}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, captions: { ...es.captions, highlightColor: e.target.value } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </div>
                  <label className="flex items-center justify-between">
                    <span>UPPERCASE</span>
                    <input
                      type="checkbox"
                      checked={es.captions.uppercase}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, captions: { ...es.captions, uppercase: e.target.checked } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </label>
                </div>

                <div className="space-y-2 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <div className="flex items-center gap-1.5 font-semibold text-gray-200">
                    <Languages className="h-3.5 w-3.5 text-violet-400" /> Translate & Dub Subtitles
                  </div>
                  <div className="flex items-center gap-2">
                    <select
                      value={targetLang}
                      onChange={(e) => setTargetLang(e.target.value)}
                      className="flex-1 rounded-lg border border-white/10 bg-[#08090e] px-2 py-1.5 text-xs"
                    >
                      <option value="es">Spanish</option>
                      <option value="fr">French</option>
                      <option value="de">German</option>
                      <option value="pt">Portuguese</option>
                      <option value="hi">Hindi</option>
                      <option value="ja">Japanese</option>
                    </select>
                    <button
                      type="button"
                      onClick={translateClip}
                      className="rounded-lg bg-violet-600 px-3 py-1.5 font-medium text-white hover:bg-violet-500"
                    >
                      Translate
                    </button>
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-gray-400">
                    <input type="checkbox" checked={dubAudio} onChange={(e) => setDubAudio(e.target.checked)} />
                    Also generate dubbed audio track
                  </label>
                </div>
              </>
            )}

            {tab === "layout" && (
              <>
                <div>
                  <h3 className="mb-2 font-semibold text-gray-200">Aspect Ratio</h3>
                  <div className="grid grid-cols-2 gap-2">
                    {(
                      [
                        { id: "portrait", label: "9:16 Portrait" },
                        { id: "square", label: "1:1 Square" },
                        { id: "four-five", label: "4:5 Social" },
                        { id: "landscape", label: "16:9 Landscape" },
                      ] as const
                    ).map((ar) => (
                      <button
                        key={ar.id}
                        type="button"
                        onClick={() => {
                          const nc = { ...clip, editingScript: { ...es, aspectRatio: ar.id } };
                          setClip(nc);
                          persistEdits(nc);
                        }}
                        className={`rounded-xl border px-3 py-2 text-left font-medium ${
                          es.aspectRatio === ar.id
                            ? "border-violet-500 bg-violet-600/20 text-white"
                            : "border-white/10 bg-white/[0.02] text-gray-300"
                        }`}
                      >
                        {ar.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <h3 className="mb-2 font-semibold text-gray-200">AI Framing Layouts</h3>
                  <div className="space-y-2">
                    {[
                      { id: "card", label: "Center Card (3:4 / 1:1 + Top Headline)" },
                      { id: "auto", label: "Auto Layout" },
                      { id: "fill", label: "Fill (Active Speaker Tracked)" },
                      { id: "fit", label: "Fit (Blurred Padding)" },
                      { id: "split", label: "Split (2 Speakers Stacked)" },
                      { id: "screenshare", label: "Screenshare (Slide Top + Speaker)" },
                      { id: "gameplay", label: "Gameplay (30% Cam + 70% Game)" },
                    ].map((l) => (
                      <button
                        key={l.id}
                        type="button"
                        onClick={() => {
                          const nc = {
                            ...clip,
                            editingScript: {
                              ...es,
                              layoutMode: l.id,
                              headline: {
                                ...(es.headline || { enabled: true, text: clip.headline }),
                                persistent: l.id === "card",
                              },
                            },
                          };
                          setClip(nc);
                          persistEdits(nc);
                        }}
                        className={`flex w-full items-center justify-between rounded-xl border px-3 py-2.5 text-left ${
                          es.layoutMode === l.id
                            ? "border-violet-500 bg-violet-600/20 text-white"
                            : "border-white/10 bg-white/[0.02] text-gray-300"
                        }`}
                      >
                        <span>{l.label}</span>
                        {es.layoutMode === l.id && <Check className="h-4 w-4 text-violet-400" />}
                      </button>
                    ))}
                  </div>
                </div>

                {es.layoutMode === "card" && (
                  <div>
                    <h3 className="mb-2 font-semibold text-gray-200">Center Video Frame Ratio</h3>
                    <div className="grid grid-cols-3 gap-2">
                      {(["3:4", "1:1", "4:3"] as const).map((ratio) => (
                        <button
                          key={ratio}
                          type="button"
                          onClick={() => {
                            const nc = { ...clip, editingScript: { ...es, cardFrameRatio: ratio } };
                            setClip(nc);
                            persistEdits(nc);
                          }}
                          className={`rounded-xl border px-3 py-2 text-center font-semibold ${
                            (es.cardFrameRatio || "3:4") === ratio
                              ? "border-amber-400 bg-amber-400/20 text-amber-200"
                              : "border-white/10 bg-white/[0.02] text-gray-300"
                          }`}
                        >
                          {ratio}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}

            {tab === "broll" && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <div>
                    <h3 className="font-semibold text-gray-200">AI B-Roll Planner</h3>
                    <p className="text-[11px] text-gray-400">Scan transcript and generate or fetch contextual visuals.</p>
                  </div>
                  <button
                    type="button"
                    onClick={findBrollSpots}
                    disabled={brollLoading}
                    className="flex items-center gap-1.5 rounded-lg bg-violet-600 px-3 py-1.5 font-medium text-white hover:bg-violet-500 disabled:opacity-50"
                  >
                    {brollLoading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
                    Find Spots
                  </button>
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <select
                    value={brollMode}
                    onChange={(e) => setBrollMode(e.target.value as "ai_image" | "stock_video")}
                    className="rounded-lg border border-white/10 bg-[#08090e] px-2.5 py-1.5"
                  >
                    <option value="ai_image">AI Image</option>
                    <option value="stock_video">Stock Video (Pexels)</option>
                  </select>
                  <select
                    value={brollLayout}
                    onChange={(e) => setBrollLayout(e.target.value as "fill" | "pip")}
                    className="rounded-lg border border-white/10 bg-[#08090e] px-2.5 py-1.5"
                  >
                    <option value="fill">Fill Frame</option>
                    <option value="pip">Picture-in-Picture</option>
                  </select>
                </div>

                {brollSpots.length > 0 && (
                  <div className="space-y-2">
                    {brollSpots.map((sp, i) => (
                      <div key={i} className="rounded-xl border border-violet-500/30 bg-violet-500/5 p-2.5">
                        <div className="flex items-center justify-between font-medium text-violet-200">
                          <span>{sp.query}</span>
                          <span>{sp.start_sec.toFixed(1)}s – {sp.end_sec.toFixed(1)}s</span>
                        </div>
                        <p className="mt-1 text-[11px] text-gray-400">{sp.reason}</p>
                      </div>
                    ))}
                    <button
                      type="button"
                      onClick={applyBrollSpots}
                      disabled={brollLoading}
                      className="flex w-full items-center justify-center gap-1.5 rounded-xl bg-emerald-600 py-2 font-semibold text-white hover:bg-emerald-500"
                    >
                      <Plus className="h-4 w-4" /> Add Suggested B-Rolls ({brollSpots.length * 3} cr)
                    </button>
                  </div>
                )}

                <div>
                  <h4 className="mb-2 font-medium text-gray-300">Active B-Roll Timeline Items</h4>
                  {(es.brolls || []).length === 0 ? (
                    <p className="text-[11px] text-gray-500">No B-roll clips added yet.</p>
                  ) : (
                    <div className="space-y-2">
                      {(es.brolls || []).map((b) => (
                        <div key={b.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] p-2">
                          <div>
                            <div className="font-medium text-gray-200">{b.query}</div>
                            <div className="text-[10px] text-gray-400">
                              {b.start_sec.toFixed(1)}s–{b.end_sec.toFixed(1)}s • {b.layout} ({b.source})
                            </div>
                          </div>
                          <button
                            type="button"
                            onClick={() => {
                              const nc = { ...clip, editingScript: { ...es, brolls: (es.brolls || []).filter((x) => x.id !== b.id) } };
                              setClip(nc);
                              persistEdits(nc);
                            }}
                            className="rounded p-1 text-gray-400 hover:bg-white/10 hover:text-rose-400"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}

            {tab === "enhance" && (
              <div className="space-y-4">
                {/* Auto Headline */}
                <div className="space-y-2 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <label className="flex items-center justify-between font-semibold text-gray-200">
                    <span>Auto Headline Overlay</span>
                    <input
                      type="checkbox"
                      checked={es.headline?.enabled ?? false}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, headline: { ...(es.headline || { text: clip.headline }), enabled: e.target.checked } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </label>
                  <input
                    type="text"
                    value={es.headline?.text || ""}
                    onChange={(e) => {
                      const nc = { ...clip, editingScript: { ...es, headline: { ...(es.headline || { enabled: true }), text: e.target.value } } };
                      setClip(nc);
                    }}
                    onBlur={() => persistEdits(clip)}
                    placeholder="Scroll-stopping top headline..."
                    className="w-full rounded-lg border border-white/10 bg-[#08090e] px-2.5 py-1.5 text-xs"
                  />
                  <div className="grid grid-cols-2 gap-1.5 pt-1">
                    {(
                      [
                        { id: "yellow", label: "Bold Yellow" },
                        { id: "red", label: "Bold Red" },
                        { id: "red-banner", label: "Red Banner" },
                        { id: "yellow-banner", label: "Yellow Banner" },
                      ] as const
                    ).map((st) => (
                      <button
                        key={st.id}
                        type="button"
                        onClick={() => {
                          const nc = { ...clip, editingScript: { ...es, headline: { ...(es.headline || { enabled: true, text: clip.headline }), colorStyle: st.id } } };
                          setClip(nc);
                          persistEdits(nc);
                        }}
                        className={`rounded-lg border px-2 py-1 text-[11px] font-medium ${
                          (es.headline?.colorStyle || "yellow") === st.id
                            ? "border-amber-400 bg-amber-400/20 text-amber-200"
                            : "border-white/10 bg-black/30 text-gray-400"
                        }`}
                      >
                        {st.label}
                      </button>
                    ))}
                  </div>
                  <label className="flex items-center justify-between pt-1 text-[11px] text-gray-400">
                    <span>Keep headline visible for whole clip</span>
                    <input
                      type="checkbox"
                      checked={es.headline?.persistent ?? es.layoutMode === "card"}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, headline: { ...(es.headline || { enabled: true, text: clip.headline }), persistent: e.target.checked } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </label>
                </div>

                {/* Speech Enhancement & Auto Color */}
                <div className="space-y-3 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <label className="flex items-center justify-between font-semibold text-gray-200">
                    <span className="flex items-center gap-1.5"><Volume2 className="h-3.5 w-3.5 text-emerald-400" /> Speech Enhancement</span>
                    <input
                      type="checkbox"
                      checked={es.enhance?.speechEnhance ?? false}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, enhance: { ...es.enhance, speechEnhance: e.target.checked } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </label>
                  <div className="flex items-center justify-between text-[11px] text-gray-400">
                    <span>Noise Reduction</span>
                    <input
                      type="range"
                      min={0.2}
                      max={1.0}
                      step={0.1}
                      value={es.enhance?.noiseReduction ?? 0.7}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, enhance: { ...es.enhance, noiseReduction: parseFloat(e.target.value) } } };
                        setClip(nc);
                      }}
                      onMouseUp={() => persistEdits(clip)}
                    />
                  </div>

                  <label className="flex items-center justify-between border-t border-white/5 pt-2.5 font-semibold text-gray-200">
                    <span>Auto Color Correction</span>
                    <input
                      type="checkbox"
                      checked={es.enhance?.autoColor ?? false}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, enhance: { ...es.enhance, autoColor: e.target.checked } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </label>

                  <label className="flex items-center justify-between border-t border-white/5 pt-2.5 font-semibold text-amber-200">
                    <span>Sharp HDR (Crisp Viral Look)</span>
                    <input
                      type="checkbox"
                      checked={es.enhance?.sharpHdr ?? false}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, enhance: { ...es.enhance, sharpHdr: e.target.checked } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                    />
                  </label>
                </div>

                {/* Built-in Background Music Selector */}
                <div className="space-y-2.5 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <div className="flex items-center justify-between">
                    <span className="flex items-center gap-1.5 font-semibold text-gray-200">
                      <Music className="h-3.5 w-3.5 text-fuchsia-400" /> Background Music
                    </span>
                    <span className="text-[10px] text-gray-400">
                      Vol: {Math.round((es.music?.volume ?? 0.12) * 100)}%
                    </span>
                  </div>
                  <div className="space-y-1.5">
                    <button
                      type="button"
                      onClick={() => {
                        const nc = { ...clip, editingScript: { ...es, music: { trackId: null, path: null, volume: es.music?.volume ?? 0.12 } } };
                        setClip(nc);
                        persistEdits(nc);
                      }}
                      className={`flex w-full items-center justify-between rounded-lg border px-2.5 py-1.5 text-left text-[11px] ${
                        !es.music?.path
                          ? "border-violet-500 bg-violet-600/20 text-white"
                          : "border-white/10 bg-[#08090e] text-gray-400"
                      }`}
                    >
                      <span>No Background Music</span>
                      {!es.music?.path && <Check className="h-3.5 w-3.5 text-violet-400" />}
                    </button>
                    {musicTracks.map((tr) => {
                      const active = es.music?.path === tr.path || es.music?.trackId === tr.id;
                      const isPreviewing = previewTrackId === tr.id;
                      return (
                        <div
                          key={tr.id}
                          className={`flex items-center justify-between rounded-lg border px-2.5 py-1.5 text-[11px] ${
                            active
                              ? "border-fuchsia-500 bg-fuchsia-600/20 text-white"
                              : "border-white/10 bg-[#08090e] text-gray-300"
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => {
                              const nc = { ...clip, editingScript: { ...es, music: { trackId: tr.id, path: tr.path, volume: es.music?.volume ?? 0.12 } } };
                              setClip(nc);
                              persistEdits(nc);
                            }}
                            className="flex-1 text-left"
                          >
                            <div className="font-medium">{tr.name}</div>
                            <div className="text-[10px] text-gray-400">{tr.mood}</div>
                          </button>
                          <button
                            type="button"
                            onClick={() => {
                              if (isPreviewing) {
                                musicPreviewRef.current?.pause();
                                setPreviewTrackId(null);
                              } else {
                                musicPreviewRef.current?.pause();
                                const audio = new Audio(tr.url);
                                audio.volume = 0.4;
                                audio.loop = true;
                                audio.play().catch(() => {});
                                musicPreviewRef.current = audio;
                                setPreviewTrackId(tr.id);
                              }
                            }}
                            className="ml-2 rounded bg-white/10 px-2 py-1 text-[10px] text-gray-200 hover:bg-white/20"
                          >
                            {isPreviewing ? "Stop" : "Play"}
                          </button>
                        </div>
                      );
                    })}
                  </div>
                  <div className="flex items-center justify-between pt-1 text-[11px] text-gray-400">
                    <span>Music Level</span>
                    <input
                      type="range"
                      min={0.04}
                      max={0.4}
                      step={0.02}
                      value={es.music?.volume ?? 0.12}
                      onChange={(e) => {
                        const nc = { ...clip, editingScript: { ...es, music: { ...(es.music || {}), volume: parseFloat(e.target.value) } } };
                        setClip(nc);
                      }}
                      onMouseUp={() => persistEdits(clip)}
                    />
                  </div>
                  <label className="mt-1 flex cursor-pointer items-center justify-center gap-1.5 rounded-lg border border-dashed border-white/15 bg-[#08090e] py-1.5 text-[11px] text-gray-300 hover:border-fuchsia-400">
                    <Plus className="h-3.5 w-3.5 text-fuchsia-400" />
                    <span>Upload Custom Song (.mp3 / .wav)</span>
                    <input
                      type="file"
                      accept="audio/*"
                      className="hidden"
                      onChange={async (e) => {
                        const f = e.target.files?.[0];
                        if (!f) return;
                        const fd = new FormData();
                        fd.append("file", f);
                        fd.append("kind", "music");
                        const res = await fetch("/api/assets/upload", { method: "POST", body: fd });
                        if (res.ok) {
                          const data = await res.json();
                          const nc = { ...clip, editingScript: { ...es, music: { trackId: "custom", path: data.path, volume: es.music?.volume ?? 0.12 } } };
                          setClip(nc);
                          persistEdits(nc);
                          setStatusMsg(`Added custom song: ${f.name} — click Re-Render to bake.`);
                        }
                      }}
                    />
                  </label>
                </div>

                {/* Auto SFX */}
                <div className="flex items-center justify-between rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <div>
                    <div className="font-semibold text-gray-200">Auto Sound Effects (SFX)</div>
                    <div className="text-[11px] text-gray-400">{(es.sfx || []).length} SFX cues placed</div>
                  </div>
                  <button
                    type="button"
                    onClick={applyAutoSfx}
                    className="rounded-lg bg-violet-600 px-3 py-1.5 font-medium text-white hover:bg-violet-500"
                  >
                    Add Auto SFX (~7/m)
                  </button>
                </div>

                {/* AI Voiceover */}
                <div className="space-y-2 rounded-xl border border-white/10 bg-white/[0.02] p-3">
                  <div className="flex items-center gap-1.5 font-semibold text-gray-200">
                    <Mic className="h-3.5 w-3.5 text-sky-400" /> AI Voiceover / Hook
                  </div>
                  <textarea
                    rows={2}
                    value={voText}
                    onChange={(e) => setVoText(e.target.value)}
                    placeholder="Type an opening hook or narration..."
                    className="w-full rounded-lg border border-white/10 bg-[#08090e] p-2 text-xs"
                  />
                  <div className="flex items-center gap-2">
                    <select
                      value={voVoice}
                      onChange={(e) => setVoVoice(e.target.value)}
                      className="rounded-lg border border-white/10 bg-[#08090e] px-2 py-1 text-xs"
                    >
                      <option value="Samantha">Samantha (macOS)</option>
                      <option value="Daniel">Daniel (macOS UK)</option>
                      <option value="Alex">Alex (macOS)</option>
                      <option value="21m00Tcm4TlvDq8ikWAM">Rachel (ElevenLabs)</option>
                    </select>
                    <input
                      type="range"
                      min={0}
                      max={1}
                      step={0.05}
                      value={voOrigVol}
                      onChange={(e) => setVoOrigVol(parseFloat(e.target.value))}
                      title="Original audio volume during voiceover"
                      className="flex-1"
                    />
                    <button
                      type="button"
                      onClick={generateVoiceover}
                      className="rounded-lg bg-sky-600 px-3 py-1.5 font-medium text-white hover:bg-sky-500"
                    >
                      Generate (3 cr)
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* Bottom Multi-Track Timeline */}
      <footer className="border-t border-white/10 bg-[#0e111a] px-4 py-2.5">
        <div className="mb-1.5 flex items-center justify-between text-[11px] text-gray-400">
          <span>Multi-Track Timeline ({clip.start_sec.toFixed(1)}s – {clip.end_sec.toFixed(1)}s)</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => {
                const ns = Math.max(0, clip.start_sec - 5);
                const nc = { ...clip, start_sec: ns, duration_sec: clip.end_sec - ns };
                setClip(nc);
                persistEdits(nc);
              }}
              className="rounded bg-white/5 px-2 py-0.5 hover:bg-white/10"
            >
              -5s Start
            </button>
            <button
              type="button"
              onClick={() => {
                const ne = Math.min(initialProject.duration_sec || clip.end_sec + 5, clip.end_sec + 5);
                const nc = { ...clip, end_sec: ne, duration_sec: ne - clip.start_sec };
                setClip(nc);
                persistEdits(nc);
              }}
              className="rounded bg-white/5 px-2 py-0.5 hover:bg-white/10"
            >
              +5s End
            </button>
          </div>
        </div>
        <div className="relative space-y-1 rounded-xl border border-white/10 bg-[#08090e] p-2 text-[10px]">
          {/* Playhead line */}
          <div
            className="pointer-events-none absolute top-0 bottom-0 z-10 w-0.5 bg-rose-500"
            style={{ left: `${Math.min(100, Math.max(0, (currentTime / Math.max(1, clip.duration_sec)) * 100))}%` }}
          />
          <div className="flex items-center gap-2">
            <span className="w-16 text-gray-500">Video</span>
            <div className="h-5 flex-1 rounded bg-violet-600/30 border border-violet-500/40 px-2 leading-5 text-violet-200 truncate">
              {clip.title} ({es.layoutMode})
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-16 text-gray-500">Captions</span>
            <div className="h-4 flex-1 rounded bg-emerald-600/20 border border-emerald-500/30 px-2 leading-4 text-emerald-300">
              {es.captions?.enabled ? es.captions.templateId.replace("preset-fancy-", "") : "Disabled"}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-16 text-gray-500">B-Roll</span>
            <div className="relative h-4 flex-1 rounded bg-white/[0.03]">
              {(es.brolls || []).map((b) => {
                const left = (b.start_sec / Math.max(1, clip.duration_sec)) * 100;
                const width = ((b.end_sec - b.start_sec) / Math.max(1, clip.duration_sec)) * 100;
                return (
                  <div
                    key={b.id}
                    style={{ left: `${left}%`, width: `${Math.max(4, width)}%` }}
                    className="absolute top-0 bottom-0 rounded bg-sky-500/40 border border-sky-400/60 px-1 truncate text-sky-100"
                  >
                    {b.query}
                  </div>
                );
              })}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-16 text-gray-500">Audio/SFX</span>
            <div className="relative h-4 flex-1 rounded bg-white/[0.03] px-2 text-amber-300">
              {es.enhance?.speechEnhance ? "Voice Enhanced • " : ""}
              {es.voiceover?.audioPath ? "AI Voiceover • " : ""}
              {(es.sfx || []).map((s) => `${s.name}@${s.t}s`).join(", ") || "Original Audio"}
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
