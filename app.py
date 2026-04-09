"""
Empathy Engine v4 — Flask Web App
Python 3.13 compatible — NO pydub, NO pyaudioop.

Audio pipeline:
  gTTS  →  mp3 file
  ffmpeg subprocess  →  decode mp3 → raw PCM (wav)
  numpy  →  speed/volume modulation on raw PCM
  soundfile  →  write modulated wav
  ffmpeg subprocess  →  encode final wav → mp3
  All sentence mp3s stitched via ffmpeg concat demuxer
"""

import os
import re
import uuid
import math
import shutil
import subprocess
import tempfile
from flask import Flask, render_template, request, jsonify, send_from_directory

# ── Emotion Detection ─────────────────────────────────────────────────────────
try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
    VADER_AVAILABLE = True
except ImportError:
    VADER_AVAILABLE = False

# ── TTS ───────────────────────────────────────────────────────────────────────
try:
    from gtts import gTTS
    GTTS_AVAILABLE = True
except ImportError:
    GTTS_AVAILABLE = False

# ── Numpy + Soundfile (Python 3.13 safe, no pyaudioop) ───────────────────────
try:
    import numpy as np
    import soundfile as sf
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

# ── Locate ffmpeg ─────────────────────────────────────────────────────────────
def _find_ffmpeg():
    found = shutil.which("ffmpeg")
    if found:
        return found
    for candidate in [
        r"C:\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
        r"C:\Program Files (x86)\ffmpeg\bin\ffmpeg.exe",
    ]:
        if os.path.isfile(candidate):
            return candidate
    return None

FFMPEG = _find_ffmpeg()

def ffmpeg_ok():
    return FFMPEG is not None

def run_ffmpeg(*args, check=True):
    """Run ffmpeg with given args list, suppress console output."""
    cmd = [FFMPEG] + list(args)
    result = subprocess.run(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"ffmpeg error: {result.stderr.decode(errors='replace')}")
    return result

app = Flask(__name__)
AUDIO_DIR = os.path.join("static", "audio")
os.makedirs(AUDIO_DIR, exist_ok=True)


# =============================================================================
# 1.  SENTENCE SPLITTER
# =============================================================================

def split_sentences(text: str) -> list:
    parts = re.split(r'(?<=[.!?])\s+', text.strip())
    sentences = []
    for part in parts:
        sub = re.split(r'\s*—\s*|\n+', part)
        sentences.extend([s.strip() for s in sub if s.strip()])
    return sentences


# =============================================================================
# 2.  EMOTION DETECTION
# =============================================================================

EMOTION_RULES = [
    (r"\b(furious|angry|hate|disgusting|outraged|infuriating|terrible|awful|dreadful|rage)\b", "anger"),
    (r"\b(sad|cry|crying|tears|heartbroken|devastated|depressed|miserable|grief|loss|mourning)\b", "sadness"),
    (r"\b(amazing|fantastic|wonderful|brilliant|excellent|incredible|thrilled|ecstatic|overjoyed|best)\b", "excited"),
    (r"\b(happy|great|good|glad|pleased|delighted|enjoy|yay|congrats|excited about)\b", "happy"),
    (r"\b(worried|anxious|nervous|scared|afraid|fearful|terrified|dread|panic|uneasy|bit anxious)\b", "anxious"),
    (r"\b(why|how|what|when|where|curious|wonder|interesting|strange|odd|inquisitive|learn|understand|improve)\b", "inquisitive"),
    (r"\b(wow|whoa|unbelievable|shocked|surprised|astonished|no way|genuinely surprised)\b", "surprised"),
    (r"\b(sorry|unfortunately|regret|problem|issue|concern|careful|warning|caution|concerned|might arise)\b", "concerned"),
    (r"\b(ugh|sigh|whatever|boring|tired|exhausted|meh|delays|frustrated|annoying|quite frustrated)\b", "frustrated"),
]

def detect_emotion(text: str) -> dict:
    lower = text.lower()
    hits = {}
    for pattern, label in EMOTION_RULES:
        count = len(re.findall(pattern, lower))
        if count:
            hits[label] = hits.get(label, 0) + count

    compound = 0.0
    if VADER_AVAILABLE:
        compound = _vader.polarity_scores(text)["compound"]

    if hits:
        primary = max(hits, key=hits.get)
        word_count = max(len(text.split()), 1)
        kw_intensity = min(hits[primary] / word_count * 5, 1.0)
        intensity = min((kw_intensity + abs(compound)) / 2 * 1.5, 1.0)
    else:
        if compound >= 0.5:   primary, intensity = "excited",   abs(compound)
        elif compound >= 0.15: primary, intensity = "happy",    abs(compound)
        elif compound <= -0.5: primary, intensity = "frustrated", abs(compound)
        elif compound <= -0.15:primary, intensity = "concerned", abs(compound)
        else:                  primary, intensity = "neutral",  0.2

    return {"emotion": primary, "intensity": round(intensity, 3), "compound": round(compound, 3)}


# =============================================================================
# 3.  VOCAL PARAMETERS + DISPLAY TAGS
# =============================================================================

EMOTION_DISPLAY_TAGS = {
    "anger":       ["[angry]", "[raised voice]"],
    "sadness":     ["[sad]", "[slow]", "[soft]"],
    "excited":     ["[excited]", "[fast]", "[high pitch]"],
    "happy":       ["[happy]", "[cheerful]"],
    "anxious":     ["[nervous]", "[fast]"],
    "inquisitive": ["[curious]", "[thoughtful]"],
    "surprised":   ["[surprised]", "[shocked]"],
    "concerned":   ["[concerned]", "[soft voice]"],
    "frustrated":  ["[frustrated]", "[sighing]"],
    "neutral":     ["[neutral]"],
}

VOICE_PARAMS = {
    "anger":       {"rate_factor": 1.18, "volume_factor": 1.35},
    "sadness":     {"rate_factor": 0.72, "volume_factor": 0.78},
    "excited":     {"rate_factor": 1.32, "volume_factor": 1.20},
    "happy":       {"rate_factor": 1.10, "volume_factor": 1.10},
    "anxious":     {"rate_factor": 1.22, "volume_factor": 0.88},
    "inquisitive": {"rate_factor": 0.97, "volume_factor": 1.00},
    "surprised":   {"rate_factor": 1.12, "volume_factor": 1.18},
    "concerned":   {"rate_factor": 0.88, "volume_factor": 0.82},
    "frustrated":  {"rate_factor": 0.83, "volume_factor": 0.92},
    "neutral":     {"rate_factor": 1.00, "volume_factor": 1.00},
}

def get_display_tags(emotion: str, intensity: float) -> list:
    tags = EMOTION_DISPLAY_TAGS.get(emotion, ["[neutral]"])
    if intensity >= 0.65:   return tags
    elif intensity >= 0.35: return tags[:2] if len(tags) >= 2 else tags
    else:                   return tags[:1]


# =============================================================================
# 4.  AUDIO MODULATION  — numpy + soundfile, no pydub/pyaudioop
# =============================================================================

def mp3_to_wav(mp3_path: str, wav_path: str):
    """Decode mp3 → wav using ffmpeg subprocess."""
    run_ffmpeg("-y", "-i", mp3_path, "-ar", "22050", "-ac", "1", wav_path)

def wav_to_mp3(wav_path: str, mp3_path: str):
    """Encode wav → mp3 using ffmpeg subprocess."""
    run_ffmpeg("-y", "-i", wav_path, "-codec:a", "libmp3lame", "-q:a", "4", mp3_path)

def modulate_wav(wav_in: str, wav_out: str, emotion: str, intensity: float):
    """
    Read PCM wav with soundfile, apply speed + volume via numpy, write back.
    Speed change: resample by changing the declared sample rate (no pyaudioop needed).
    Volume change: multiply samples by scalar.
    """
    params = VOICE_PARAMS.get(emotion, VOICE_PARAMS["neutral"])

    data, samplerate = sf.read(wav_in, dtype="float32")

    # ── Volume ────────────────────────────────────────────────────────────────
    vol_scaled = 1.0 + (params["volume_factor"] - 1.0) * intensity
    data = data * vol_scaled
    data = np.clip(data, -1.0, 1.0)

    # ── Speed (rate) ─────────────────────────────────────────────────────────
    # Writing with a different samplerate than the original makes ffmpeg/players
    # play back at a different speed — same approach as pydub's frame-rate trick,
    # but implemented directly on the numpy array via soundfile.
    rate_scaled = 1.0 + (params["rate_factor"] - 1.0) * intensity
    new_samplerate = max(8000, int(samplerate * rate_scaled))

    sf.write(wav_out, data, new_samplerate)

def silence_wav(wav_path: str, duration_ms: int = 380):
    """Write a short silence WAV file."""
    sr = 22050
    samples = int(sr * duration_ms / 1000)
    silence = np.zeros(samples, dtype="float32")
    sf.write(wav_path, silence, sr)


# =============================================================================
# 5.  SYNTHESIZE ONE SENTENCE
# =============================================================================

def synthesize_sentence_mp3(plain_text: str, emotion: str, intensity: float, out_mp3: str):
    """
    Synthesize a single plain-text sentence → modulated mp3.
    Brackets are NEVER passed here — only clean text.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        raw_mp3  = os.path.join(tmp_dir, "raw.mp3")
        raw_wav  = os.path.join(tmp_dir, "raw.wav")
        mod_wav  = os.path.join(tmp_dir, "mod.wav")

        # 1. gTTS → raw mp3 (clean text, no brackets)
        use_slow = (emotion == "sadness" and intensity > 0.5)
        tts = gTTS(text=plain_text, lang="en", slow=use_slow)
        tts.save(raw_mp3)

        # 2. Decode to wav
        mp3_to_wav(raw_mp3, raw_wav)

        # 3. Modulate with numpy (Python 3.13 safe)
        modulate_wav(raw_wav, mod_wav, emotion, intensity)

        # 4. Encode back to mp3
        wav_to_mp3(mod_wav, out_mp3)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# 6.  STITCH ALL SENTENCE MP3s WITH SILENCE GAPS
# =============================================================================

def stitch_mp3s(mp3_files: list, silence_ms: int, out_mp3: str):
    """
    Concatenate a list of mp3 files with silence between them using ffmpeg
    concat demuxer — no pydub needed.
    """
    tmp_dir = tempfile.mkdtemp()
    try:
        # Convert all inputs to uniform wav
        wav_files = []
        for i, mp3 in enumerate(mp3_files):
            wav = os.path.join(tmp_dir, f"seg_{i}.wav")
            mp3_to_wav(mp3, wav)
            wav_files.append(wav)

        # Insert silence between sentences
        silence_wav_path = os.path.join(tmp_dir, "silence.wav")
        silence_wav(silence_wav_path, silence_ms)

        # Build concat list
        concat_list_path = os.path.join(tmp_dir, "concat.txt")
        combined_wavs = []
        for i, wav in enumerate(wav_files):
            combined_wavs.append(wav)
            if i < len(wav_files) - 1:
                combined_wavs.append(silence_wav_path)

        with open(concat_list_path, "w") as f:
            for wav in combined_wavs:
                # ffmpeg concat demuxer requires forward slashes even on Windows
                f.write(f"file '{wav.replace(chr(92), '/')}'\n")

        # Merged wav
        merged_wav = os.path.join(tmp_dir, "merged.wav")
        run_ffmpeg("-y", "-f", "concat", "-safe", "0",
                   "-i", concat_list_path, merged_wav)

        # Final mp3
        wav_to_mp3(merged_wav, out_mp3)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


# =============================================================================
# 7.  MAIN PIPELINE
# =============================================================================

def process_passage(text: str) -> dict:
    sentences = split_sentences(text)
    if not sentences:
        raise ValueError("No sentences detected in input.")

    annotated_sentences = []
    sentence_mp3s = []

    for sentence in sentences:
        if not sentence.strip():
            continue

        detection    = detect_emotion(sentence)
        emotion      = detection["emotion"]
        intensity    = detection["intensity"]
        display_tags = get_display_tags(emotion, intensity)

        annotated_sentences.append({
            "original":      sentence,
            "emotion":       emotion,
            "intensity":     intensity,
            "compound":      detection["compound"],
            "display_tags":  display_tags,
            "annotated_text": " ".join(display_tags) + " " + sentence,
        })

        # Synthesize this sentence to a temp mp3
        seg_mp3 = os.path.join(AUDIO_DIR, f"_seg_{uuid.uuid4().hex}.mp3")
        synthesize_sentence_mp3(sentence, emotion, intensity, seg_mp3)
        sentence_mp3s.append(seg_mp3)

    if not sentence_mp3s:
        raise RuntimeError("No audio generated.")

    # Stitch all segments into final file
    final_filename = f"{uuid.uuid4().hex}.mp3"
    final_path = os.path.join(AUDIO_DIR, final_filename)
    stitch_mp3s(sentence_mp3s, silence_ms=380, out_mp3=final_path)

    # Clean up individual segment files
    for f in sentence_mp3s:
        try: os.remove(f)
        except: pass

    return {
        "original_text":       text,
        "annotated_sentences": annotated_sentences,
        "audio_url":           f"/static/audio/{final_filename}",
        "audio_filename":      final_filename,
    }


# =============================================================================
# 8.  FLASK ROUTES
# =============================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/debug")
def debug_route():
    return jsonify({
        "python_ok":       True,
        "ffmpeg_path":     FFMPEG,
        "ffmpeg_ok":       ffmpeg_ok(),
        "gtts_available":  GTTS_AVAILABLE,
        "numpy_available": NUMPY_AVAILABLE,
        "vader_available": VADER_AVAILABLE,
        "note":            "pydub removed — using numpy+soundfile+ffmpeg directly (Python 3.13 safe)"
    })


@app.route("/synthesize", methods=["POST"])
def synthesize_route():
    data = request.get_json(force=True)
    text = (data.get("text") or "").strip()

    if not text:
        return jsonify({"error": "No text provided."}), 400
    if len(text) > 1500:
        return jsonify({"error": "Text too long (max 1500 chars)."}), 400
    if not GTTS_AVAILABLE:
        return jsonify({"error": "gTTS not installed. Run: pip install gtts"}), 500
    if not NUMPY_AVAILABLE:
        return jsonify({"error": "numpy or soundfile not installed. Run: pip install numpy soundfile"}), 500
    if not ffmpeg_ok():
        return jsonify({"error": "ffmpeg not found. Make sure ffmpeg.exe is on your PATH."}), 500

    try:
        result = process_passage(text)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    return jsonify(result)


@app.route("/static/audio/<path:filename>")
def serve_audio(filename):
    return send_from_directory(AUDIO_DIR, filename)


if __name__ == "__main__":
    # 0.0.0.0 makes Flask reachable from outside the container
    app.run(host="0.0.0.0", debug=True, port=5000)
