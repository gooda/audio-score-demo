"""Threshold calibration: .venv/bin/python calibrate.py  -> prints table + writes calibration.json"""
import json, os, subprocess, sys, tempfile, time
import numpy as np, soundfile as sf
from score import score_attempt

A = "/home/box/agent-data/agents/f63b6a42-3b6a-43f9-9f29-d381c182acf8/attachments/"
TAKE_ES = A + "5a9f21281b5e9cf09c7025e1a509809800a0858ca590ecc521415f9d75894835.m4a"
TAKE_HUM = A + "834fa8ef513227032c5a289d47bb434d85fd5bda1e6fa8448225e57fd8292dbb.m4a"
L = json.load(open("levels.json", encoding="utf-8"))
ref = {l["id"]: "samples/" + l["ref"] for l in L}
mode = {l["id"]: l["mode"] for l in L}
prof = {l["id"]: l["profile"] for l in L}

tmp = tempfile.mkdtemp()
def opus(src):  # simulate browser MediaRecorder (webm/opus) round-trip
    out = os.path.join(tmp, os.path.basename(src) + ".webm")
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-c:a", "libopus", "-b:a", "48k", out], check=True)
    return out
sil = os.path.join(tmp, "silence.wav"); sf.write(sil, np.random.randn(44100).astype("float32") * 1e-4, 22050)
noise = os.path.join(tmp, "noise.wav"); sf.write(noise, np.random.randn(44100).astype("float32") * 0.2, 22050)

cases = []
for a in ref:
    cases.append(("自身", a, ref[a]))
    for b in ref:
        if b != a:
            cases.append(("错内容:" + b, a, ref[b]))
    cases.append(("静音", a, sil)); cases.append(("白噪声", a, noise))
cases += [("真实-西语", "es_hola", TAKE_ES), ("真实-哼唱", "hum_melody", TAKE_HUM),
          ("同句另一TTS", "es_hola", "samples/es_hola_ref.wav"),
          ("模拟录音opus-西语", "es_hola", opus(TAKE_ES)), ("模拟录音opus-哼唱", "hum_melody", opus("samples/a_near_perfect_user.wav")),
          ("合成近似", "hum_melody", "samples/a_near_perfect_user.wav")]
rows = []
for kind, lid, f in cases:
    t = time.time(); r = score_attempt(ref[lid], f, mode[lid], prof[lid]); dt = time.time() - t
    ac = r["anti_cheat"]
    rows.append({"kind": kind, "level": lid, "overall": r["overall"], "passed": r["passed"], "anti_cheat": ac["pass"],
                 "failed": [c["id"] for c in ac["checks"] if not c["pass"]], "dist": r["detail"]["spectral_distance"],
                 "sim": r["dims"]["similarity"]["score"], "syl": ac["checks"][1]["value"], "ms": round(dt * 1000)})
    x = rows[-1]
    print(f"{lid:14s} {kind:22s} 总分{x['overall']:5.1f} {'PASS' if x['passed'] else 'fail'} AC={'✓' if x['anti_cheat'] else '✗'+','.join(x['failed']):18s} d={x['dist']:.3f} sim={x['sim']:5.1f} syl={x['syl']} {x['ms']}ms")
json.dump(rows, open("calibration.json", "w"), ensure_ascii=False, indent=1)
wrong = [x for x in rows if x["kind"].startswith("错内容")]
print("\n错内容通过关卡:", sum(x["passed"] for x in wrong), "/", len(wrong), "  防作弊拦截:", sum(not x["anti_cheat"] for x in wrong))
