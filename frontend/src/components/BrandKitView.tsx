"use client";

import { useState } from "react";
import { Palette, Plus, Sparkles, Trash2, Upload } from "lucide-react";
import { BrandKit, CaptionPreset, Recipe } from "@/lib/types";

interface Props {
  brandKits: BrandKit[];
  recipes: Recipe[];
  captionPresets: CaptionPreset[];
  onRefresh: () => void;
}

export default function BrandKitView({ brandKits, recipes, captionPresets, onRefresh }: Props) {
  const activeKit = brandKits[0];
  const [kitName, setKitName] = useState(activeKit?.name || "My Brand Kit");
  const [captionId, setCaptionId] = useState(activeKit?.config.captionTemplateId || "preset-fancy-Karaoke");
  const [highlightColor, setHighlightColor] = useState(activeKit?.config.highlightColor || "#04F827");
  const [layoutMode, setLayoutMode] = useState(activeKit?.config.layoutMode || "fill");
  const [aspectRatio, setAspectRatio] = useState(activeKit?.config.aspectRatio || "portrait");
  const [vocabText, setVocabText] = useState((activeKit?.config.vocabulary || []).join(", "));
  const [logoPath, setLogoPath] = useState<string | null | undefined>(activeKit?.config.logoPath);
  const [musicPath, setMusicPath] = useState<string | null | undefined>(activeKit?.config.musicPath);
  const [saving, setSaving] = useState(false);

  const [newRecipeName, setNewRecipeName] = useState("");
  const [newRecipeDesc, setNewRecipeDesc] = useState("");

  const uploadAsset = async (file: File, kind: "logo" | "music") => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("kind", kind);
    const res = await fetch("/api/assets/upload", { method: "POST", body: fd });
    if (res.ok) {
      const data = await res.json();
      if (kind === "logo") setLogoPath(data.path);
      else setMusicPath(data.path);
    }
  };

  const saveKit = async () => {
    setSaving(true);
    try {
      await fetch("/api/brand-kits", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: activeKit?.id || "kit-default",
          name: kitName,
          is_default: true,
          config: {
            ...(activeKit?.config || {}),
            captionTemplateId: captionId,
            highlightColor,
            layoutMode,
            aspectRatio,
            vocabulary: vocabText.split(",").map((s) => s.trim()).filter(Boolean),
            logoPath,
            musicPath,
          },
        }),
      });
      onRefresh();
    } finally {
      setSaving(false);
    }
  };

  const createRecipe = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newRecipeName.trim()) return;
    await fetch("/api/recipes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        name: newRecipeName.trim(),
        description: newRecipeDesc.trim() || "Custom creator workflow recipe",
        settings: {
          mode: "clip",
          enableCaption: true,
          captionTemplateId: captionId,
          enableAutoHeadline: true,
          enableAutoLayout: true,
          layoutMode,
          aspectRatio,
          enableSpeechCleanup: true,
        },
      }),
    });
    setNewRecipeName("");
    setNewRecipeDesc("");
    onRefresh();
  };

  const deleteRecipe = async (id: string) => {
    await fetch(`/api/recipes/${id}`, { method: "DELETE" });
    onRefresh();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6">
      {/* Brand Kit */}
      <section className="rounded-2xl border border-white/10 bg-[#10131e] p-6">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <Palette className="h-5 w-5 text-violet-400" />
            <div>
              <h2 className="text-lg font-semibold">Brand Kit & Vocabulary</h2>
              <p className="text-xs text-gray-400">
                Save default caption style, layout, logo watermark, music, and custom ASR Brand Vocabulary.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={saveKit}
            disabled={saving}
            className="rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-500"
          >
            {saving ? "Saving..." : "Save Brand Kit"}
          </button>
        </div>

        <div className="grid gap-4 md:grid-cols-2">
          <div>
            <label className="mb-1 block text-xs text-gray-400">Brand Kit Name</label>
            <input
              type="text"
              value={kitName}
              onChange={(e) => setKitName(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Default Caption Preset</label>
            <select
              value={captionId}
              onChange={(e) => setCaptionId(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
            >
              {captionPresets.map((p) => (
                <option key={p.templateId} value={p.templateId}>
                  {p.name} ({p.fontFamily})
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Default Layout & Aspect Ratio</label>
            <div className="grid grid-cols-2 gap-2">
              <select
                value={layoutMode}
                onChange={(e) => setLayoutMode(e.target.value)}
                className="rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
              >
                <option value="fill">Fill</option>
                <option value="fit">Fit</option>
                <option value="split">Split</option>
                <option value="screenshare">Screenshare</option>
                <option value="gameplay">Gameplay</option>
              </select>
              <select
                value={aspectRatio}
                onChange={(e) => setAspectRatio(e.target.value)}
                className="rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
              >
                <option value="portrait">9:16 Portrait</option>
                <option value="square">1:1 Square</option>
                <option value="four-five">4:5 Social</option>
                <option value="landscape">16:9 Landscape</option>
              </select>
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Highlight Color</label>
            <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-[#08090e] px-3 py-1.5">
              <input type="color" value={highlightColor} onChange={(e) => setHighlightColor(e.target.value)} />
              <span className="font-mono text-xs text-gray-300">{highlightColor}</span>
            </div>
          </div>
          <div className="md:col-span-2">
            <label className="mb-1 block text-xs text-gray-400">
              Brand Vocabulary (comma-separated names/acronyms for Whisper ASR accuracy)
            </label>
            <input
              type="text"
              value={vocabText}
              onChange={(e) => setVocabText(e.target.value)}
              placeholder="OpusClip, FastAPI, ClipAnything, Kubernetes..."
              className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Brand Logo Watermark (PNG)</label>
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-white/15 bg-[#08090e] px-3 py-2 text-xs text-gray-300 hover:border-violet-500">
              <Upload className="h-4 w-4 text-violet-400" />
              <span>{logoPath ? "Logo uploaded (click to replace)" : "Upload PNG logo"}</span>
              <input type="file" accept="image/*" className="hidden" onChange={(e) => e.target.files?.[0] && uploadAsset(e.target.files[0], "logo")} />
            </label>
          </div>
          <div>
            <label className="mb-1 block text-xs text-gray-400">Background Music (MP3/WAV)</label>
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-dashed border-white/15 bg-[#08090e] px-3 py-2 text-xs text-gray-300 hover:border-violet-500">
              <Upload className="h-4 w-4 text-sky-400" />
              <span>{musicPath ? "Music uploaded (click to replace)" : "Upload background track"}</span>
              <input type="file" accept="audio/*" className="hidden" onChange={(e) => e.target.files?.[0] && uploadAsset(e.target.files[0], "music")} />
            </label>
          </div>
        </div>
      </section>

      {/* Recipes Manager */}
      <section className="rounded-2xl border border-white/10 bg-[#10131e] p-6">
        <div className="mb-4 flex items-center gap-2.5">
          <Sparkles className="h-5 w-5 text-amber-400" />
          <div>
            <h2 className="text-lg font-semibold">Automation Recipes</h2>
            <p className="text-xs text-gray-400">8 OpusClip-style built-in Recipes + your custom saved workflows.</p>
          </div>
        </div>

        <form onSubmit={createRecipe} className="mb-5 flex flex-wrap gap-2">
          <input
            type="text"
            value={newRecipeName}
            onChange={(e) => setNewRecipeName(e.target.value)}
            placeholder="New custom recipe name..."
            className="flex-1 rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
          />
          <input
            type="text"
            value={newRecipeDesc}
            onChange={(e) => setNewRecipeDesc(e.target.value)}
            placeholder="Description..."
            className="flex-1 rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-sm"
          />
          <button type="submit" className="flex items-center gap-1.5 rounded-xl bg-violet-600 px-4 py-2 text-xs font-semibold text-white hover:bg-violet-500">
            <Plus className="h-4 w-4" /> Save Current Kit as Recipe
          </button>
        </form>

        <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
          {recipes.map((r) => (
            <div key={r.id} className="flex flex-col justify-between rounded-xl border border-white/10 bg-[#08090e] p-3.5">
              <div>
                <div className="mb-1 flex items-center justify-between">
                  <span className="text-sm font-semibold text-white">{r.name}</span>
                  <span className={`rounded px-1.5 py-0.5 text-[10px] ${r.is_builtin ? "bg-white/10 text-gray-400" : "bg-violet-600/20 text-violet-300"}`}>
                    {r.is_builtin ? "Built-in" : "Custom"}
                  </span>
                </div>
                <p className="text-xs text-gray-400">{r.description}</p>
              </div>
              {!r.is_builtin && (
                <button
                  type="button"
                  onClick={() => deleteRecipe(r.id)}
                  className="mt-3 flex items-center gap-1 self-end text-[11px] text-rose-400 hover:text-rose-300"
                >
                  <Trash2 className="h-3 w-3" /> Delete
                </button>
              )}
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
