# 🎙️ Empathy Engine

> *Dynamically modulates synthesized speech based on the detected emotion of the source text.*

---

## Overview

The **Empathy Engine** is a Flask web service that closes the gap between flat, robotic TTS and genuinely expressive voice output. It:

1. **Detects emotion** in your text using rule-based keyword matching + VADER sentiment analysis
2. **Injects bracket tags** (`[angry]`, `[crying]`, `[excited]`, etc.) directly into the text — making the emotional intent explicit and human-readable
3. **Maps emotions to vocal parameters** (rate, pitch, volume) and applies them to the generated audio
4. **Synthesizes speech** via gTTS (Google TTS) with audio post-processing via pydub
5. **Serves a web UI** where you can type text, see the bracketed output, and play/download the generated audio

---

## Pipeline Architecture

```
Input Text
    │
    ▼
┌─────────────────────────────────┐
│  Emotion Detection              │
│  • VADER sentiment (compound)   │
│  • Keyword pattern matching     │
│  • Intensity scoring (0–1)      │
└──────────────┬──────────────────┘
               │  emotion + intensity
               ▼
┌─────────────────────────────────┐
│  Bracket Injection              │
│  "[angry] [raised voice] text"  │
│  (intensity scales # of tags)   │
└──────────────┬──────────────────┘
               │  bracketed text
               ▼
┌─────────────────────────────────┐
│  TTS Synthesis (gTTS)           │
│  Text → raw MP3                 │
└──────────────┬──────────────────┘
               │  raw audio
               ▼
┌─────────────────────────────────┐
│  Audio Modulation (pydub)       │
│  • Rate (speed) factor          │
│  • Volume (dB) factor           │
│  • Intensity-scaled effect      │
└──────────────┬──────────────────┘
               │
               ▼
        Final .mp3 file
        (auto-played + downloadable)
```

---

## Emotion Categories

| Emotion      | Brackets injected                    | Rate  | Pitch | Volume |
|--------------|--------------------------------------|-------|-------|--------|
| `anger`      | `[angry]` `[raised voice]`           | ↑ 15% | ↓ 2   | ↑ 30%  |
| `sadness`    | `[sad]` `[crying]` `[slow]`          | ↓ 25% | ↓ 4   | ↓ 20%  |
| `excited`    | `[excited]` `[fast]` `[high pitch]`  | ↑ 30% | ↑ 5   | ↑ 20%  |
| `happy`      | `[happy]` `[cheerful]`               | ↑ 10% | ↑ 3   | ↑ 10%  |
| `anxious`    | `[nervous]` `[fast]` `[worried]`     | ↑ 20% | ↑ 2   | ↓ 10%  |
| `inquisitive`| `[curious]` `[thoughtful]`           | → 0%  | ↑ 1   | → 0%   |
| `surprised`  | `[surprised]` `[shocked]`            | ↑ 10% | ↑ 4   | ↑ 15%  |
| `concerned`  | `[concerned]` `[soft voice]`         | ↓ 10% | ↓ 1   | ↓ 15%  |
| `frustrated` | `[frustrated]` `[sighing]`           | ↓ 15% | ↓ 2   | ↓ 5%   |
| `neutral`    | `[neutral]`                          | → 0%  | → 0   | → 0%   |

**Intensity scaling**: All parameter changes are multiplied by the detected intensity (0–1), so `"This is good"` gets a subtle boost while `"THIS IS THE BEST THING EVER!"` gets maximum modulation.

---

## Setup & Installation

---
## 🐳 Run with Docker

You can run the Empathy Engine using Docker (no manual setup required).

### Prerequisites
- Docker installed
- Docker Compose installed

### Steps

```bash
cd empathy-engine

# Build and start the container
docker-compose up --build
```

## Manual Setup
### Prerequisites
- Python 3.9+
- `ffmpeg` installed on your system (required by pydub for audio conversion)

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg

# Windows — download from https://ffmpeg.org/download.html
```

### 1. Clone the repo

```bash
git clone https://github.com/YOUR_USERNAME/empathy-engine.git
cd empathy-engine
```

### 2. Create a virtual environment

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the app

```bash
python app.py
```

Open your browser at **http://localhost:5000**

---

## Usage

1. Type any sentence into the text box
2. Click **Synthesize Speech**
3. The UI will display:
   - The detected **emotion** with an intensity bar
   - The **bracketed text** that was sent to TTS (e.g. `[angry] [raised voice] I can't believe you did that!`)
   - An **audio player** — audio plays automatically
   - A **Download** button to save the `.mp3`

### Example inputs to try

| Text | Expected Emotion |
|------|-----------------|
| `"I can't believe you did that, I'm furious!"` | anger |
| `"This is the best news I've ever heard, I'm so thrilled!"` | excited |
| `"I'm sorry, there seems to be a problem with your order."` | concerned |
| `"I don't know... why would that even happen?"` | inquisitive |
| `"I'm just so tired of everything, I can't go on."` | sadness |

---

## Design Decisions

### Why brackets?
Bracket tags like `[angry]` serve two purposes: (1) they make the emotional intent **human-readable** in the UI, and (2) they mirror the "prompt engineering" approach used in modern expressive TTS models (e.g. ElevenLabs, Bark) where emotion tags in the input text influence the model's prosody.

### Why VADER + rules?
VADER is fast, offline, and highly effective for social-media style text. The keyword rule layer adds **granular emotion categories** beyond positive/negative/neutral, catching specific emotions like `anxious`, `inquisitive`, and `surprised` that pure sentiment analysis misses.

### Why pydub for audio effects?
gTTS produces clean, natural-sounding audio. Rather than relying on a heavyweight voice cloning API, pydub provides deterministic, lightweight audio transformations (speed, volume) that directly correspond to the emotion parameters — keeping the system fully self-contained and cost-free.

### Intensity scaling
Every parameter change is multiplied by the intensity score (0–1). This means the system behaves proportionally: a mildly positive sentence gets a small pitch lift; an ecstatically positive sentence gets the full effect. This was a core design goal to avoid jarring, over-exaggerated output on subtle emotions.

---

## Stretch Goals Implemented

- ✅ **Granular emotions** — 9 distinct emotional categories beyond positive/negative/neutral
- ✅ **Intensity scaling** — degree of modulation scales with emotional strength
- ✅ **Web interface** — Flask UI with text input, emotion display, and embedded audio player
- ✅ **Bracket injection** — explicit emotion tags injected into text before synthesis
- ✅ **Auto-play + download** — audio plays automatically and can be saved

---

## Project Structure

```
empathy-engine/
├── app.py                  # Main Flask application
├── requirements.txt        # Python dependencies
├── README.md               # This file
├── templates/
│   └── index.html          # Web UI
└── static/
    └── audio/              # Generated audio files (auto-created)
```

---

## License
MIT
