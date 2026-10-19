#!/usr/bin/env python3
"""FastAPI backend: python server.py  (PORT env, default 8765)."""
import json, os, shutil, tempfile, threading, time
from functools import lru_cache
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

import score

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
LEVELS = {l["id"]: l for l in json.loads((ROOT / "levels.json").read_text("utf-8"))}
app = FastAPI(title="音频模仿打分")
_lock = threading.Lock()  # keep numba/librosa calls serialized (cheap, sub-second)


@app.get("/api/levels")
def levels():
    return [{**l, "ref_url": f"/samples/{l['ref']}"} for l in LEVELS.values()]


@lru_cache(maxsize=32)
def _ref_series(fname):
    return score.ref_series(str(SAMPLES / fname))


@app.get("/api/levels/{lid}/ref")
def level_ref(lid: str):
    if lid not in LEVELS:
        raise HTTPException(404, "关卡不存在")
    return _ref_series(LEVELS[lid]["ref"])


def _save(up: UploadFile) -> str:
    fd, p = tempfile.mkstemp(suffix=Path(up.filename or "a.webm").suffix or ".webm")
    with os.fdopen(fd, "wb") as f:
        shutil.copyfileobj(up.file, f)
    return p


@app.post("/api/score")
def api_score(audio: UploadFile = File(...), level_id: str = Form(""),
              ref: UploadFile | None = File(None), mode: str = Form(""),
              profile: str = Form("")):
    """level_id 模式：用关卡示范音；否则上传 ref + mode=foreign|meme（+ 可选 profile=speech|hum）。"""
    tmp = [_save(audio)]
    try:
        if level_id:
            if level_id not in LEVELS:
                raise HTTPException(404, "关卡不存在")
            L = LEVELS[level_id]
            ref_path, mode, profile = str(SAMPLES / L["ref"]), mode or L["mode"], profile or L.get("profile", "speech")
        else:
            if ref is None or mode not in ("foreign", "meme"):
                raise HTTPException(400, "无 level_id 时需上传 ref 并指定 mode=foreign|meme")
            tmp.append(_save(ref)); ref_path = tmp[-1]
        t0 = time.perf_counter()
        with _lock:
            res = score.score_attempt(ref_path, tmp[0], mode, profile or None)
        res["elapsed_ms"] = round((time.perf_counter() - t0) * 1000)
        return res
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(422, f"评分失败：{e}")
    finally:
        for p in tmp:
            os.unlink(p)


app.mount("/samples", StaticFiles(directory=SAMPLES), name="samples")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8765)))
