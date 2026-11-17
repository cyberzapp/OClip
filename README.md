# OClip Studio — Local Mac OpusClip Alternative

Local AI video clipping & short-form editing studio for macOS, built from reverse-engineering `opus.pro`.

## Run Locally on Mac

```bash
chmod +x start.sh
./start.sh
```

Then open **http://localhost:3000**.

## Optional API Keys (Click "API Keys" in bottom-left sidebar)

* **`GEMINI_API_KEY`** — Enables multimodal **ClipAnything™** curation, 4-pillar **Virality Scoring**, **Bad-Take** detection, **AI B-Roll** planning & image generation, **Subtitle Translation**, and **AI Social Copy**. *(Without it, OClip falls back to local Whisper + transcript/hook heuristic curation so everything still runs 100% offline.)*
* **`PEXELS_API_KEY`** — Enables Stock Video B-Roll search & download.
* **`ELEVENLABS_API_KEY`** — Enables ElevenLabs studio voiceovers/dubbing. *(Without it, OClip uses macOS built-in `say` TTS offline.)*
