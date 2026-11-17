"use client";

import { useState } from "react";
import { Calendar, FolderPlus, Search, Send, Sparkles, Trash2 } from "lucide-react";
import { Clip, ScheduledPost } from "@/lib/types";

interface Props {
  clips: Clip[];
  posts: ScheduledPost[];
  collections: { id: string; name: string; clipIds: string[] }[];
  onRefresh: () => void;
  onOpenClip: (clip: Clip) => void;
}

export default function CalendarView({ clips, posts, collections, onRefresh, onOpenClip }: Props) {
  const [searchQ, setSearchQ] = useState("");
  const [selectedClipId, setSelectedClipId] = useState(clips[0]?.id || "");
  const [platform, setPlatform] = useState("YouTube Shorts");
  const [postTitle, setPostTitle] = useState("");
  const [postCopy, setPostCopy] = useState("");
  const [scheduledAt, setScheduledAt] = useState("2026-11-20T15:00");
  const [newColName, setNewColName] = useState("");
  const [generatingCopy, setGeneratingCopy] = useState(false);

  const filteredClips = clips.filter(
    (c) =>
      !searchQ.trim() ||
      c.title.toLowerCase().includes(searchQ.toLowerCase()) ||
      c.keywords.some((k) => k.toLowerCase().includes(searchQ.toLowerCase()))
  );

  const generateCopy = async () => {
    if (!selectedClipId) return;
    setGeneratingCopy(true);
    try {
      const res = await fetch(`/api/clips/${selectedClipId}/social-copy`, { method: "POST" });
      if (res.ok) {
        const updated = (await res.json()) as Clip;
        const pKey = platform.toLowerCase().includes("youtube")
          ? "youtube"
          : platform.toLowerCase().includes("tiktok")
          ? "tiktok"
          : platform.toLowerCase().includes("instagram")
          ? "instagram"
          : platform.toLowerCase().includes("linkedin")
          ? "linkedin"
          : "x";
        setPostTitle(updated.title);
        setPostCopy(updated.socialCopy?.[pKey] || updated.title);
        onRefresh();
      }
    } finally {
      setGeneratingCopy(false);
    }
  };

  const schedulePost = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedClipId) return;
    await fetch("/api/schedule", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        clipId: selectedClipId,
        platform,
        title: postTitle || "Scheduled Clip",
        copy: postCopy,
        hashtags: ["#shorts", "#reels"],
        scheduledAt,
      }),
    });
    setPostCopy("");
    onRefresh();
  };

  const deletePost = async (id: string) => {
    await fetch(`/api/schedule/${id}`, { method: "DELETE" });
    onRefresh();
  };

  const createCollection = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newColName.trim()) return;
    await fetch("/api/collections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: newColName.trim() }),
    });
    setNewColName("");
    onRefresh();
  };

  return (
    <div className="mx-auto max-w-6xl space-y-8 p-6">
      {/* OpusSearch Clip Library */}
      <section className="rounded-2xl border border-white/10 bg-[#10131e] p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold">OpusSearch — Clip Library & Collections</h2>
            <p className="text-xs text-gray-400">Search across all generated clips, keywords, and organize into collections.</p>
          </div>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="absolute top-2.5 left-3 h-4 w-4 text-gray-500" />
              <input
                type="search"
                value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)}
                placeholder="Search clips or keywords..."
                className="rounded-xl border border-white/10 bg-[#08090e] py-2 pr-3 pl-9 text-xs text-white"
              />
            </div>
            <form onSubmit={createCollection} className="flex gap-1.5">
              <input
                type="text"
                value={newColName}
                onChange={(e) => setNewColName(e.target.value)}
                placeholder="New collection..."
                className="rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-xs"
              />
              <button type="submit" className="flex items-center gap-1 rounded-xl bg-white/10 px-3 py-2 text-xs hover:bg-white/15">
                <FolderPlus className="h-3.5 w-3.5" /> Add
              </button>
            </form>
          </div>
        </div>

        {collections.length > 0 && (
          <div className="mb-4 flex flex-wrap gap-2">
            {collections.map((col) => (
              <span key={col.id} className="rounded-lg border border-violet-500/30 bg-violet-600/15 px-3 py-1 text-xs text-violet-200">
                {col.name} ({col.clipIds.length})
              </span>
            ))}
          </div>
        )}

        <div className="grid gap-3 md:grid-cols-3">
          {filteredClips.slice(0, 9).map((c) => (
            <div key={c.id} className="flex items-center justify-between rounded-xl border border-white/10 bg-[#08090e] p-3">
              <div className="min-w-0 pr-2">
                <div className="truncate text-sm font-medium text-white">{c.title}</div>
                <div className="text-[11px] text-gray-400">
                  Score {c.virality_score}/99 • {c.duration_sec.toFixed(0)}s
                </div>
              </div>
              <button
                type="button"
                onClick={() => onOpenClip(c)}
                className="shrink-0 rounded-lg bg-violet-600/25 px-2.5 py-1 text-xs font-medium text-violet-200 hover:bg-violet-600/40"
              >
                Edit
              </button>
            </div>
          ))}
        </div>
      </section>

      {/* Social Copy & Scheduler */}
      <section className="grid gap-6 md:grid-cols-2">
        <form onSubmit={schedulePost} className="space-y-3 rounded-2xl border border-white/10 bg-[#10131e] p-6">
          <div className="flex items-center gap-2">
            <Send className="h-5 w-5 text-sky-400" />
            <h2 className="text-lg font-semibold">Social Copy & Post Scheduler</h2>
          </div>

          <div>
            <label className="mb-1 block text-xs text-gray-400">Select Clip</label>
            <select
              value={selectedClipId}
              onChange={(e) => setSelectedClipId(e.target.value)}
              className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-xs"
            >
              {clips.map((c) => (
                <option key={c.id} value={c.id}>
                  [{c.virality_score}] {c.title}
                </option>
              ))}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="mb-1 block text-xs text-gray-400">Platform</label>
              <select
                value={platform}
                onChange={(e) => setPlatform(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-xs"
              >
                <option>YouTube Shorts</option>
                <option>TikTok</option>
                <option>Instagram Reels</option>
                <option>LinkedIn</option>
                <option>X</option>
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-gray-400">Schedule Date & Time</label>
              <input
                type="datetime-local"
                value={scheduledAt}
                onChange={(e) => setScheduledAt(e.target.value)}
                className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-xs"
              />
            </div>
          </div>

          <div className="flex items-center justify-between">
            <label className="text-xs text-gray-400">AI Caption & Hashtags</label>
            <button
              type="button"
              onClick={generateCopy}
              disabled={generatingCopy || !selectedClipId}
              className="flex items-center gap-1 rounded-lg bg-violet-600/25 px-2.5 py-1 text-[11px] font-medium text-violet-200 hover:bg-violet-600/40"
            >
              <Sparkles className="h-3 w-3" /> {generatingCopy ? "Generating..." : "Generate AI Social Copy"}
            </button>
          </div>

          <input
            type="text"
            value={postTitle}
            onChange={(e) => setPostTitle(e.target.value)}
            placeholder="Post title..."
            className="w-full rounded-xl border border-white/10 bg-[#08090e] px-3 py-2 text-xs"
          />
          <textarea
            rows={3}
            value={postCopy}
            onChange={(e) => setPostCopy(e.target.value)}
            placeholder="Post description & hashtags..."
            className="w-full rounded-xl border border-white/10 bg-[#08090e] p-3 text-xs"
          />
          <button type="submit" disabled={!selectedClipId} className="w-full rounded-xl bg-violet-600 py-2.5 text-xs font-semibold text-white hover:bg-violet-500 disabled:opacity-50">
            Schedule to Content Calendar
          </button>
        </form>

        <div className="rounded-2xl border border-white/10 bg-[#10131e] p-6">
          <div className="mb-4 flex items-center gap-2">
            <Calendar className="h-5 w-5 text-emerald-400" />
            <h2 className="text-lg font-semibold">Content Calendar ({posts.length})</h2>
          </div>
          {posts.length === 0 ? (
            <p className="text-xs text-gray-500">No scheduled posts yet. Queue a clip on the left.</p>
          ) : (
            <div className="space-y-3">
              {posts.map((p) => (
                <div key={p.id} className="flex items-start justify-between rounded-xl border border-white/10 bg-[#08090e] p-3">
                  <div>
                    <div className="flex items-center gap-2">
                      <span className="rounded bg-sky-500/20 px-2 py-0.5 text-[10px] font-medium text-sky-300">
                        {p.platform}
                      </span>
                      <span className="text-xs font-semibold text-white">{p.title}</span>
                    </div>
                    <p className="mt-1 line-clamp-2 text-xs text-gray-400">{p.copy}</p>
                    <div className="mt-1 text-[10px] text-gray-500">{p.scheduled_at}</div>
                  </div>
                  <button
                    type="button"
                    onClick={() => deletePost(p.id)}
                    className="rounded p-1 text-gray-500 hover:bg-white/10 hover:text-rose-400"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </section>
    </div>
  );
}
