export interface TranscriptWord {
  id: string;
  word: string;
  start: number;
  end: number;
  isFillerWord?: boolean;
  isProfanity?: boolean;
  deleted?: boolean;
  censored?: boolean;
}

export interface TranscriptParagraph {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker?: string;
  words: TranscriptWord[];
}

export interface ViralityBreakdown {
  hook: number;
  flow: number;
  value: number;
  trend: number;
  rationale?: string;
}

export interface BRollItem {
  id: string;
  start_sec: number;
  end_sec: number;
  query: string;
  assetPath: string;
  assetUrl?: string | null;
  layout: "fill" | "pip" | "split";
  source?: string;
}

export interface EditingScript {
  aspectRatio: "portrait" | "square" | "landscape" | "four-five";
  layoutMode: string;
  cardFrameRatio?: "3:4" | "1:1" | "4:3";
  framing?: {
    width?: number;
    height?: number;
    speakerCount?: number;
    keyframes?: { t: number; cx: number; cy: number }[];
    clusters?: { cx: number; cy: number }[];
    manualTracked?: boolean;
  };
  captions: {
    enabled: boolean;
    templateId: string;
    fontFamily: string;
    fontSize: number;
    uppercase: boolean;
    primaryColor: string;
    highlightColor: string;
    secondaryColor: string;
    enableEmoji?: boolean;
    positionY?: number;
    wordsPerLine?: number;
  };
  headline?: {
    enabled: boolean;
    text: string;
    colorStyle?: "yellow" | "red" | "red-banner" | "yellow-banner";
    persistent?: boolean;
    durationSec?: number;
  };
  viralHook?: {
    enabled: boolean;
    text: string;
  };
  textOverlays?: { id: string; text: string; start: number; end: number }[];
  brolls?: BRollItem[];
  speechCleanup?: {
    pauseThresholdSec: number;
    removedPauses: { id: string; start: number; end: number; duration: number }[];
    badTakes?: { paragraph_id: string; reason: string; word_ids: string[] }[];
  };
  enhance?: {
    speechEnhance?: boolean;
    noiseReduction?: number;
    voiceBoost?: number;
    autoColor?: boolean;
    colorIntensity?: number;
    censorStyle?: "**" | "--";
    censorAudioMode?: "beep" | "mute" | "none";
    upscale?: boolean;
  };
  voiceover?: {
    audioPath?: string;
    audioUrl?: string | null;
    start_sec?: number;
    originalVolume?: number;
    text?: string;
    voice?: string;
  };
  sfx?: { id: string; name: string; t: number; volume: number }[];
  music?: { path?: string | null; volume?: number };
}

export interface Clip {
  id: string;
  project_id: string;
  title: string;
  start_sec: number;
  end_sec: number;
  duration_sec: number;
  virality_score: number;
  viralityBreakdown: ViralityBreakdown;
  keywords: string[];
  hashtags: string[];
  socialCopy: Record<string, string>;
  genre: string;
  headline: string;
  editingScript: EditingScript;
  previewUrl?: string | null;
  exportUrl?: string | null;
  thumbnailUrl?: string | null;
  created_at: string;
}

export interface Project {
  id: string;
  title: string;
  source_type: string;
  source_url?: string | null;
  sourceMediaUrl?: string | null;
  thumbnailUrl?: string | null;
  duration_sec: number;
  width: number;
  height: number;
  fps: number;
  stage: "queued" | "downloading" | "probing" | "transcribing" | "curating" | "rendering" | "completed" | "failed";
  progress: number;
  status_message: string;
  error?: string | null;
  clipCount?: number;
  transcript?: TranscriptParagraph[];
  curationPref?: Record<string, unknown>;
  renderPref?: Record<string, unknown>;
  created_at: string;
}

export interface CaptionPreset {
  templateId: string;
  name: string;
  fontFamily: string;
  fontSize: number;
  uppercase: boolean;
  primaryColor: string;
  highlightColor: string;
  secondaryColor: string;
  boxColor?: string;
  strokeColor: string;
  strokeWidth: number;
  shadowEnabled: boolean;
  animation: string;
  wordsPerLine: number;
  positionY: number;
}

export interface Recipe {
  id: string;
  name: string;
  description: string;
  is_builtin: boolean;
  settings: Record<string, unknown>;
}

export interface BrandKit {
  id: string;
  name: string;
  is_default: boolean;
  config: {
    captionTemplateId: string;
    fontFamily: string;
    fontSize: number;
    uppercase: boolean;
    primaryColor: string;
    highlightColor: string;
    secondaryColor: string;
    aspectRatio: string;
    layoutMode: string;
    vocabulary: string[];
    logoPath?: string | null;
    musicPath?: string | null;
    musicVolume?: number;
  };
}

export interface HealthStatus {
  ok: boolean;
  ffmpeg: boolean;
  ytdlp: boolean;
  keys: {
    GEMINI_API_KEY: boolean;
    PEXELS_API_KEY: boolean;
    ELEVENLABS_API_KEY: boolean;
  };
}

export interface ScheduledPost {
  id: string;
  clip_id: string;
  clip_title?: string;
  clip_thumbnail?: string | null;
  platform: string;
  title: string;
  copy: string;
  hashtags: string[];
  scheduled_at: string;
  status: string;
}

export interface CreditTransaction {
  id: string;
  action: string;
  description: string;
  amount: number;
  balance_after: number;
  project_id?: string | null;
  clip_id?: string | null;
  created_at: string;
}

export interface CreditWallet {
  balance: number;
  updatedAt: string;
  transactions: CreditTransaction[];
  recipeRates?: Record<string, { label: string; basePerMin: number; features: string[] }>;
}

export interface CreditEstimate {
  estimatedCredits: number;
  effectiveMinutes: number;
  breakdown: { item: string; credits: number }[];
}
