"""check_voice.py - run THIS on your laptop when transcription is wrong.

Records 4s, prints what the mic actually captured (levels, clipping,
both engine transcripts) and saves sample.wav — play it back: if YOU
can't hear yourself clearly in it, no software can transcribe it.

Usage:  python check_voice.py
    Say a full sentence, e.g. "Hello blacksmith, I need work".
"""
import os
import struct
import wave

import numpy as np

import voice

SECS = 4


def stats(pcm):
    x = np.asarray(pcm, dtype=float)
    peak = float(np.max(np.abs(x)))
    rms = float(np.sqrt((x ** 2).mean()))
    clip = float((np.abs(x) > 0.98).mean() * 100)
    quiet = float((np.abs(x) < 0.02).mean() * 100)
    return peak, rms, clip, quiet


def main():
    ok, info = voice.check_mic()
    print("mic:", "OK " if ok else "FAIL", "-", info)
    if not ok:
        return
    print(f"\nSpeak a full sentence NOW ({SECS}s recording)...")
    try:
        pcm = voice.record(SECS)
    except RuntimeError as e:
        print("record failed:", e)
        return
    peak, rms, clip, quiet = stats(pcm)
    print(f"level: peak={peak:.2f} rms={rms:.3f} clipped={clip:.1f}% silence={quiet:.0f}%")
    if peak < 0.05:
        print("VERDICT: far too quiet — move closer, raise mic gain "
              "(Windows Sound settings > Input volume), or pick another device.")
    elif clip > 5:
        print("VERDICT: clipping — too loud/close, back off or lower gain.")
    elif quiet > 80:
        print("VERDICT: mostly silence — wrong input device selected, or you started late.")
    else:
        print("VERDICT: levels look fine — problem is accent/language or background noise.")

    wav = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sample.wav")
    with wave.open(wav, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(voice.SAMPLE_RATE)
        f.writeframes(struct.pack("<%dh" % len(pcm),
                                  *[int(max(-1.0, min(1.0, float(v))) * 32767) for v in pcm]))
    print("saved:", wav, "-- play it. Unclear to you = unclear to the AI.")

    print("\n--- Google STT ---")
    try:
        import speech_recognition as sr
        raw = struct.pack("<%dh" % len(pcm),
                          *[int(max(-1.0, min(1.0, float(v))) * 32767) for v in pcm])
        audio = sr.AudioData(raw, voice.SAMPLE_RATE, 2)
        for lang in (os.getenv("VOICE_LANG", "en-IN"), "en-US"):
            try:
                print(f"[{lang}]:", sr.Recognizer().recognize_google(audio, language=lang))
            except Exception as e:
                print(f"[{lang}] failed:", str(e)[:70])
    except ImportError:
        print("SpeechRecognition not installed")

    print("\n--- Vosk offline STT ---")
    try:
        print("vosk:", voice._transcribe_vosk(raw) or "(heard nothing)")
    except RuntimeError as e:
        print("vosk unavailable:", e)


if __name__ == "__main__":
    main()
