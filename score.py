"""Audio mimic scoring: pitch, rhythm, content (proxy), loudness."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import librosa
import numpy as np
from scipy.ndimage import median_filter
from scipy.spatial.distance import cdist


SR = 22050
HOP = 256
FMIN = librosa.note_to_hz("C2")
FMAX = librosa.note_to_hz("C6")


@dataclass
class ScoreResult:
    overall: float
    pitch: float
    rhythm: float
    content: float
    loudness: float
    content_is_proxy: bool
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_audio(path: str, sr: int = SR) -> tuple[np.ndarray, int]:
    y, _ = librosa.load(path, sr=sr, mono=True)
    y, _ = librosa.effects.trim(y, top_db=30)
    if len(y) < sr // 10:
        raise ValueError("音频太短或几乎全是静音，请重新录制。")
    peak = np.max(np.abs(y)) + 1e-9
    y = y / peak * 0.9
    return y, sr


def extract_f0(y: np.ndarray, sr: int = SR) -> tuple[np.ndarray, np.ndarray]:
    """
    Prefer pyin. Stationary synth tones sometimes yield all-NaN;
    fall back to yin + octave repair, or pyin on lightly dithered audio.
    """
    times = None

    def _pyin(sig: np.ndarray) -> np.ndarray:
        f0, _, _ = librosa.pyin(
            sig,
            fmin=FMIN,
            fmax=FMAX,
            sr=sr,
            hop_length=HOP,
            fill_na=np.nan,
        )
        return f0

    f0 = _pyin(y)
    voiced = float(np.isfinite(f0).mean())

    if voiced < 0.1:
        # dither helps pyin lock onto pure tones
        rng = np.random.default_rng(0)
        y_d = y + rng.normal(0, 1e-4, size=y.shape).astype(y.dtype)
        f0 = _pyin(y_d)
        voiced = float(np.isfinite(f0).mean())

    if voiced < 0.1:
        f0_yin = librosa.yin(y, fmin=FMIN, fmax=FMAX, sr=sr, hop_length=HOP)
        f0_yin = median_filter(f0_yin, size=5)
        # drop implausible jumps / fold octaves toward median
        med = float(np.median(f0_yin))
        for i in range(len(f0_yin)):
            v = f0_yin[i]
            for _ in range(3):
                if v > med * 1.8:
                    v *= 0.5
                elif v < med * 0.55:
                    v *= 2.0
                else:
                    break
            f0_yin[i] = v
        f0 = f0_yin.astype(float)
        # mark low-energy frames unvoiced
        rms = librosa.feature.rms(y=y, hop_length=HOP)[0]
        thr = np.percentile(rms, 20)
        f0 = f0.copy()
        n = min(len(f0), len(rms))
        f0[:n][rms[:n] < thr] = np.nan

    times = librosa.times_like(f0, sr=sr, hop_length=HOP)
    return f0, times


def extract_onsets(y: np.ndarray, sr: int = SR) -> np.ndarray:
    oenv = librosa.onset.onset_strength(y=y, sr=sr, hop_length=HOP)
    onsets = librosa.onset.onset_detect(
        onset_envelope=oenv, sr=sr, hop_length=HOP, units="time", backtrack=True
    )
    return onsets


def extract_rms(y: np.ndarray, sr: int = SR) -> np.ndarray:
    return librosa.feature.rms(y=y, hop_length=HOP)[0]


def extract_mfcc(y: np.ndarray, sr: int = SR, n_mfcc: int = 13) -> np.ndarray:
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=n_mfcc, hop_length=HOP)
    d = librosa.feature.delta(mfcc)
    return np.vstack([mfcc, d])


def _nan_interp(f0: np.ndarray) -> np.ndarray:
    x = f0.copy()
    n = len(x)
    idx = np.arange(n)
    good = np.isfinite(x)
    if good.sum() < 2:
        return np.zeros(n)
    x[~good] = np.interp(idx[~good], idx[good], x[good])
    return x


def _hz_to_cents(f: np.ndarray, ref: float = 440.0) -> np.ndarray:
    f = np.maximum(f, 1e-6)
    return 1200.0 * np.log2(f / ref)


def dtw_align(seq_a: np.ndarray, seq_b: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    a = seq_a.reshape(-1, 1) if seq_a.ndim == 1 else seq_a.T
    b = seq_b.reshape(-1, 1) if seq_b.ndim == 1 else seq_b.T

    def z(x):
        m = x.mean(axis=0, keepdims=True)
        s = x.std(axis=0, keepdims=True) + 1e-6
        return (x - m) / s

    D = cdist(z(a), z(b), metric="euclidean")
    acc, wp = librosa.sequence.dtw(C=D, subseq=False)
    wp = wp[::-1]
    path_a, path_b = wp[:, 0], wp[:, 1]
    cost = float(acc[-1, -1] / max(len(path_a), 1))
    return path_a, path_b, cost


def score_pitch(f0_ref: np.ndarray, f0_user: np.ndarray) -> tuple[float, dict]:
    ref_c = _hz_to_cents(_nan_interp(f0_ref))
    usr_c = _hz_to_cents(_nan_interp(f0_user))
    voiced_ratio_ref = float(np.isfinite(f0_ref).mean())
    voiced_ratio_usr = float(np.isfinite(f0_user).mean())
    if voiced_ratio_ref < 0.05 or voiced_ratio_usr < 0.05:
        return 0.0, {
            "mae_cents": None,
            "key_shift_cents": None,
            "voiced_ratio_ref": voiced_ratio_ref,
            "voiced_ratio_user": voiced_ratio_usr,
            "note": "有效音高帧过少，无法评分（可能是噪音/气声）",
        }

    pa, pb, _ = dtw_align(ref_c, usr_c)
    ref_al = ref_c[pa]
    usr_al = usr_c[pb]
    shift = float(np.median(usr_al - ref_al))
    err = np.abs(usr_al - ref_al - shift)
    mae = float(np.mean(err))
    score = float(np.clip(100.0 * np.exp(-mae / 80.0), 0, 100))
    return score, {
        "mae_cents": round(mae, 1),
        "key_shift_cents": round(shift, 1),
        "voiced_ratio_ref": round(voiced_ratio_ref, 3),
        "voiced_ratio_user": round(voiced_ratio_usr, 3),
        "path_ref": pa,
        "path_user": pb,
        "ref_cents_aligned": ref_al,
        "user_cents_aligned": usr_al - shift,
    }


def score_rhythm(
    y_ref: np.ndarray,
    y_usr: np.ndarray,
    sr: int,
    onsets_ref: np.ndarray,
    onsets_usr: np.ndarray,
) -> tuple[float, dict]:
    dur_ref = len(y_ref) / sr
    dur_usr = len(y_usr) / sr
    dur_ratio = min(dur_ref, dur_usr) / max(dur_ref, dur_usr, 1e-6)

    n_r, n_u = len(onsets_ref), len(onsets_usr)
    count_sim = min(n_r, n_u) / max(n_r, n_u, 1)

    onset_mae = None
    if n_r >= 2 and n_u >= 2:
        r = onsets_ref / max(onsets_ref[-1], 1e-6)
        u = onsets_usr / max(onsets_usr[-1], 1e-6)
        pa, pb, _ = dtw_align(r, u)
        onset_mae = float(np.mean(np.abs(r[pa] - u[pb])))
        onset_score = float(np.clip(100.0 * np.exp(-onset_mae / 0.08), 0, 100))
    else:
        onset_score = 50.0 * count_sim

    rms_r = extract_rms(y_ref, sr)
    rms_u = extract_rms(y_usr, sr)
    pa, pb, _ = dtw_align(rms_r, rms_u)
    expected_b = pa * (len(rms_u) - 1) / max(len(rms_r) - 1, 1)
    warp = float(np.mean(np.abs(pb - expected_b)) / max(len(rms_u), 1))
    warp_score = float(np.clip(100.0 * np.exp(-warp / 0.15), 0, 100))

    # duration mismatch should hurt more for "wrong timing" demos
    dur_score = float(100.0 * (dur_ratio ** 1.5))

    score = float(
        np.clip(
            0.30 * onset_score
            + 0.30 * warp_score
            + 0.30 * dur_score
            + 0.10 * (100 * count_sim),
            0,
            100,
        )
    )
    return score, {
        "duration_ref_s": round(dur_ref, 3),
        "duration_user_s": round(dur_usr, 3),
        "duration_ratio": round(dur_ratio, 3),
        "onset_count_ref": n_r,
        "onset_count_user": n_u,
        "onset_mae_norm": None if onset_mae is None else round(onset_mae, 4),
        "warp": round(warp, 4),
        "onset_score": round(onset_score, 1),
        "warp_score": round(warp_score, 1),
        "dur_score": round(dur_score, 1),
    }


def score_content(y_ref: np.ndarray, y_usr: np.ndarray, sr: int) -> tuple[float, dict, bool]:
    """MFCC+delta cosine after DTW — PROXY, not ASR."""
    mf_r = extract_mfcc(y_ref, sr)
    mf_u = extract_mfcc(y_usr, sr)
    pa, pb, cost = dtw_align(mf_r, mf_u)
    a = mf_r[:, pa].T
    b = mf_u[:, pb].T
    a_n = a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)
    b_n = b / (np.linalg.norm(b, axis=1, keepdims=True) + 1e-9)
    cos = float(np.mean(np.sum(a_n * b_n, axis=1)))
    # stricter mapping so unrelated clips don't sit at 100
    score = float(np.clip((cos - 0.35) / 0.55 * 100.0, 0, 100))
    return score, {"mfcc_cosine": round(cos, 4), "dtw_cost": round(cost, 4)}, True


def score_loudness(y_ref: np.ndarray, y_usr: np.ndarray, sr: int) -> tuple[float, dict]:
    r = extract_rms(y_ref, sr)
    u = extract_rms(y_usr, sr)
    pa, pb, _ = dtw_align(r, u)
    ra, ua = r[pa], u[pb]
    if ra.std() < 1e-8 or ua.std() < 1e-8:
        corr = 0.0
    else:
        corr = float(np.corrcoef(ra, ua)[0, 1])
    mae = float(np.mean(np.abs(ra - ua)) / (np.mean(ra) + 1e-9))
    score = float(np.clip(50 * (corr + 1) * 0.5 + 50 * np.exp(-mae / 0.5), 0, 100))
    return score, {"rms_corr": round(corr, 4), "rms_rel_mae": round(mae, 4)}


def score_pair(ref_path: str, user_path: str) -> tuple[ScoreResult, dict]:
    y_r, sr = load_audio(ref_path)
    y_u, _ = load_audio(user_path)

    f0_r, t_r = extract_f0(y_r, sr)
    f0_u, t_u = extract_f0(y_u, sr)
    on_r = extract_onsets(y_r, sr)
    on_u = extract_onsets(y_u, sr)

    pitch, pitch_d = score_pitch(f0_r, f0_u)
    rhythm, rhythm_d = score_rhythm(y_r, y_u, sr, on_r, on_u)
    content, content_d, is_proxy = score_content(y_r, y_u, sr)
    loudness, loud_d = score_loudness(y_r, y_u, sr)

    overall = float(
        np.clip(0.35 * pitch + 0.30 * rhythm + 0.25 * content + 0.10 * loudness, 0, 100)
    )

    result = ScoreResult(
        overall=round(overall, 1),
        pitch=round(pitch, 1),
        rhythm=round(rhythm, 1),
        content=round(content, 1),
        loudness=round(loudness, 1),
        content_is_proxy=is_proxy,
        details={
            "pitch": {
                k: v
                for k, v in pitch_d.items()
                if k
                not in (
                    "path_ref",
                    "path_user",
                    "ref_cents_aligned",
                    "user_cents_aligned",
                )
            },
            "rhythm": rhythm_d,
            "content": content_d,
            "loudness": loud_d,
            "weights": {
                "pitch": 0.35,
                "rhythm": 0.30,
                "content": 0.25,
                "loudness": 0.10,
            },
        },
    )

    plots = {
        "y_ref": y_r,
        "y_user": y_u,
        "sr": sr,
        "f0_ref": f0_r,
        "f0_user": f0_u,
        "t_ref": t_r,
        "t_user": t_u,
        "onsets_ref": on_r,
        "onsets_user": on_u,
        "pitch_align": {
            "ref": pitch_d.get("ref_cents_aligned"),
            "user": pitch_d.get("user_cents_aligned"),
        },
    }
    return result, plots


# =====================================================================
# v3: two game modes, NO speech recognition. Pure acoustic scoring.
# =====================================================================
import os
import subprocess
import tempfile

from scipy.signal import find_peaks

PAUSE_MIN_S = 0.25
# --- calibrated thresholds (see README「阈值标定」) ---
# per mode: (distance -> similarity 100, distance -> similarity 0, anti-cheat max distance)
# 哼唱/玩梗的音高变化让频谱距离天然更大，所以阈值更宽
SIM_CFG = {"speech": (0.20, 0.45, 0.35), "hum": (0.30, 0.65, 0.60)}
SIM_D_GOOD, SIM_D_BAD, CHEAT_D_MAX = SIM_CFG["speech"]
FAIL_CAP = 59.0       # overall shown when a mode gate fails
SYL_RATIO = (0.5, 2.0)
MIN_VOICED_S = 0.3
SILENCE_RMS = 0.003   # raw (pre-normalization) RMS
FOREIGN_SIM_GATE = 45.0
MEME_RHYTHM_GATE = 55.0


def to_wav(path: str) -> str:
    fd, out = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-ac", "1",
                    "-ar", str(SR), out], check=True)
    return out


def load_raw(path: str) -> tuple[np.ndarray, float]:
    """Decode via ffmpeg; return (trimmed, peak-normalized y, raw RMS before normalization)."""
    wav = to_wav(path)
    try:
        y, _ = librosa.load(wav, sr=SR, mono=True)
    finally:
        os.unlink(wav)
    raw_rms = float(np.sqrt(np.mean(y ** 2))) if len(y) else 0.0
    if len(y) and np.max(np.abs(y)) > 0:
        y, _ = librosa.effects.trim(y, top_db=30)
        y = y / (np.max(np.abs(y)) + 1e-9) * 0.9
    return y, raw_rms


def voiced_seconds(y: np.ndarray, sr: int = SR) -> float:
    iv = librosa.effects.split(y, top_db=35, hop_length=HOP)
    return float(sum(b - a for a, b in iv) / sr)


def syllable_count(y: np.ndarray, sr: int = SR) -> int:
    e = librosa.feature.rms(y=y, hop_length=HOP)[0]
    w = np.hanning(9); e = np.convolve(e, w / w.sum(), "same")
    if e.max() <= 0:
        return 0
    p, _ = find_peaks(e, height=0.15 * e.max(), prominence=0.08 * e.max(), distance=8)
    return int(len(p))


def spectral_feat(y: np.ndarray, sr: int = SR) -> np.ndarray:
    """24-band log-mel, per-utterance CMVN (speaker / channel normalization)."""
    m = np.log(librosa.feature.melspectrogram(y=y, sr=sr, n_mels=24, hop_length=HOP, fmax=8000) + 1e-6)
    return (m - m.mean(1, keepdims=True)) / (m.std(1, keepdims=True) + 1e-6)


def spectral_compare(y_r, y_u, sr=SR, band=0.3):
    """
    Band-constrained DTW on CMVN log-mel with cosine distance.
    User is first linearly time-normalized to ref length (tempo is scored separately by 语速/节奏),
    then DTW may warp within ±30% of the utterance.
    Returns mean path distance and per-ref-frame local distance.
    """
    A, B = spectral_feat(y_r, sr), spectral_feat(y_u, sr)
    n = A.shape[1]
    idx = np.linspace(0, B.shape[1] - 1, n).astype(int)
    D = cdist(A.T, B[:, idx].T, "cosine")
    i, j = np.indices(D.shape)
    D = np.where(np.abs(i - j) <= max(3, int(band * n)), D, 1e6)
    _, wp = librosa.sequence.dtw(C=D)
    wp = wp[::-1]
    local = D[wp[:, 0], wp[:, 1]]
    per_ref = np.zeros(n); cnt = np.zeros(n)
    np.add.at(per_ref, wp[:, 0], local); np.add.at(cnt, wp[:, 0], 1)
    per_ref /= np.maximum(cnt, 1)
    # same path drives the UI time map, so overlay and difference strip agree
    tr, tu = wp[:, 0] * HOP / sr, idx[wp[:, 1]] * HOP / sr
    k = max(1, len(tr) // 120)
    pairs = [[round(float(u), 3), round(float(r), 3)] for r, u in zip(tr[::k], tu[::k])]
    pairs.append([round(float(tu[-1]), 3), round(float(tr[-1]), 3)])
    return float(local.mean()), per_ref, pairs


def dist_to_sim(d, mode="foreign"):
    g, b, _ = SIM_CFG.get(mode, SIM_CFG["speech"])
    return np.clip((b - np.asarray(d, float)) / (b - g) * 100, 0, 100)


def pace_score(ratio: float) -> float:
    if 0.85 <= ratio <= 1.15:
        return 100.0
    d = 0.85 - ratio if ratio < 0.85 else ratio - 1.15
    return round(float(np.clip(100 - 200 * d, 0, 100)), 1)


def find_pauses(y: np.ndarray, sr: int) -> list[list[float]]:
    iv = librosa.effects.split(y, top_db=30, hop_length=HOP)
    out = []
    for a, b in zip(iv[:-1], iv[1:]):
        g0, g1 = a[1] / sr, b[0] / sr
        if g1 - g0 >= PAUSE_MIN_S:
            out.append([round(g0, 3), round(g1, 3)])
    return out


def fluency_score(p_user: list, p_ref: list) -> float:
    excess_n = max(0, len(p_user) - len(p_ref))
    excess_s = max(0.0, sum(b - a for a, b in p_user) - sum(b - a for a, b in p_ref))
    return float(np.clip(100 - 15 * excess_n - 40 * excess_s, 0, 100))


def anti_cheat(y_r, y_u, raw_rms_u, dist, sr=SR, mode="foreign") -> dict:
    cheat_max = SIM_CFG.get(mode, SIM_CFG["speech"])[2]
    checks = []
    vs = voiced_seconds(y_u, sr) if len(y_u) else 0.0
    silent = raw_rms_u < SILENCE_RMS or vs < MIN_VOICED_S
    checks.append({"id": "voice", "name": "有声音", "pass": not silent,
                   "value": round(vs, 2), "tip": "几乎没录到声音或太短，靠近麦克风再试一次"})
    sr_, su = syllable_count(y_r, sr), syllable_count(y_u, sr) if not silent else 0
    ratio = su / max(sr_, 1)
    checks.append({"id": "syllables", "name": "音节数接近", "pass": (not silent) and SYL_RATIO[0] <= ratio <= SYL_RATIO[1],
                   "value": f"{su}/{sr_}", "tip": f"音节数差太多（你 {su} 个，示范 {sr_} 个），请完整模仿同一句"})
    checks.append({"id": "spectral", "name": "是同一句话", "pass": (not silent) and dist <= cheat_max,
                   "value": round(dist, 3), "tip": "听起来不像同一句内容，请跟着示范说"})
    return {"pass": all(c["pass"] for c in checks), "checks": checks}


# ---------- chart series ----------
def _env(y, sr, n=400):
    k = max(1, len(y) // n)
    m = len(y) // k * k
    blk = y[:m].reshape(-1, k)
    return {"dur": round(len(y) / sr, 3), "max": np.round(blk.max(1).astype(float), 3).tolist(),
            "min": np.round(blk.min(1).astype(float), 3).tolist()}


def _ds(t, v, n=300):
    k = max(1, len(t) // n)
    return [[round(float(a), 3), None if not np.isfinite(b) else round(float(b), 1)]
            for a, b in zip(t[::k], v[::k])]


def _time_map(y_r, y_u, sr):
    fr = librosa.feature.mfcc(y=y_r, sr=sr, hop_length=HOP, n_mfcc=13)
    fu = librosa.feature.mfcc(y=y_u, sr=sr, hop_length=HOP, n_mfcc=13)
    pa, pb, _ = dtw_align(fr, fu)
    tr, tu = pa * HOP / sr, pb * HOP / sr
    k = max(1, len(tr) // 120)
    pairs = [[round(float(u), 3), round(float(r), 3)] for r, u in zip(tr[::k], tu[::k])]
    pairs.append([round(float(tu[-1]), 3), round(float(tr[-1]), 3)])
    return pairs


def _map(pairs, tu):
    u = np.array([p[0] for p in pairs]); r = np.array([p[1] for p in pairs])
    u, idx = np.unique(u, return_index=True)
    return np.interp(tu, u, r[idx])


def ref_series(path: str) -> dict:
    y, _ = load_raw(path)
    f0, t = extract_f0(y, SR)
    return {"wave": _env(y, SR), "f0": _ds(t, f0)}


def _sim_strip(per_ref, sr, mode, n_seg=60):
    """Per-segment similarity along the reference timeline (heatmap strip)."""
    n = len(per_ref)
    edges = np.linspace(0, n, min(n_seg, n) + 1).astype(int)
    seg = [float(dist_to_sim(per_ref[a:b].mean(), mode)) for a, b in zip(edges[:-1], edges[1:]) if b > a]
    return {"seg_dur": round(n * HOP / sr / len(seg), 4), "sim": [round(s) for s in seg]}


def _worst_window(per_ref, sr, mode, win_s=0.3):
    w = max(1, int(win_s * sr / HOP))
    if len(per_ref) <= w:
        return 0.0, float(dist_to_sim(per_ref.mean(), mode))
    c = np.convolve(per_ref, np.ones(w) / w, "valid")
    i = int(np.argmax(c))
    return (i + w / 2) * HOP / sr, float(dist_to_sim(c[i], mode))


def _mel_pair(y_r, y_u, sr, n_t=120):
    """Log-mel (24 bands) of ref and user, user mapped onto ref timeline, quantized 0..99."""
    def lm(y):
        m = np.log(librosa.feature.melspectrogram(y=y, sr=sr, n_mels=24, hop_length=HOP, fmax=8000) + 1e-6)
        return m
    R, U = lm(y_r), lm(y_u)
    tr = np.linspace(0, R.shape[1] - 1, n_t).astype(int)
    # map ref frame -> user frame using linear tempo normalization (same as spectral_compare)
    tu = np.linspace(0, U.shape[1] - 1, n_t).astype(int)
    def q(M):
        lo, hi = np.percentile(M, 5), np.percentile(M, 99)
        return np.clip((M - lo) / (hi - lo + 1e-9) * 99, 0, 99).astype(int)
    return {"ref": q(R[:, tr]).T.tolist(), "user": q(U[:, tu]).T.tolist()}


# ---------- main entry ----------
def score_attempt(ref_path: str, user_path: str, mode: str, profile: str | None = None, **_ignored) -> dict:
    """profile: 'speech' (default) or 'hum' — selects calibrated similarity/anti-cheat thresholds."""
    prof = profile if profile in SIM_CFG else "speech"
    y_r, _ = load_raw(ref_path)
    y_u, raw_rms_u = load_raw(user_path)
    sr = SR
    if len(y_u) < sr * 0.15:  # can't analyse at all
        y_u = np.zeros(int(sr * 0.2), dtype=np.float32) + 1e-6
    dist, per_ref, pairs = spectral_compare(y_r, y_u, sr)
    sim = float(dist_to_sim(dist, prof))
    ac = anti_cheat(y_r, y_u, raw_rms_u, dist, sr, prof)
    dur_r, dur_u = len(y_r) / sr, len(y_u) / sr
    loud, _ = score_loudness(y_r, y_u, sr)
    f0_r, t_r = extract_f0(y_r, sr)
    f0_u, t_u = extract_f0(y_u, sr)
    on_r, on_u = extract_onsets(y_r, sr), extract_onsets(y_u, sr)
    p_u, p_r = find_pauses(y_u, sr), find_pauses(y_r, sr)
    tips, gates, extra = [], [{"name": "防作弊校验", "pass": ac["pass"]}], {}
    worst_t, worst_sim = _worst_window(per_ref, sr, prof)

    if mode == "foreign":
        ratio = dur_r / max(dur_u, 1e-6)
        pace, flu = pace_score(ratio), fluency_score(p_u, p_r)
        dims = {
            "similarity": {"name": "发音相似度", "score": sim, "weight": 0.45},
            "pace": {"name": "语速", "score": pace, "weight": 0.25},
            "fluency": {"name": "流畅度", "score": flu, "weight": 0.20},
            "loudness": {"name": "响度", "score": loud, "weight": 0.10},
        }
        gates.append({"name": f"发音相似度 ≥ {FOREIGN_SIM_GATE:.0f}", "pass": sim >= FOREIGN_SIM_GATE})
        if sim >= 80:
            tips.append("发音和示范很接近 👍")
        elif worst_sim < 60:
            tips.append(f"第 {worst_t:.1f} 秒附近发音偏差较大，对照示范多听几遍")
        else:
            tips.append("整体发音还可以，注意元音口型更饱满")
        if ratio < 0.85:
            tips.append(f"语速偏慢约 {1/ratio:.1f} 倍，试着读得更连贯")
        elif ratio > 1.15:
            tips.append(f"语速偏快约 {ratio:.1f} 倍，放慢一点")
        else:
            tips.append("语速和示范接近")
        ex = len(p_u) - len(p_r)
        tips.append(f"中间多停顿 {ex} 处，尽量一口气读完" if ex > 0 else "没有多余停顿")
        extra.update({"ratio": round(ratio, 3), "pauses_ref": p_r})
    else:
        rhythm, rh_d = score_rhythm(y_r, y_u, sr, on_r, on_u)
        pitch, pd = score_pitch(f0_r, f0_u)
        dims = {
            "rhythm": {"name": "节奏型", "score": rhythm, "weight": 0.40},
            "contour": {"name": "腔调", "score": pitch, "weight": 0.35},
            "similarity": {"name": "声音相似度", "score": sim, "weight": 0.15},
            "loudness": {"name": "响度", "score": loud, "weight": 0.10},
        }
        gates.append({"name": f"节奏 ≥ {MEME_RHYTHM_GATE:.0f}", "pass": rhythm >= MEME_RHYTHM_GATE})
        r = rh_d["duration_ratio"]
        if r < 0.85:
            tips.append(f"整体时长差约 {1/r:.1f} 倍，" + ("拖长了" if dur_u > dur_r else "太赶了"))
        else:
            tips.append("整体节奏和示范接近" if rhythm >= 70 else "停顿位置和重音拍点再对齐一些")
        mae = pd.get("mae_cents")
        if mae is None:
            tips.append("没检测到清晰的音高，声音再亮一点")
        elif mae > 200:
            tips.append(f"腔调起伏差别较大（平均偏差 {mae/100:.1f} 个半音），注意哪里升哪里降")
        elif mae > 80:
            tips.append("腔调大体对，个别地方升降不到位")
        else:
            tips.append("腔调起伏很像 👍")
        if worst_sim < 50:
            tips.append(f"第 {worst_t:.1f} 秒附近听起来不太像")
        extra.update({"key_shift_cents": pd.get("key_shift_cents"), "mae_cents": mae})

    if loud < 60:
        tips.append("轻重起伏和示范差别较大，注意重音")
    failed = [c for c in ac["checks"] if not c["pass"]]
    if failed:
        tips.insert(0, "⚠️ " + failed[0]["tip"])
    overall = sum(d["score"] * d["weight"] for d in dims.values())
    if not ac["pass"]:
        overall = min(overall, 20.0)  # rejected attempts can't earn a real score
    elif not all(g["pass"] for g in gates):
        overall = min(overall, FAIL_CAP)
    for d in dims.values():
        d["score"] = round(float(d["score"]), 1)

    def cents(f):
        return np.where(np.isfinite(f), 1200 * np.log2(np.maximum(np.nan_to_num(f, nan=1), 1e-6) / 440), np.nan)
    cr, cu = cents(f0_r), cents(f0_u)
    shift = extra.get("key_shift_cents")
    if shift is None:
        shift = float(np.nanmedian(cu) - np.nanmedian(cr)) if np.isfinite(cu).any() and np.isfinite(cr).any() else 0.0
    tu_on_r = _map(pairs, t_u)
    mapped = _map(pairs, on_u) if len(on_u) else np.array([])
    links = []
    for o in on_r:
        if not len(mapped):
            break
        j = int(np.argmin(np.abs(mapped - o)))
        links.append({"r": round(float(o), 3), "u": round(float(on_u[j]), 3), "dt": round(float(mapped[j] - o), 3)})

    extra.update({"spectral_distance": round(dist, 4), "worst_t": round(worst_t, 2),
                  "worst_sim": round(worst_sim, 1), "pauses_user": p_u})
    return {
        "mode": mode,
        "profile": prof,
        "overall": round(float(overall), 1),
        "passed": all(g["pass"] for g in gates),
        "anti_cheat": ac,
        "gates": gates,
        "dims": dims,
        "tips": tips,
        "detail": extra,
        "series": {
            "ref_wave": _env(y_r, sr), "user_wave": _env(y_u, sr),
            "time_map": pairs,
            "ref_cents": _ds(t_r, cr),
            "user_cents_aligned": _ds(tu_on_r, cu - shift),
            "onsets_ref": np.round(on_r, 3).tolist(),
            "onsets_user": np.round(on_u, 3).tolist(),
            "onset_links": links,
            "pauses_user": p_u,
            "sim_strip": _sim_strip(per_ref, sr, prof),
            "mel": _mel_pair(y_r, y_u, sr),
        },
    }
