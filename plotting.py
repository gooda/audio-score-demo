"""Matplotlib figures for Gradio display."""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

# Prefer Noto CJK so Chinese titles render
for fp in (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
):
    try:
        font_manager.fontManager.addfont(fp)
        prop = font_manager.FontProperties(fname=fp)
        plt.rcParams["font.family"] = prop.get_name()
        plt.rcParams["axes.unicode_minus"] = False
        break
    except Exception:
        continue


def fig_waveforms(y_ref: np.ndarray, y_user: np.ndarray, sr: int):
    fig, axes = plt.subplots(2, 1, figsize=(9, 4), sharex=False)
    t_r = np.arange(len(y_ref)) / sr
    t_u = np.arange(len(y_user)) / sr
    axes[0].plot(t_r, y_ref, color="#2563eb", lw=0.8)
    axes[0].set_title("参考音频波形 (Reference)")
    axes[0].set_ylabel("Amplitude")
    axes[1].plot(t_u, y_user, color="#dc2626", lw=0.8)
    axes[1].set_title("用户音频波形 (User)")
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Amplitude")
    fig.tight_layout()
    return fig


def fig_f0(t_ref, f0_ref, t_user, f0_user, onsets_ref=None, onsets_user=None):
    fig, axes = plt.subplots(2, 1, figsize=(9, 4.5), sharex=False)
    axes[0].plot(t_ref, f0_ref, color="#2563eb", lw=1.2, label="F0")
    if onsets_ref is not None and len(onsets_ref):
        for o in onsets_ref:
            axes[0].axvline(o, color="#93c5fd", alpha=0.5, lw=0.8)
    axes[0].set_title("参考音高 F0 + onset（浅蓝竖线）")
    axes[0].set_ylabel("Hz")
    axes[0].legend(loc="upper right")

    axes[1].plot(t_user, f0_user, color="#dc2626", lw=1.2, label="F0")
    if onsets_user is not None and len(onsets_user):
        for o in onsets_user:
            axes[1].axvline(o, color="#fca5a5", alpha=0.5, lw=0.8)
    axes[1].set_title("用户音高 F0 + onset")
    axes[1].set_xlabel("Time (s)")
    axes[1].set_ylabel("Hz")
    axes[1].legend(loc="upper right")
    fig.tight_layout()
    return fig


def fig_pitch_aligned(ref_cents, user_cents):
    fig, ax = plt.subplots(figsize=(9, 3.2))
    if ref_cents is None or user_cents is None:
        ax.text(0.5, 0.5, "有效音高不足，无法绘制对齐曲线", ha="center", va="center")
        ax.set_axis_off()
        return fig
    x = np.arange(len(ref_cents))
    ax.plot(x, ref_cents, color="#2563eb", lw=1.2, label="参考（对齐后，cents）")
    ax.plot(x, user_cents, color="#dc2626", lw=1.2, alpha=0.85, label="用户（去全局移调后）")
    ax.set_title("DTW 对齐后的音高曲线（已减去全局 key shift）")
    ax.set_xlabel("Aligned frame")
    ax.set_ylabel("Cents (ref A4=440)")
    ax.legend(loc="upper right")
    fig.tight_layout()
    return fig


def fig_scores_bar(overall, pitch, rhythm, content, loudness):
    fig, ax = plt.subplots(figsize=(7, 3.2))
    labels = ["总分", "音准", "节奏", "内容*", "响度"]
    vals = [overall, pitch, rhythm, content, loudness]
    colors = ["#111827", "#2563eb", "#16a34a", "#ca8a04", "#7c3aed"]
    bars = ax.bar(labels, vals, color=colors)
    ax.set_ylim(0, 100)
    ax.set_ylabel("Score")
    ax.set_title("分项得分（内容* = MFCC 代理，非 ASR）")
    for b, v in zip(bars, vals):
        ax.text(b.get_x() + b.get_width() / 2, v + 1.5, f"{v:.0f}", ha="center", fontsize=9)
    fig.tight_layout()
    return fig
