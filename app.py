#!/usr/bin/env python3
"""Gradio demo: audio mimic scoring for game evaluation."""

from __future__ import annotations

import json
import traceback
from pathlib import Path

import gradio as gr

from plotting import fig_f0, fig_pitch_aligned, fig_scores_bar, fig_waveforms
from score import score_pair

ROOT = Path(__file__).resolve().parent
SAMPLES = ROOT / "samples"
MANIFEST = SAMPLES / "manifest.json"

EXPLAIN_MD = """
## 评分说明（Demo）

| 维度 | 算法 | 说明 |
|------|------|------|
| **音准 pitch** | `librosa.pyin` 提取 F0 → DTW 对齐 → 以 **cents** 计平均误差；先减去全局移调（key shift） | 同一旋律换调仍可能拿高分；真正「调性感」需另加绝对音高项 |
| **节奏 rhythm** | Onset 时间归一化对齐 + 能量包络 DTW 路径弯曲度 + 时长比 | 整体变慢/变快、拍点不齐会拉低 |
| **内容 content*** | MFCC+Δ 经 DTW 后余弦相似度（**代理指标**） | **不是 ASR**。歌词/台词对错请上线 Whisper 等；此处衡量「音色+频谱轮廓是否像」 |
| **响度 loudness** | RMS 包络相关 + 相对 MAE（加载时已峰值归一） | 比的是起伏形状，不是绝对音量 |
| **总分** | `0.35*音准 + 0.30*节奏 + 0.25*内容 + 0.10*响度` | 可按玩法改权重 |

### 已知局限
- 合成音/哼唱效果好；嘈杂环境、气声、说唱（弱音高）音准会失真。
- 内容分为代理，**不能**判断「歌词对不对」。
- 未做真人说话人归一、未做伴奏分离。
- CPU 上 pyin 对较长音频可能接近数秒级。
"""


def _load_manifest() -> list[dict]:
    if not MANIFEST.exists():
        return []
    with open(MANIFEST, encoding="utf-8") as f:
        return json.load(f)


def sample_choices() -> list[str]:
    items = _load_manifest()
    return [f"{m['id']}. {m['name']}（期望总分 {m['expected_overall']}）" for m in items]


def resolve_sample(label: str) -> tuple[str | None, str | None, str]:
    if not label:
        return None, None, ""
    mid = label.split(".", 1)[0].strip()
    for m in _load_manifest():
        if m["id"] == mid:
            note = f"**{m['name']}**\n\n期望总分：`{m['expected_overall']}`\n\n{m['note']}"
            return str(SAMPLES / m["ref"]), str(SAMPLES / m["user"]), note
    return None, None, ""


def run_score(ref_audio, user_audio):
    if ref_audio is None or user_audio is None:
        raise gr.Error("请先提供参考音频和用户音频（可上传或选示例）")
    ref_path = ref_audio if isinstance(ref_audio, str) else ref_audio
    user_path = user_audio if isinstance(user_audio, str) else user_audio
    try:
        result, plots = score_pair(ref_path, user_path)
    except Exception as e:
        traceback.print_exc()
        raise gr.Error(f"评分失败：{e}") from e

    proxy_tag = "（代理 MFCC，非 ASR）" if result.content_is_proxy else ""
    summary = (
        f"### 总分 **{result.overall:.1f}** / 100\n\n"
        f"- 音准：**{result.pitch:.1f}**\n"
        f"- 节奏：**{result.rhythm:.1f}**\n"
        f"- 内容{proxy_tag}：**{result.content:.1f}**\n"
        f"- 响度：**{result.loudness:.1f}**\n\n"
        f"<details><summary>技术细节 JSON</summary>\n\n```json\n"
        f"{json.dumps(result.details, ensure_ascii=False, indent=2)}\n```\n</details>"
    )

    fig_bar = fig_scores_bar(
        result.overall, result.pitch, result.rhythm, result.content, result.loudness
    )
    fig_wave = fig_waveforms(plots["y_ref"], plots["y_user"], plots["sr"])
    fig_pitch = fig_f0(
        plots["t_ref"],
        plots["f0_ref"],
        plots["t_user"],
        plots["f0_user"],
        plots["onsets_ref"],
        plots["onsets_user"],
    )
    fig_al = fig_pitch_aligned(
        plots["pitch_align"]["ref"], plots["pitch_align"]["user"]
    )
    return summary, fig_bar, fig_wave, fig_pitch, fig_al


def build_app() -> gr.Blocks:
    with gr.Blocks(title="音频模仿打分 Demo") as demo:
        gr.Markdown(
            "# 音频模仿打分 Demo\n"
            "上传**示范音**与**模仿音**，或选择内置合成样例，评估音准 / 节奏 / 内容(代理) / 响度。"
        )
        with gr.Row():
            with gr.Column():
                sample = gr.Dropdown(
                    choices=sample_choices(),
                    label="内置样例（可选）",
                    value=None,
                )
                sample_info = gr.Markdown("")
                ref = gr.Audio(type="filepath", label="参考 / 示范音频", sources=["upload"])
                user = gr.Audio(type="filepath", label="用户模仿音频", sources=["upload"])
                btn = gr.Button("开始打分", variant="primary")
            with gr.Column():
                out_md = gr.Markdown("等待打分…")
                out_bar = gr.Plot(label="分项柱状图")

        with gr.Row():
            out_wave = gr.Plot(label="波形")
            out_f0 = gr.Plot(label="F0 / Onset")
        out_al = gr.Plot(label="DTW 对齐音高")

        gr.Markdown(EXPLAIN_MD)

        def on_sample(label):
            r, u, note = resolve_sample(label)
            return r, u, note

        sample.change(on_sample, inputs=[sample], outputs=[ref, user, sample_info])
        btn.click(run_score, inputs=[ref, user], outputs=[out_md, out_bar, out_wave, out_f0, out_al])

    return demo


if __name__ == "__main__":
    if not MANIFEST.exists():
        from generate_samples import main as gen

        print("Generating sample clips…")
        gen()
    app = build_app()
    app.launch(server_name="127.0.0.1", server_port=7860, share=False)
