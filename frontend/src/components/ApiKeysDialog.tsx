"use client";

import { useEffect, useRef, useState } from "react";
import { KeyRound, CheckCircle2, X } from "lucide-react";
import { HealthStatus } from "@/lib/types";

interface Props {
  open: boolean;
  health: HealthStatus | null;
  onClose: () => void;
  onSaved: (h: HealthStatus) => void;
}

export default function ApiKeysDialog({ open, health, onClose, onSaved }: Props) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [gemini, setGemini] = useState("");
  const [pexels, setPexels] = useState("");
  const [eleven, setEleven] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const el = dialogRef.current;
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
    } else if (!open && el.open) {
      el.close();
    }
  }, [open]);

  const handleClose = () => {
    const el = dialogRef.current;
    if (el) el.returnValue = "";
    onClose();
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaving(true);
    try {
      const body: Record<string, string> = {};
      if (gemini.trim()) body.GEMINI_API_KEY = gemini.trim();
      if (pexels.trim()) body.PEXELS_API_KEY = pexels.trim();
      if (eleven.trim()) body.ELEVENLABS_API_KEY = eleven.trim();

      const res = await fetch("/api/settings/keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (res.ok) {
        const updated = (await res.json()) as HealthStatus;
        onSaved(updated);
        setGemini("");
        setPexels("");
        setEleven("");
        handleClose();
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby="api-keys-title"
      onClose={handleClose}
      className="w-full max-w-lg rounded-2xl border border-white/10 bg-[#121521] p-6 text-gray-100 shadow-2xl"
    >
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-violet-600/20 text-violet-400">
            <KeyRound className="h-5 w-5" />
          </div>
          <div>
            <h2 id="api-keys-title" className="text-base font-semibold">
              Local API Keys & Engine Status
            </h2>
            <p className="text-xs text-gray-400">
              Saved locally to <code className="text-violet-300">.env.local</code> — never leaves your Mac except API calls.
            </p>
          </div>
        </div>
        <button
          type="button"
          onClick={handleClose}
          aria-label="Close settings"
          className="rounded-lg p-1.5 text-gray-400 hover:bg-white/10 hover:text-white"
        >
          <X className="h-4 w-4" />
        </button>
      </div>

      <div className="mb-4 grid grid-cols-2 gap-2 rounded-xl border border-white/10 bg-black/25 p-3 text-xs">
        <div className="flex items-center gap-2">
          <CheckCircle2 className={`h-4 w-4 ${health?.ffmpeg ? "text-emerald-400" : "text-rose-400"}`} />
          <span>FFmpeg: {health?.ffmpeg ? "Ready" : "Missing"}</span>
        </div>
        <div className="flex items-center gap-2">
          <CheckCircle2 className={`h-4 w-4 ${health?.ytdlp ? "text-emerald-400" : "text-rose-400"}`} />
          <span>yt-dlp: {health?.ytdlp ? "Ready" : "Missing"}</span>
        </div>
      </div>

      <form onSubmit={handleSave} className="space-y-4">
        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <label htmlFor="gemini-key" className="font-medium text-gray-200">
              GEMINI_API_KEY (ClipAnything, Virality Score, AI B-Roll, Translate)
            </label>
            <span className={health?.keys.GEMINI_API_KEY ? "text-emerald-400" : "text-amber-400"}>
              {health?.keys.GEMINI_API_KEY ? "Configured" : "Optional (heuristic fallback active)"}
            </span>
          </div>
          <input
            id="gemini-key"
            type="password"
            autoFocus
            value={gemini}
            onChange={(e) => setGemini(e.target.value)}
            placeholder={health?.keys.GEMINI_API_KEY ? "•••••••••••••••• (enter to replace)" : "AIza..."}
            className="w-full rounded-xl border border-white/10 bg-[#0b0d14] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-violet-500 focus:outline-none"
          />
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <label htmlFor="pexels-key" className="font-medium text-gray-200">
              PEXELS_API_KEY (Stock Video B-Roll)
            </label>
            <span className={health?.keys.PEXELS_API_KEY ? "text-emerald-400" : "text-gray-400"}>
              {health?.keys.PEXELS_API_KEY ? "Configured" : "Optional"}
            </span>
          </div>
          <input
            id="pexels-key"
            type="password"
            value={pexels}
            onChange={(e) => setPexels(e.target.value)}
            placeholder={health?.keys.PEXELS_API_KEY ? "••••••••••••••••" : "Pexels API Key"}
            className="w-full rounded-xl border border-white/10 bg-[#0b0d14] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-violet-500 focus:outline-none"
          />
        </div>

        <div>
          <div className="mb-1 flex items-center justify-between text-xs">
            <label htmlFor="eleven-key" className="font-medium text-gray-200">
              ELEVENLABS_API_KEY (Studio AI Voiceover & Dubbing)
            </label>
            <span className={health?.keys.ELEVENLABS_API_KEY ? "text-emerald-400" : "text-gray-400"}>
              {health?.keys.ELEVENLABS_API_KEY ? "Configured" : "Optional (uses macOS `say` offline)"}
            </span>
          </div>
          <input
            id="eleven-key"
            type="password"
            value={eleven}
            onChange={(e) => setEleven(e.target.value)}
            placeholder={health?.keys.ELEVENLABS_API_KEY ? "••••••••••••••••" : "sk_..."}
            className="w-full rounded-xl border border-white/10 bg-[#0b0d14] px-3 py-2 text-sm text-white placeholder-gray-500 focus:border-violet-500 focus:outline-none"
          />
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={handleClose}
            className="rounded-xl border border-white/10 px-4 py-2 text-sm text-gray-300 hover:bg-white/5"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={saving}
            className="rounded-xl bg-violet-600 px-4 py-2 text-sm font-medium text-white hover:bg-violet-500 disabled:opacity-50"
          >
            {saving ? "Saving..." : "Save API Keys"}
          </button>
        </div>
      </form>
    </dialog>
  );
}
