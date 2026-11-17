"use client";

import { useCallback, useEffect, useState } from "react";
import {
  CalendarDays,
  CheckSquare,
  ChevronRight,
  Clock,
  Coins,
  Copy,
  Download,
  FileCode2,
  Film,
  FolderOpen,
  Grid,
  KeyRound,
  Link2,
  List,
  Loader2,
  Palette,
  PlayCircle,
  RefreshCw,
  Scissors,
  Sparkles,
  Trash2,
  Upload,
  Wand2,
} from "lucide-react";
import ApiKeysDialog from "@/components/ApiKeysDialog";
import BrandKitView from "@/components/BrandKitView";
import CalendarView from "@/components/CalendarView";
import ClipEditor from "@/components/ClipEditor";
import CreditsDialog from "@/components/CreditsDialog";
import {
  BrandKit,
  CaptionPreset,
  Clip,
  CreditEstimate,
  CreditWallet,
  HealthStatus,
  Project,
  Recipe,
  ScheduledPost,
} from "@/lib/types";

type NavTab = "dashboard" | "results" | "brand" | "calendar";

export default function OClipHome() {
  const [nav, setNav] = useState<NavTab>("dashboard");
  const [health, setHealth] = useState<HealthStatus | null>(null);
  const [keysOpen, setKeysOpen] = useState(false);
  const [wallet, setWallet] = useState<CreditWallet | null>(null);
  const [creditsOpen, setCreditsOpen] = useState(false);
  const [creditEstimate, setCreditEstimate] = useState<CreditEstimate | null>(null);
  const [estMinutes, setEstMinutes] = useState(5);

  const [genres, setGenres] = useState<string[]>(["Auto"]);
  const [clipDurations, setClipDurations] = useState<{ id: string; label: string; range: number[] }[]>([]);
  const [captionPresets, setCaptionPresets] = useState<CaptionPreset[]>([]);
  const [recipes, setRecipes] = useState<Recipe[]>([]);
  const [brandKits, setBrandKits] = useState<BrandKit[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [allClips, setAllClips] = useState<Clip[]>([]);
  const [posts, setPosts] = useState<ScheduledPost[]>([]);
  const [collections, setCollections] = useState<{ id: string; name: string; clipIds: string[] }[]>([]);

  // Active project & editor
  const [activeProject, setActiveProject] = useState<Project | null>(null);
  const [projectClips, setProjectClips] = useState<Clip[]>([]);
  const [editingClip, setEditingClip] = useState<Clip | null>(null);
  const [viewMode, setViewMode] = useState<"grid" | "list">("grid");
  const [sortBy, setSortBy] = useState<"score" | "chrono">("score");
  const [selectedClipIds, setSelectedClipIds] = useState<string[]>([]);

  // Quick-Start / Submit form state
  const [videoUrl, setVideoUrl] = useState("");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [srtFile, setSrtFile] = useState<File | null>(null);
  const [projectTitle, setProjectTitle] = useState("");
  const [selectedRecipeId, setSelectedRecipeId] = useState("recipe-clip-long");
  const [selectedKitId, setSelectedKitId] = useState("kit-default");
  const [clipPrompt, setClipPrompt] = useState("");
  const [genre, setGenre] = useState("Auto");
  const [durationId, setDurationId] = useState("auto");
  const [sourceLang, setSourceLang] = useState("auto");
  const [startSec, setStartSec] = useState("");
  const [endSec, setEndSec] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [repromptText, setRepromptText] = useState("");

  const loadBootstrap = useCallback(async () => {
    const [hRes, pRes, rRes, kRes, prRes, cRes, sRes, colRes, crRes] = await Promise.all([
      fetch("/api/health"),
      fetch("/api/presets"),
      fetch("/api/recipes"),
      fetch("/api/brand-kits"),
      fetch("/api/projects"),
      fetch("/api/clips"),
      fetch("/api/schedule"),
      fetch("/api/collections"),
      fetch("/api/credits"),
    ]);
    if (hRes.ok) setHealth(await hRes.json());
    if (crRes.ok) setWallet(await crRes.json());
    if (pRes.ok) {
      const pd = await pRes.json();
      setGenres(pd.genres || []);
      setClipDurations(pd.clipDurations || []);
      setCaptionPresets(pd.captionPresets || []);
    }
    if (rRes.ok) setRecipes((await rRes.json()).recipes || []);
    if (kRes.ok) setBrandKits((await kRes.json()).brandKits || []);
    if (prRes.ok) setProjects((await prRes.json()).projects || []);
    if (cRes.ok) setAllClips((await cRes.json()).clips || []);
    if (sRes.ok) setPosts((await sRes.json()).posts || []);
    if (colRes.ok) setCollections((await colRes.json()).collections || []);
  }, []);

  useEffect(() => {
    loadBootstrap();
  }, [loadBootstrap]);

  useEffect(() => {
    const selRecipe = recipes.find((r) => r.id === selectedRecipeId);
    const sSec = startSec ? parseFloat(startSec) : undefined;
    const eSec = endSec ? parseFloat(endSec) : undefined;
    fetch("/api/credits/estimate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        recipeId: selectedRecipeId,
        durationSec: Math.max(30, estMinutes * 60),
        hasPrompt: Boolean(clipPrompt.trim()),
        hasCustomSrt: Boolean(srtFile),
        startSec: sSec,
        endSec: eSec,
        renderPref: selRecipe?.settings || null,
      }),
    })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setCreditEstimate(d))
      .catch(() => {});
  }, [selectedRecipeId, estMinutes, clipPrompt, srtFile, startSec, endSec, recipes]);

  const openProjectResults = useCallback(async (projectId: string) => {
    const res = await fetch(`/api/projects/${projectId}`);
    if (res.ok) {
      const data = await res.json();
      setActiveProject(data.project);
      setProjectClips(data.clips || []);
      setNav("results");
    }
  }, []);

  // Poll active project while processing
  useEffect(() => {
    if (!activeProject) return;
    if (activeProject.stage === "completed" || activeProject.stage === "failed") return;
    const timer = setInterval(async () => {
      const res = await fetch(`/api/projects/${activeProject.id}`);
      if (res.ok) {
        const data = await res.json();
        setActiveProject(data.project);
        setProjectClips(data.clips || []);
        if (data.project.stage === "completed" || data.project.stage === "failed") {
          loadBootstrap();
        }
      }
    }, 2000);
    return () => clearInterval(timer);
  }, [activeProject, loadBootstrap]);

  const handleSubmitProject = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!videoUrl.trim() && !uploadFile) return;
    setSubmitting(true);
    try {
      const recipe = recipes.find((r) => r.id === selectedRecipeId);
      const durObj = clipDurations.find((d) => d.id === durationId);
      const fd = new FormData();
      fd.append("title", projectTitle.trim() || uploadFile?.name || "Untitled Project");
      if (videoUrl.trim()) fd.append("videoUrl", videoUrl.trim());
      if (uploadFile) fd.append("file", uploadFile);
      if (srtFile) fd.append("srtFile", srtFile);
      fd.append("recipeId", selectedRecipeId);
      fd.append("brandKitId", selectedKitId);
      fd.append(
        "curationPref",
        JSON.stringify({
          topicKeywords: clipPrompt.trim(),
          genre,
          clipDurations: [durObj?.range || [15, 180]],
          ...(startSec || endSec
            ? {
                range: {
                  startSec: parseFloat(startSec || "0"),
                  endSec: parseFloat(endSec || "0"),
                },
              }
            : {}),
        })
      );
      fd.append("renderPref", JSON.stringify(recipe?.settings || { mode: "clip", enableCaption: true }));
      fd.append("importPref", JSON.stringify({ sourceLang }));

      // Upload directly to FastAPI (127.0.0.1:8000) to bypass Next.js's 10MB proxy limit on multi-GB videos
      const backendOrigin =
        typeof window !== "undefined" ? `${window.location.protocol}//${window.location.hostname}:8000` : "http://127.0.0.1:8000";

      setSubmitError(null);
      setUploadPct(uploadFile ? 0 : null);

      const created = await new Promise<Project>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open("POST", `${backendOrigin}/api/projects`);
        xhr.upload.onprogress = (ev) => {
          if (ev.lengthComputable) {
            setUploadPct(Math.round((ev.loaded / ev.total) * 100));
          }
        };
        xhr.onload = () => {
          if (xhr.status >= 200 && xhr.status < 300) {
            try {
              resolve(JSON.parse(xhr.responseText));
            } catch {
              reject(new Error("Invalid server response"));
            }
          } else {
            reject(new Error(xhr.responseText || `Upload failed (${xhr.status})`));
          }
        };
        xhr.onerror = () => reject(new Error("Network error uploading video to local backend (port 8000)."));
        xhr.send(fd);
      });

      setVideoUrl("");
      setUploadFile(null);
      setSrtFile(null);
      setProjectTitle("");
      setActiveProject(created);
      setProjectClips([]);
      setNav("results");
      loadBootstrap();
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Failed to submit project");
    } finally {
      setSubmitting(false);
      setUploadPct(null);
    }
  };

  const handleRerunPrompt = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeProject) return;
    const durObj = clipDurations.find((d) => d.id === durationId);
    await fetch(`/api/projects/${activeProject.id}/rerun`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        topicKeywords: repromptText,
        genre,
        clipDurations: [durObj?.range || [15, 180]],
      }),
    });
    setActiveProject({ ...activeProject, stage: "curating", progress: 65, status_message: "Re-running ClipAnything prompt..." });
  };

  const handleDeleteProject = async (id: string) => {
    await fetch(`/api/projects/${id}`, { method: "DELETE" });
    if (activeProject?.id === id) {
      setActiveProject(null);
      setProjectClips([]);
      setNav("dashboard");
    }
    loadBootstrap();
  };

  const handleDuplicateClip = async (clipId: string) => {
    const res = await fetch(`/api/clips/${clipId}/duplicate`, { method: "POST" });
    if (res.ok && activeProject) {
      openProjectResults(activeProject.id);
    }
  };

  const handleBulkDownload = async () => {
    if (selectedClipIds.length === 0) return;
    const res = await fetch("/api/clips/bulk-download", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ clipIds: selectedClipIds }),
    });
    if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "oclip_bulk_clips.zip";
      a.click();
      URL.revokeObjectURL(url);
    }
  };

  // If editing a clip, render full-screen Studio Editor
  if (editingClip && activeProject) {
    return (
      <ClipEditor
        clip={editingClip}
        project={activeProject}
        captionPresets={captionPresets}
        onBack={() => {
          setEditingClip(null);
          openProjectResults(activeProject.id);
        }}
        onUpdated={(uc, tr) => {
          setEditingClip(uc);
          if (tr) setActiveProject({ ...activeProject, transcript: tr });
        }}
      />
    );
  }

  const displayedClips = [...projectClips].sort((a, b) =>
    sortBy === "score" ? b.virality_score - a.virality_score : a.start_sec - b.start_sec
  );

  return (
    <div className="flex min-h-screen bg-[#08090e] text-gray-100">
      {/* Left Sidebar */}
      <aside className="flex w-60 shrink-0 flex-col justify-between border-r border-white/10 bg-[#0b0d14] p-4">
        <div className="space-y-6">
          <div className="flex items-center gap-2.5 px-2">
            <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-gradient-to-br from-violet-500 to-fuchsia-500 font-black text-white shadow-lg shadow-violet-600/30">
              O
            </div>
            <div>
              <div className="text-sm font-bold tracking-tight text-white">OClip Studio</div>
              <div className="text-[10px] text-gray-400">Local Mac Edition</div>
            </div>
          </div>

          <nav className="space-y-1 text-xs font-medium">
            <button
              type="button"
              onClick={() => setNav("dashboard")}
              className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 transition ${
                nav === "dashboard" ? "bg-violet-600/20 text-violet-200" : "text-gray-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              <Sparkles className="h-4 w-4" /> Home & Quick Start
            </button>
            <button
              type="button"
              onClick={() => setNav("results")}
              className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 transition ${
                nav === "results" ? "bg-violet-600/20 text-violet-200" : "text-gray-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              <Film className="h-4 w-4" /> Projects & Clips
            </button>
            <button
              type="button"
              onClick={() => setNav("brand")}
              className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 transition ${
                nav === "brand" ? "bg-violet-600/20 text-violet-200" : "text-gray-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              <Palette className="h-4 w-4" /> Brand Kit & Recipes
            </button>
            <button
              type="button"
              onClick={() => setNav("calendar")}
              className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2.5 transition ${
                nav === "calendar" ? "bg-violet-600/20 text-violet-200" : "text-gray-400 hover:bg-white/5 hover:text-white"
              }`}
            >
              <CalendarDays className="h-4 w-4" /> Calendar & OpusSearch
            </button>
          </nav>

          {/* Recent Projects */}
          <div>
            <div className="mb-2 px-2 text-[10px] font-semibold uppercase tracking-wider text-gray-500">
              Recent Projects ({projects.length})
            </div>
            <div className="space-y-1">
              {projects.slice(0, 6).map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => openProjectResults(p.id)}
                  className={`flex w-full items-center justify-between rounded-lg px-2.5 py-1.5 text-left text-xs transition ${
                    activeProject?.id === p.id ? "bg-white/10 text-white" : "text-gray-400 hover:bg-white/5"
                  }`}
                >
                  <span className="truncate">{p.title}</span>
                  <span className="ml-1 shrink-0 text-[10px] text-gray-500">{p.clipCount ?? 0}</span>
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setCreditsOpen(true)}
            className="flex w-full items-center justify-between rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-2.5 text-xs hover:bg-amber-500/15"
          >
            <span className="flex items-center gap-2 font-medium text-amber-200">
              <Coins className="h-4 w-4 text-amber-400" />
              Credits
            </span>
            <span className="font-bold text-amber-300">
              {(wallet?.balance ?? 1000).toLocaleString()}
            </span>
          </button>

          <button
            type="button"
            onClick={() => setKeysOpen(true)}
            className="flex w-full items-center justify-between rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2.5 text-xs hover:bg-white/10"
          >
            <span className="flex items-center gap-2 font-medium text-gray-200">
              <KeyRound className="h-4 w-4 text-violet-400" />
              API Keys
            </span>
            <span className={`h-2 w-2 rounded-full ${health?.keys.GEMINI_API_KEY ? "bg-emerald-400" : "bg-amber-400"}`} />
          </button>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 overflow-y-auto">
        {nav === "dashboard" && (
          <div className="mx-auto max-w-5xl space-y-8 p-8">
            <div className="space-y-2">
              <div className="inline-flex items-center gap-2 rounded-full border border-violet-500/30 bg-violet-500/10 px-3 py-1 text-xs text-violet-300">
                <Wand2 className="h-3.5 w-3.5" /> Local OpusClip Studio • FFmpeg + Whisper + Gemini
              </div>
              <h1 className="text-3xl font-bold tracking-tight text-white">
                Turn 1 long video into viral shorts in one click.
              </h1>
              <p className="text-sm text-gray-400">
                Paste a YouTube/video URL or drop a local MP4/MOV file. Choose a Recipe and prompt ClipAnything.
              </p>
            </div>

            {/* Ingestion + Copilot Card */}
            <form onSubmit={handleSubmitProject} className="space-y-5 rounded-2xl border border-white/10 bg-[#10131e] p-6 shadow-xl">
              <div className="grid gap-3 md:grid-cols-2">
                <div>
                  <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-gray-300">
                    <Link2 className="h-3.5 w-3.5 text-violet-400" /> Paste Video URL (YouTube, Vimeo, MP4...)
                  </label>
                  <input
                    type="url"
                    value={videoUrl}
                    onChange={(e) => setVideoUrl(e.target.value)}
                    placeholder="https://www.youtube.com/watch?v=..."
                    className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3.5 py-2.5 text-sm text-white placeholder-gray-500 focus:border-violet-500 focus:outline-none"
                  />
                </div>
                <div>
                  <label className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-gray-300">
                    <Upload className="h-3.5 w-3.5 text-sky-400" /> Or Upload Local Video (MP4/MOV/MKV)
                  </label>
                  <label className="flex cursor-pointer items-center justify-between rounded-xl border border-dashed border-white/15 bg-[#08090e] px-3.5 py-2.5 text-sm text-gray-400 hover:border-violet-500">
                    <span className="truncate">{uploadFile ? uploadFile.name : "Choose local video file..."}</span>
                    <span className="rounded bg-white/10 px-2 py-0.5 text-xs text-gray-200">Browse</span>
                    <input
                      type="file"
                      accept="video/*"
                      className="hidden"
                      onChange={(e) => {
                        const f = e.target.files?.[0] || null;
                        setUploadFile(f);
                        if (f) {
                          const v = document.createElement("video");
                          v.preload = "metadata";
                          v.onloadedmetadata = () => {
                            if (v.duration && isFinite(v.duration)) {
                              setEstMinutes(Math.max(1, Math.round((v.duration / 60) * 10) / 10));
                            }
                            URL.revokeObjectURL(v.src);
                          };
                          v.src = URL.createObjectURL(f);
                        }
                      }}
                    />
                  </label>
                </div>
              </div>

              {/* Recipe Quick-Start Pills */}
              <div>
                <div className="mb-2 text-xs font-medium text-gray-300">Select Workflow Recipe</div>
                <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
                  {recipes.map((r) => {
                    const rate = wallet?.recipeRates?.[r.id]?.basePerMin;
                    return (
                      <button
                        key={r.id}
                        type="button"
                        onClick={() => setSelectedRecipeId(r.id)}
                        className={`rounded-xl border p-3 text-left transition ${
                          selectedRecipeId === r.id
                            ? "border-violet-500 bg-violet-600/20 text-white"
                            : "border-white/10 bg-[#08090e] text-gray-300 hover:border-white/25"
                        }`}
                      >
                        <div className="flex items-center justify-between gap-1">
                          <span className="text-xs font-semibold">{r.name}</span>
                          {rate !== undefined && (
                            <span className="shrink-0 rounded bg-amber-500/15 px-1.5 py-0.5 text-[10px] font-semibold text-amber-300">
                              {rate}/m
                            </span>
                          )}
                        </div>
                        <div className="mt-1 line-clamp-2 text-[11px] text-gray-400">{r.description}</div>
                      </button>
                    );
                  })}
                </div>
              </div>

              {/* ClipAnything & Copilot Controls */}
              <div className="grid gap-3 rounded-xl border border-white/10 bg-[#08090e] p-4 md:grid-cols-4">
                <div className="md:col-span-2">
                  <label className="mb-1 block text-xs font-medium text-gray-300">
                    ClipAnything Prompt (Optional)
                  </label>
                  <input
                    type="text"
                    value={clipPrompt}
                    onChange={(e) => setClipPrompt(e.target.value)}
                    placeholder="e.g., Find funny reactions, product demos, or AI pricing..."
                    className="w-full rounded-lg border border-white/10 bg-[#10131e] px-3 py-2 text-xs text-white"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-300">Genre</label>
                  <select
                    value={genre}
                    onChange={(e) => setGenre(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-[#10131e] px-3 py-2 text-xs"
                  >
                    {genres.map((g) => (
                      <option key={g} value={g}>{g}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs font-medium text-gray-300">Clip Length</label>
                  <select
                    value={durationId}
                    onChange={(e) => setDurationId(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-[#10131e] px-3 py-2 text-xs"
                  >
                    {clipDurations.map((d) => (
                      <option key={d.id} value={d.id}>{d.label}</option>
                    ))}
                  </select>
                </div>

                <div>
                  <label className="mb-1 block text-xs text-gray-400">Brand Kit</label>
                  <select
                    value={selectedKitId}
                    onChange={(e) => setSelectedKitId(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-[#10131e] px-3 py-1.5 text-xs"
                  >
                    {brandKits.map((k) => (
                      <option key={k.id} value={k.id}>{k.name}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-400">Source Language</label>
                  <select
                    value={sourceLang}
                    onChange={(e) => setSourceLang(e.target.value)}
                    className="w-full rounded-lg border border-white/10 bg-[#10131e] px-3 py-1.5 text-xs"
                  >
                    <option value="auto">Auto-detect</option>
                    <option value="en">English</option>
                    <option value="es">Spanish</option>
                    <option value="fr">French</option>
                    <option value="de">German</option>
                    <option value="hi">Hindi</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-400">Timeframe (sec)</label>
                  <div className="flex gap-1.5">
                    <input
                      type="number"
                      placeholder="Start"
                      value={startSec}
                      onChange={(e) => setStartSec(e.target.value)}
                      className="w-1/2 rounded-lg border border-white/10 bg-[#10131e] px-2 py-1.5 text-xs"
                    />
                    <input
                      type="number"
                      placeholder="End"
                      value={endSec}
                      onChange={(e) => setEndSec(e.target.value)}
                      className="w-1/2 rounded-lg border border-white/10 bg-[#10131e] px-2 py-1.5 text-xs"
                    />
                  </div>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-400">Optional .SRT Subtitles</label>
                  <label className="flex cursor-pointer items-center justify-between rounded-lg border border-white/10 bg-[#10131e] px-2.5 py-1.5 text-xs text-gray-400">
                    <span className="truncate">{srtFile ? srtFile.name : "Upload .srt"}</span>
                    <input type="file" accept=".srt" className="hidden" onChange={(e) => setSrtFile(e.target.files?.[0] || null)} />
                  </label>
                </div>
              </div>

              {/* Live Credit Cost Calculator */}
              <div className="rounded-xl border border-amber-500/25 bg-amber-500/5 p-3.5 text-xs">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div className="flex items-center gap-2 font-semibold text-amber-300">
                    <Coins className="h-4 w-4" />
                    Credit Cost Estimate: {creditEstimate?.estimatedCredits ?? 1} credits
                  </div>
                  <label className="flex items-center gap-2 text-[11px] text-gray-300">
                    <span>Est. Video Length (min):</span>
                    <input
                      type="number"
                      min={0.5}
                      max={600}
                      step={0.5}
                      value={estMinutes}
                      onChange={(e) => setEstMinutes(Math.max(0.5, parseFloat(e.target.value) || 1))}
                      className="w-16 rounded-lg border border-white/10 bg-[#08090e] px-2 py-1 text-center text-xs text-white"
                    />
                  </label>
                </div>
                {creditEstimate && (
                  <div className="mt-2 flex flex-wrap gap-2 text-[11px] text-gray-400">
                    {creditEstimate.breakdown.map((b, i) => (
                      <span key={i} className="rounded-md bg-black/35 px-2 py-0.5">
                        {b.item}: <strong className={b.credits < 0 ? "text-emerald-400" : "text-amber-200"}>{b.credits > 0 ? `+${b.credits}` : b.credits}</strong>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              <div className="flex items-center justify-between gap-4">
                <input
                  type="text"
                  value={projectTitle}
                  onChange={(e) => setProjectTitle(e.target.value)}
                  placeholder="Optional Project Name..."
                  className="w-64 rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-xs"
                />
                <button
                  type="submit"
                  disabled={submitting || (!videoUrl.trim() && !uploadFile)}
                  className="flex items-center gap-2 rounded-xl bg-gradient-to-r from-violet-600 to-fuchsia-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-violet-600/25 hover:opacity-95 disabled:opacity-40"
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" /> : <Scissors className="h-4 w-4" />}
                  {submitting && uploadPct !== null
                    ? `Uploading ${uploadPct}%...`
                    : `Get Clips in 1 Click (${creditEstimate?.estimatedCredits ?? 1} cr)`}
                </button>
              </div>
              {submitError && (
                <div className="rounded-xl border border-rose-500/40 bg-rose-500/10 px-3.5 py-2.5 text-xs text-rose-300">
                  {submitError}
                </div>
              )}
            </form>

            {/* Recent Projects Gallery */}
            <section>
              <h2 className="mb-3 text-sm font-semibold text-gray-300">All Projects</h2>
              {projects.length === 0 ? (
                <div className="rounded-2xl border border-dashed border-white/10 p-8 text-center text-xs text-gray-500">
                  No projects yet. Upload a video or paste a URL above to generate clips!
                </div>
              ) : (
                <div className="grid gap-4 md:grid-cols-3">
                  {projects.map((p) => (
                    <div key={p.id} className="group rounded-2xl border border-white/10 bg-[#10131e] p-3 transition hover:border-violet-500/40">
                      <div
                        onClick={() => openProjectResults(p.id)}
                        className="relative mb-3 aspect-video cursor-pointer overflow-hidden rounded-xl bg-black"
                      >
                        {p.thumbnailUrl ? (
                          <img src={p.thumbnailUrl} alt={p.title} className="h-full w-full object-cover" />
                        ) : (
                          <div className="flex h-full items-center justify-center text-gray-600">
                            <Film className="h-8 w-8" />
                          </div>
                        )}
                        <span className="absolute right-2 bottom-2 rounded bg-black/75 px-1.5 py-0.5 text-[10px] text-white">
                          {p.clipCount ?? 0} clips
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <button type="button" onClick={() => openProjectResults(p.id)} className="truncate text-left text-sm font-semibold text-white hover:text-violet-300">
                          {p.title}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteProject(p.id)}
                          aria-label={`Delete ${p.title}`}
                          className="rounded p-1 text-gray-500 hover:bg-white/10 hover:text-rose-400"
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                      <div className="mt-1 flex items-center justify-between text-[11px] text-gray-400">
                        <span>{p.stage} ({p.progress}%)</span>
                        <span>{p.duration_sec.toFixed(0)}s</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          </div>
        )}

        {nav === "results" && (
          <div className="mx-auto max-w-6xl space-y-6 p-8">
            {!activeProject ? (
              <div className="rounded-2xl border border-dashed border-white/10 p-12 text-center text-sm text-gray-400">
                Select a project from the sidebar or create a new one in Home & Quick Start.
              </div>
            ) : (
              <>
                <div className="flex flex-wrap items-center justify-between gap-4">
                  <div>
                    <div className="flex items-center gap-2 text-xs text-gray-400">
                      <FolderOpen className="h-3.5 w-3.5" /> Project Results
                      <ChevronRight className="h-3 w-3" />
                      <span>{activeProject.duration_sec.toFixed(1)}s</span>
                    </div>
                    <h1 className="text-2xl font-bold text-white">{activeProject.title}</h1>
                  </div>

                  <div className="flex flex-wrap items-center gap-2">
                    <form onSubmit={handleRerunPrompt} className="flex items-center gap-1.5">
                      <input
                        type="text"
                        value={repromptText}
                        onChange={(e) => setRepromptText(e.target.value)}
                        placeholder="Re-prompt ClipAnything..."
                        className="rounded-xl border border-white/10 bg-[#10131e] px-3 py-1.5 text-xs"
                      />
                      <button type="submit" className="flex items-center gap-1 rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs hover:bg-white/10">
                        <RefreshCw className="h-3.5 w-3.5" /> Re-Clip
                      </button>
                    </form>
                    {selectedClipIds.length > 0 && (
                      <button
                        type="button"
                        onClick={handleBulkDownload}
                        className="flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3 py-1.5 text-xs font-semibold text-white"
                      >
                        <Download className="h-3.5 w-3.5" /> Bulk Download ({selectedClipIds.length})
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setSortBy(sortBy === "score" ? "chrono" : "score")}
                      className="flex items-center gap-1 rounded-xl border border-white/10 px-3 py-1.5 text-xs text-gray-300"
                    >
                      <Clock className="h-3.5 w-3.5" /> {sortBy === "score" ? "By Virality" : "Chronological"}
                    </button>
                    <div className="flex rounded-xl border border-white/10 p-0.5">
                      <button
                        type="button"
                        onClick={() => setViewMode("grid")}
                        className={`rounded-lg p-1.5 ${viewMode === "grid" ? "bg-violet-600 text-white" : "text-gray-400"}`}
                      >
                        <Grid className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        onClick={() => setViewMode("list")}
                        className={`rounded-lg p-1.5 ${viewMode === "list" ? "bg-violet-600 text-white" : "text-gray-400"}`}
                      >
                        <List className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </div>
                </div>

                {/* Progress Bar if still processing */}
                {activeProject.stage !== "completed" && (
                  <div className="rounded-2xl border border-violet-500/30 bg-violet-500/10 p-4">
                    <div className="mb-2 flex items-center justify-between text-xs font-medium">
                      <span className="flex items-center gap-2 text-violet-200">
                        {activeProject.stage === "failed" ? null : <Loader2 className="h-4 w-4 animate-spin" />}
                        {activeProject.status_message}
                      </span>
                      <span>{activeProject.progress}%</span>
                    </div>
                    <progress max={100} value={activeProject.progress} className="h-2 w-full overflow-hidden rounded-full" />
                    {activeProject.error && (
                      <p className="mt-2 text-xs text-rose-400">{activeProject.error}</p>
                    )}
                  </div>
                )}

                {/* Clips Grid / List */}
                <div className={viewMode === "grid" ? "grid gap-5 md:grid-cols-2 lg:grid-cols-3" : "space-y-4"}>
                  {displayedClips.map((c, idx) => {
                    const isSel = selectedClipIds.includes(c.id);
                    return (
                      <div
                        key={c.id}
                        className={`rounded-2xl border bg-[#10131e] p-4 transition ${
                          isSel ? "border-violet-500" : "border-white/10"
                        } ${viewMode === "list" ? "flex gap-5" : "space-y-3"}`}
                      >
                        <div className={viewMode === "list" ? "w-56 shrink-0" : ""}>
                          <div className="relative aspect-[9/16] max-h-80 w-full overflow-hidden rounded-xl bg-black">
                            {c.previewUrl ? (
                              <video src={c.previewUrl} controls playsInline className="h-full w-full object-contain" />
                            ) : c.thumbnailUrl ? (
                              <img src={c.thumbnailUrl} alt={c.title} className="h-full w-full object-cover" />
                            ) : (
                              <div className="flex h-full items-center justify-center">
                                <PlayCircle className="h-10 w-10 text-gray-600" />
                              </div>
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                setSelectedClipIds((prev) =>
                                  isSel ? prev.filter((id) => id !== c.id) : [...prev, c.id]
                                )
                              }
                              className={`absolute top-2 left-2 rounded-lg p-1 ${
                                isSel ? "bg-violet-600 text-white" : "bg-black/60 text-gray-300"
                              }`}
                              title="Select for bulk download"
                            >
                              <CheckSquare className="h-4 w-4" />
                            </button>
                            <div className="absolute top-2 right-2 rounded-lg bg-black/80 px-2.5 py-1 text-xs font-bold text-emerald-400">
                              #{idx + 1} • {c.virality_score}/99
                            </div>
                          </div>
                        </div>

                        <div className="flex flex-1 flex-col justify-between space-y-3">
                          <div>
                            <h3 className="text-sm font-semibold text-white">{c.title}</h3>
                            <p className="mt-1 text-[11px] text-gray-400">
                              {c.start_sec.toFixed(1)}s – {c.end_sec.toFixed(1)}s ({c.duration_sec.toFixed(1)}s)
                            </p>

                            {/* 4-Pillar Virality Breakdown */}
                            <div className="mt-3 grid grid-cols-4 gap-1.5 rounded-xl bg-[#08090e] p-2 text-center text-[10px]">
                              <div>
                                <div className="text-gray-500">Hook</div>
                                <div className="font-bold text-violet-300">{c.viralityBreakdown?.hook ?? "-"}</div>
                              </div>
                              <div>
                                <div className="text-gray-500">Flow</div>
                                <div className="font-bold text-sky-300">{c.viralityBreakdown?.flow ?? "-"}</div>
                              </div>
                              <div>
                                <div className="text-gray-500">Value</div>
                                <div className="font-bold text-emerald-300">{c.viralityBreakdown?.value ?? "-"}</div>
                              </div>
                              <div>
                                <div className="text-gray-500">Trend</div>
                                <div className="font-bold text-amber-300">{c.viralityBreakdown?.trend ?? "-"}</div>
                              </div>
                            </div>
                            {c.viralityBreakdown?.rationale && (
                              <p className="mt-2 line-clamp-2 text-[11px] text-gray-400">
                                {c.viralityBreakdown.rationale}
                              </p>
                            )}
                          </div>

                          <div className="flex flex-wrap gap-1.5 pt-2">
                            <button
                              type="button"
                              onClick={() => setEditingClip(c)}
                              className="flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-violet-600 px-3 py-2 text-xs font-semibold text-white hover:bg-violet-500"
                            >
                              <Scissors className="h-3.5 w-3.5" /> Edit Clip
                            </button>
                            <a
                              href={`/api/clips/${c.id}/download?resolution=1080p`}
                              className="flex items-center gap-1 rounded-xl border border-white/10 px-2.5 py-2 text-xs text-gray-200 hover:bg-white/10"
                              title="Download 1080p MP4"
                            >
                              <Download className="h-3.5 w-3.5" />
                            </a>
                            <a
                              href={`/api/clips/${c.id}/xml`}
                              className="flex items-center gap-1 rounded-xl border border-white/10 px-2.5 py-2 text-xs text-sky-300 hover:bg-white/10"
                              title="Export Premiere / DaVinci XML"
                            >
                              <FileCode2 className="h-3.5 w-3.5" />
                            </a>
                            <button
                              type="button"
                              onClick={() => handleDuplicateClip(c.id)}
                              className="flex items-center gap-1 rounded-xl border border-white/10 px-2.5 py-2 text-xs text-gray-300 hover:bg-white/10"
                              title="Duplicate clip"
                            >
                              <Copy className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </>
            )}
          </div>
        )}

        {nav === "brand" && (
          <BrandKitView
            brandKits={brandKits}
            recipes={recipes}
            captionPresets={captionPresets}
            onRefresh={loadBootstrap}
          />
        )}

        {nav === "calendar" && (
          <CalendarView
            clips={allClips}
            posts={posts}
            collections={collections}
            onRefresh={loadBootstrap}
            onOpenClip={async (c) => {
              const res = await fetch(`/api/projects/${c.project_id}`);
              if (res.ok) {
                const d = await res.json();
                setActiveProject(d.project);
                setProjectClips(d.clips || []);
                setEditingClip(c);
              }
            }}
          />
        )}
      </main>

      <ApiKeysDialog
        open={keysOpen}
        health={health}
        onClose={() => setKeysOpen(false)}
        onSaved={(h) => setHealth(h)}
      />
      <CreditsDialog
        open={creditsOpen}
        wallet={wallet}
        onClose={() => setCreditsOpen(false)}
        onUpdated={(w) => setWallet(w)}
      />
    </div>
  );
}
