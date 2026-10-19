"""Run: .venv/bin/python tests_score.py"""
import sys, tempfile
import numpy as np, soundfile as sf
import score
from score import pace_score, fluency_score, score_attempt

def test_no_asr():
    import server  # noqa: F401
    assert "whisper" not in sys.modules and not hasattr(score, "transcribe")

def test_pace():
    assert pace_score(1.0) == 100 and pace_score(0.5) == 30 and pace_score(1.3) == 70

def test_fluency():
    assert fluency_score([], []) == 100 and fluency_score([[1, 1.5]], []) == 65

def test_self_is_100():
    r = score_attempt("samples/es_hola_ref_neural.mp3", "samples/es_hola_ref_neural.mp3", "foreign")
    assert r["overall"] == 100 and r["passed"] and r["anti_cheat"]["pass"]

def test_wrong_content_rejected():
    r = score_attempt("samples/es_hola_ref_neural.mp3", "samples/ja_arigatou_ref.mp3", "foreign")
    assert not r["anti_cheat"]["pass"] and not r["passed"] and r["overall"] <= 20
    assert r["tips"][0].startswith("⚠️")

def test_silence_rejected():
    f = tempfile.mktemp(suffix=".wav"); sf.write(f, np.random.randn(22050).astype("float32") * 1e-4, 22050)
    r = score_attempt("samples/en_nice_ref.mp3", f, "foreign")
    assert not [c for c in r["anti_cheat"]["checks"] if c["id"] == "voice"][0]["pass"]

def test_meme_dims_and_hum_profile():
    r = score_attempt("samples/a_near_perfect_ref.wav", "samples/a_near_perfect_user.wav", "meme", "hum")
    assert {k: v["weight"] for k, v in r["dims"].items()} == {"rhythm": .40, "contour": .35, "similarity": .15, "loudness": .10}
    assert r["passed"] and r["overall"] > 75

def test_series_small():
    import json
    r = score_attempt("samples/es_hola_ref_neural.mp3", "samples/es_hola_ref.wav", "foreign")
    assert len(json.dumps(r)) < 80_000 and len(r["series"]["sim_strip"]["sim"]) > 10

if __name__ == "__main__":
    for k, f in list(globals().items()):
        if k.startswith("test_"):
            f(); print("ok", k)
