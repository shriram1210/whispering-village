"""voice.py - push-to-talk + vocal expression detection for Whispering Village.

Pipeline: mic -> speech-to-text -> prosody (numpy only) -> expression ->
trust delta fused into npc.talk(voice=...).

Expressions: kind, genuine/calm, overconfident, nervous, sad, rude, deceptive.
Heuristic thresholds (documented, tunable); research basis: rising intonation +
quiet onset + slower rate reads as uncertain (Nature Comm. 2020), raised pitch
max + intensity max mark deception (Levitan et al. 2018). Per-player calibration
via calibrate() beats fixed thresholds for real users.

Everything degrades gracefully: no mic / no net / no key -> (None, {"error":...})
and the game continues on typed text.
"""
import time
import os

SAMPLE_RATE = 16000

LABELS = ("kind", "genuine", "overconfident", "nervous", "sad", "rude", "deceptive", "neutral")

_baseline = {}  # name -> {"f0_mean","rate","rms_mean"} from calibrate()


def calibrate(pcm, name="player", sr=SAMPLE_RATE):
    """Record 3-4s of the player's NEUTRAL voice once; later classifications
    compare against it instead of fixed thresholds. Returns the baseline."""
    f = prosody(pcm, sr)
    _baseline[name] = {"f0_mean": f["f0_mean"], "rate": f["rate"], "rms_mean": f["rms_mean"]}
    return _baseline[name]

_POLITE = ("please", "thank", "sorry", "sir", "kind", "hello", "hey", "namaste",
           "appreciate", "friend", "dhanyavad", "shukriya")
_RUDE = ("stupid", "idiot", "hate", "fool", "useless", "ugly", "worst", "shut up")
_BOAST = ("greatest", "hero", "richest", "king", "killed", "legend")


# ---------- recording / transcription (lazy imports: module stays import-safe) ----------
def record(seconds=4.0):
    """Record mono 16kHz PCM. Raises RuntimeError with a human message on failure."""
    try:
        import sounddevice as sd
    except ImportError:
        raise RuntimeError("voice chat needs: pip install sounddevice")
    try:
        import numpy as np
    except ImportError:
        raise RuntimeError("voice chat needs numpy")
    try:
        audio = sd.rec(int(seconds * SAMPLE_RATE), samplerate=SAMPLE_RATE,
                       channels=1, dtype="float32", blocking=True)
    except Exception as e:
        raise RuntimeError(f"no microphone available ({str(e)[:80]})")
    return audio[:, 0]


def transcribe(pcm):
    """Speech-to-text: free Google endpoint first, offline Vosk fallback.
    Raises RuntimeError only if both fail (game then keeps typed input)."""
    import struct
    raw = struct.pack("<%dh" % len(pcm),
                      *[int(max(-1.0, min(1.0, float(v))) * 32767) for v in pcm])
    gmsg = "SpeechRecognition not installed"
    try:
        import speech_recognition as sr
        audio = sr.AudioData(raw, SAMPLE_RATE, 2)
        try:
            return sr.Recognizer().recognize_google(audio)
        except Exception as e:
            gmsg = str(e)[:80] or "unintelligible"
    except ImportError:
        pass
    try:
        text = _transcribe_vosk(raw)
    except RuntimeError as e:
        raise RuntimeError(f"speech-to-text failed (Google: {gmsg}; {e})")
    if not text:
        raise RuntimeError(f"speech-to-text unclear (Google: {gmsg}; offline heard nothing)")
    return text


_VOSK_MODEL = None


def _vosk_model():
    """Lazy-load the bundled offline model (assets/vosk-model/...). Cached."""
    global _VOSK_MODEL
    if _VOSK_MODEL is None:
        try:
            from vosk import Model
        except ImportError:
            raise RuntimeError("pip install vosk for offline speech-to-text")
        here = os.path.dirname(os.path.abspath(__file__))
        cands = [os.path.join(here, "assets", "vosk-model", "vosk-model-small-en-us-0.15"),
                 os.path.join(here, "assets", "vosk-model")]
        for cand in cands:
            if os.path.isdir(cand) and any(os.scandir(cand)):
                try:
                    _VOSK_MODEL = Model(cand)
                except Exception as e:
                    raise RuntimeError(f"vosk model broken ({str(e)[:60]})")
                break
        if _VOSK_MODEL is None:
            raise RuntimeError("vosk model missing in assets/vosk-model (see README)")
    return _VOSK_MODEL


def _transcribe_vosk(raw):
    import json as _json
    from vosk import KaldiRecognizer
    rec = KaldiRecognizer(_vosk_model(), SAMPLE_RATE)
    rec.AcceptWaveform(raw)
    return _json.loads(rec.FinalResult()).get("text", "").strip()


# ---------- prosody (numpy only) ----------
def prosody(pcm, sr=SAMPLE_RATE):
    import numpy as np
    x = np.asarray(pcm, dtype=float)
    if x.size < sr // 2:
        raise ValueError("clip too short (<0.5s)")
    peak = float(np.max(np.abs(x))) or 1e-6
    size, hop = int(sr * 0.03), int(sr * 0.01)
    n = 1 + (x.size - size) // hop
    idx = (np.arange(size)[None, :] + hop * np.arange(n)[:, None])
    frames = x[idx]
    rms = np.sqrt((frames ** 2).mean(axis=1))
    noise = float(np.median(rms))
    # peak-anchored + absolute floor: flat tones stay voiced, gaps/silence drop out
    thr = max(peak * 0.08, 0.005)
    voiced = rms > thr
    zcr = ((frames[:, :-1] < 0) != (frames[:, 1:] < 0)).mean(axis=1)

    def f0_of(frame):
        frame = frame - frame.mean()
        ac = np.correlate(frame, frame, "full")[len(frame) - 1:]
        lo, hi = max(2, sr // 300), min(len(ac) - 1, sr // 75)  # 75-300Hz: above is octave error
        if hi <= lo:
            return 0.0
        k = lo + int(np.argmax(ac[lo:hi]))
        return float(sr / k) if ac[k] > 0 else 0.0

    f0s = [f0_of(frames[i]) if voiced[i] else 0.0 for i in range(n)]
    vf = [f for f in f0s if f > 0]
    if len(vf) < 5:
        raise ValueError("no voiced speech detected")
    vf = np.array(vf)
    med = float(np.median(vf))  # trim octave-error outliers before stats
    vf = vf[(vf >= med * 0.5) & (vf <= med * 2.0)]
    if len(vf) < 5:
        raise ValueError("no stable voiced speech detected")
    thirds = np.array_split(vf, 3)
    slope = float(np.median(thirds[-1]) - np.median(thirds[0]))

    env = rms / (rms.max() or 1e-6)
    smooth = np.convolve(env, np.ones(5) / 5, mode="same")
    onsets = int(((smooth[1:] > 0.4) & (smooth[:-1] <= 0.4)).sum())
    voiced_sec = float(voiced.sum() * hop / sr) or 1e-3
    return {
        "rms_mean": float(rms.mean() / (peak or 1e-6)),
        "rms_max": float(rms.max() / (peak or 1e-6)),
        "rms_var": float(rms.var() / ((peak or 1e-6) ** 2)),
        "f0_mean": float(vf.mean()), "f0_std": float(vf.std()),
        "f0_max": float(vf.max()), "f0_range": float(vf.max() - vf.min()),
        "f0_slope": slope,
        "jitter": float(np.mean(np.abs(np.diff(vf))) / (vf.mean() or 1e-6)),
        "rate": onsets / voiced_sec,           # syllable-ish onsets per voiced second
        "pause_ratio": 1.0 - float(voiced.mean()),
        "zcr": float(zcr[voiced].mean()) if voiced.any() else 0.0,
        "voiced_sec": voiced_sec,
    }


# ---------- text sentiment (VADER, keyword fallback) ----------
def text_mood(text):
    low = (text or "").lower()
    try:
        from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
        compound = SentimentIntensityAnalyzer().polarity_scores(text or "")["compound"]
    except Exception:
        pos = sum(1 for w in _POLITE if w in low)
        neg = sum(1 for w in _RUDE if w in low)
        compound = max(-1.0, min(1.0, 0.4 * pos - 0.5 * neg))
    return compound


# ---------- expression classification (rule table, see module docstring) ----------
def classify(feat, text="", base=None):
    low, compound = (text or "").lower(), text_mood(text)
    base = base or _baseline.get("player") or {}
    f0_ref = base.get("f0_mean", 140.0)   # personal neutral pitch if calibrated
    cues = lambda n: n  # count helper readability
    rude_w = any(w in low for w in _RUDE)
    boast_w = any(w in low for w in _BOAST)
    polite_w = any(w in low for w in _POLITE)

    if rude_w or (feat["rms_var"] > 0.02 and feat["f0_mean"] > f0_ref * 1.2 and feat["rate"] > 3.5):
        return {"label": "rude", "trust_delta": -6, "confidence": min(0.9, 0.55 + 0.15 * cues(rude_w + 1)),
                "mood": "angry", "vader": compound}
    if boast_w or (feat["rate"] > 4.2 and feat["f0_range"] > 90 and feat["f0_slope"] < -8):
        delta = -5 if boast_w else 2
        return {"label": "overconfident", "trust_delta": delta, "confidence": 0.7,
                "mood": "suspicious" if boast_w else "confident", "vader": compound}
    if feat["pause_ratio"] > 0.30 and feat["rate"] < 2.6 and feat["f0_slope"] > 6:
        return {"label": "nervous", "trust_delta": 1, "confidence": 0.65,
                "mood": "nervous", "vader": compound}
    if feat["f0_mean"] < 115 and feat["f0_range"] < 55 and feat["pause_ratio"] > 0.22:
        return {"label": "sad", "trust_delta": 3, "confidence": 0.7,
                "mood": "sad", "vader": compound}
    if feat["jitter"] > 0.06 and feat["f0_max"] > feat["f0_mean"] * 1.5 and feat["rate"] < 3.0 \
            and feat["pause_ratio"] < 0.35:
        return {"label": "deceptive", "trust_delta": -4, "confidence": 0.6,
                "mood": "suspicious", "vader": compound}
    if polite_w or compound > 0.4:
        return {"label": "kind", "trust_delta": 4 + (2 if compound > 0.6 else 0),
                "confidence": min(0.9, 0.6 + abs(compound) * 0.4), "mood": "warm", "vader": compound}
    if feat["pause_ratio"] < 0.15 and feat["f0_std"] < 28 and 2.4 <= feat["rate"] <= 4.2:
        return {"label": "genuine", "trust_delta": 2, "confidence": 0.6,
                "mood": "neutral", "vader": compound}
    return {"label": "neutral", "trust_delta": 2 if compound > 0.2 else (-2 if compound < -0.2 else 0),
            "confidence": 0.5, "mood": "neutral", "vader": compound}


def analyze(pcm, text="", sr=SAMPLE_RATE):
    """Full voice analysis. Returns dict; on failure returns {"label":"neutral",...,"error":...}."""
    try:
        feat = prosody(pcm, sr)
    except Exception as e:
        return {"label": "neutral", "trust_delta": 0, "confidence": 0.0,
                "mood": "neutral", "vader": text_mood(text), "error": f"prosody: {e}"}
    out = classify(feat, text)
    out["features"] = {k: round(float(v), 3) for k, v in feat.items()}
    return out


def check_mic():
    """Diagnostic: returns (ok: bool, message: str) about microphone availability."""
    try:
        import sounddevice as sd
    except ImportError:
        return False, "sounddevice not installed (pip install sounddevice)"
    try:
        devs = sd.query_devices()
        ins = [f"[{i}] {d['name']}" for i, d in enumerate(devs) if d["max_input_channels"] > 0]
        if not ins:
            return False, "no input devices found (mic unplugged/disabled in Windows Sound settings?)"
        try:
            default = sd.query_devices(kind="input")["name"]
        except Exception:
            default = "?"
        return True, f"default input: {default} | inputs: {'; '.join(ins[:4])}"
    except Exception as e:
        return False, f"cannot query audio devices ({str(e)[:80]})"


def listen_once(seconds=4.0):
    """Record -> transcribe -> analyze. Returns (text|None, result-dict). Never raises."""
    t0 = time.time()
    try:
        pcm = record(seconds)
    except RuntimeError as e:
        return None, {"label": "neutral", "trust_delta": 0, "confidence": 0.0,
                      "mood": "neutral", "vader": 0.0, "error": str(e)}
    try:
        text = transcribe(pcm)
    except RuntimeError as e:
        return None, {"label": "neutral", "trust_delta": 0, "confidence": 0.0,
                      "mood": "neutral", "vader": 0.0, "error": str(e)}
    out = analyze(pcm, text)
    out["latency"] = round(time.time() - t0, 2)
    return text, out
