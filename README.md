# 声音模仿挑战 · 打分 Demo（v2）

听示范 → 录音模仿 → 按「外语发音 / 玩梗模仿」两种规则打分，并把每个维度可视化，直接对比示范和你的录音。

## 运行

```bash
cd audio-score-demo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt   # 另需系统 ffmpeg
python server.py                 # 默认 http://0.0.0.0:8765 ，可用 PORT=xxxx 修改
# 或：uvicorn server:app --host 0.0.0.0 --port 8765
```

浏览器打开 `http://127.0.0.1:8765`。录音需要 **localhost 或 HTTPS**（浏览器限制）；手机访问内网 IP 时请用上传，或加 HTTPS 反代。
服务端常驻内存约 260MB（去掉 Whisper 前约 1GB）。`edge-tts` 只是生成新关卡示范音的开发工具，运行时不需要。

测试：
```bash
python tests_score.py      # 单元测试（无 ASR、语速、流畅度、自身=100、错内容/静音被拦截、权重）
python calibrate.py        # 阈值标定表
python e2e_test.py         # Playwright 无头浏览器：假麦克风录音 + 上传两段真实录音，并截图到 screenshots/
```

## 打分规则（v3：完全不用语音识别）

所有维度只比较声音本身，不做 ASR、不识别文字；关卡里的台词只作为玩家看的字幕。单次打分在 CPU 上约 **0.3–0.7 秒**。

### 外语发音（mode=foreign）
| 维度 | 权重 | 算法 |
|---|---|---|
| 发音相似度 | 45% | 24 维 log-mel，**每句单独做均值方差归一（CMVN，抵消嗓音/麦克风差异）**；把你的录音线性拉到示范时长后做 ±30% 带约束 DTW，余弦距离取路径均值 d，映射 `d≤0.20→100，d≥0.45→0` |
| 语速 | 25% | 时长比 = 示范 ÷ 你的；0.85–1.15 满分，超出每 0.1 扣 20 |
| 流畅度 | 20% | 句中 ≥0.25s 的停顿，比示范多一处扣 15，多 1 秒扣 40 |
| 响度 | 10% | RMS 包络对齐后的形状相似度 |

必过：防作弊通过 **且** 发音相似度 ≥ 45。不计音高。

### 玩梗模仿（mode=meme）
| 维度 | 权重 | 算法 |
|---|---|---|
| 节奏型 | 40% | 起音点对齐 + 能量包络弯曲度 + 时长比 |
| 腔调 | 35% | pyin 音高 → DTW → 扣除整体升降调后的平均音分偏差 |
| 声音相似度 | 15% | 同上频谱相似度 |
| 响度 | 10% | 同上 |

必过：防作弊通过 **且** 节奏 ≥ 55。

### 防作弊（两种模式都有，零成本）
1. **有声音**：原始 RMS ≥ 0.003 且有效发声 ≥ 0.3s；
2. **音节数接近**：能量包络峰值数之比在 0.5–2.0；
3. **是同一句话**：频谱距离 d ≤ 阈值（语音类 0.35，哼唱类 0.60）。

任一不通过 → 总分封顶 20，并在建议第一条给出原因。防作弊通过但模式必过项没过 → 总分封顶 59。

阈值按关卡的 `profile` 选择：`speech`（默认，说话/台词梗）或 `hum`（哼唱，音高变化让频谱距离天然更大）。

### 阈值标定（`python calibrate.py`，完整结果见 calibration.txt / calibration.json）
| 场景 | 频谱距离 d | 结果 |
|---|---|---|
| 6 个关卡的示范音自己对自己 | 0.000 | 全部 100 分通过 |
| 示范音对其他关卡示范音（错内容，30 组） | 语音类最低 0.357，多数 0.45–0.80 | **30/30 被防作弊拦截**，总分 ≤20 |
| 静音 / 白噪声（每关各 1） | 0.78–0.94 | 全部拦截（有声音 / 音节 / 频谱同时报错） |
| 真实西语录音 m4a | 0.237 | **72.9 通过**（相似度 85，语速 30：慢 2 倍） |
| 同一句西语、另一种机器合成音色 | 0.348 | 防作弊刚好通过，相似度 41 < 45 → 59 未通过 |
| 西语录音经 opus 编码（模拟浏览器录音） | 0.230 | 74.6 通过 |
| 真实哼唱 m4a（hum 档） | 0.538 | **36.5 通过**（节奏 63 / 腔调 0 / 相似度 32 / 响度 63；旧规则为 37） |
| 合成哼唱近似 / opus 版 | 0.463 / 0.475 | 84.9 / 83.0 通过 |
| 无头浏览器假麦克风：哼唱关 | — | 76 通过 |
| 无头浏览器假麦克风：西语关（循环播放真实西语） | — | 59.3 通过（录得比示范长，语速 10 分） |

注意：语音类「真录音 0.23–0.24」与「最像的错内容 0.357」之间余量不大，正式上线前要用真实玩家录音重新标定。

## 界面
- **主视图：示范 vs 我的**（默认波形叠加）：蓝=示范、红=我的，半透明叠加；我的录音按 DTW 路径映射到示范时间轴，并按 RMS 包络统一响度，形状可直接比。背景红色越深=该处频谱差异越大；底部灰条=你的停顿。
- **差异条**：主视图下方，按 DTW 局部频谱距离逐段着色（绿→黄→红）。**点击主视图或差异条任意位置**：自动选出这一段，先播示范、再播你的同一段。
- **频谱对比**（右上切换）：示范 log-mel / 我的（对齐后）/ 差异图三行，给高级用户看具体哪个频段不同。
- 防作弊徽章与三项检查明细；分项条（含权重）、雷达图、总分、耗时；中文建议（如「第 1.2 秒附近发音偏差较大」「语速偏慢约 2.0 倍」）。
- 外语：语速条。
- 次要面板（默认折叠）：腔调音高曲线、节奏起音点连线。
- 录音时：音量条 + 实时波形 + 实时音高叠在示范音高上；也可上传。
- 本关历史折线（localStorage）。

## 架构
```
浏览器 static/index.html + app.js（原生 Canvas，无 CDN 依赖）
   │  GET /api/levels  GET /api/levels/{id}/ref  GET /samples/*
   │  POST /api/score (multipart)
server.py (FastAPI) ──► score.py: ffmpeg 解码 → librosa（log-mel+CMVN / pyin / onset / RMS）
                                  + 带约束 DTW → 防作弊 / 分项 / 必过项 / 提示 + 降采样图表序列
```

## API
`GET /api/levels` → 关卡列表（含 `ref_url`）。
`GET /api/levels/{id}/ref` → 示范波形包络与 f0（实时叠加用）。
`POST /api/score`，multipart 字段：
- `audio`（必填，webm/m4a/mp3/wav）
- `level_id`；或不用关卡时：`ref`（文件）+ `mode`=`foreign|meme` + 可选 `profile`=`speech|hum`

返回约 40KB：`overall, passed, elapsed_ms, profile, anti_cheat{pass,checks[]}, gates[], dims{key:{name,score,weight}}, tips[], detail{spectral_distance,worst_t,ratio,pauses_user,key_shift_cents…}, series{ref_wave,user_wave,time_map[[user_t,ref_t]],sim_strip{seg_dur,sim[]},mel{ref,user},ref_cents,user_cents_aligned,onsets_*,onset_links,pauses_user}`。

## 添加关卡
1. 生成示范音：`edge-tts -v ja-JP-NanamiNeural -t "こんにちは" --write-media samples/ja_konnichiwa_ref.mp3`（`--rate=-30%` 可拉长做梗）。
2. 在 `levels.json` 增加：`{"id","title","mode":"foreign|meme","profile":"speech|hum","lang","ref","text","hint"}`（`text` 只做字幕显示）。
3. 跑一遍 `python calibrate.py`，确认新关卡自身 100、与其他关卡互相被拦截。
4. 刷新页面即可，无需改代码。

## Unity / 游戏服务端接入
客户端录音（建议 16k–48k 单声道 wav 或 opus）后直接 `POST /api/score`（带 `level_id`），用返回的 `overall/passed/anti_cheat/dims/tips` 做结算；`series` 用来画对比图，不需要可以忽略。本服务无状态、纯 CPU、单条 <1 秒，可水平扩容。

## 已知局限
- **不识别文字**：读错个别词但音色、节奏接近时，可能仍拿到不错的相似度；无法给出「第几个词读错」，只能指出「第几秒附近不像」。
- 频谱相似度受嗓音、性别、口音影响，CMVN 只能部分抵消；男声模仿女声示范会偏低。真录音与最像错内容之间余量不大（0.24 vs 0.36），需要用真实玩家数据重新标定。
- 防作弊能挡住静音、噪声、明显不同的句子；内容相近、音节数相近的句子有可能骗过。
- 哼唱的频谱相似度天然低（真实哼唱 32 分），所以只占 15%。
- 音高在气声、说唱、噪音中不稳定；实时音高仅作示意。
- 频谱对比视图的用户行是在前端按 DTW 时间映射重采样的，分辨率约 120 列。
- 历史只存浏览器本地。旧版 Gradio（`app.py`）保留作对照，不再维护。
