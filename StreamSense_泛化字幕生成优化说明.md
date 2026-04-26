# StreamSense 泛化字幕生成优化说明

## 1. 优化目标

这次优化的目标不是把某一个视频调好，而是让项目面对不同真实视频时，都能稳定、快速地生成可直接使用的字幕文件。

核心验收标准：

- 不依赖某个视频的静态热词和专用纠错表。
- 默认走本地模型，不调用线上付费 API。
- 10 分钟视频最慢 5 分钟内生成字幕。
- 生成 `.srt` / `.vtt` / `.txt`，可直接应用到视频。
- 自动检查有声区间，尽量避免“中间有几段说话但没有字幕”。
- 代码保持直观，脚本保留中文注释，适合本科生继续维护。

## 2. 关键改动

### 2.1 最终字幕改为全视频优先

实时 Kafka-Flink 链路仍然保留，用于展示流式架构、Dashboard 和关键词事件。

最终可交付字幕不再依赖流式切片 JSONL 拼接，而是使用：

```powershell
python tools/generate_video_subtitles.py
```

这条链路直接对完整真实视频做本地 ASR。这样可以最大限度保留上下文，避免固定切片导致的漏词、断句和时间轴缺口。

### 2.2 增加字幕覆盖率校验

ASR 服务新增 `/detect-speech` 接口，内部用 FFmpeg `silencedetect` 检测视频中的有声区间。

生成字幕后，脚本会比较：

- 视频中检测到的有声区间
- 已生成字幕的时间轴覆盖区间

如果发现“有声音但没有字幕覆盖”的区间，会记录到：

```text
*_report.json
```

### 2.3 增加缺口补转写

如果发现漏段，脚本不会重新跑整段视频，而是只裁剪漏掉的小时间段重新转写。

ASR 服务新增了 `clip_start_ms` 和 `clip_end_ms` 参数，流程是：

1. 用 FFmpeg 从原视频中裁剪漏段音频。
2. 用同一个本地 Whisper 模型转写这个小片段。
3. 把补出来的字幕按原视频时间轴合并回最终 SRT。

这样能保证字幕更全，同时不会破坏速度目标。

### 2.4 区分正文漏段和非正文噪声

有些视频片头片尾会有背景音乐、音效、水印或字幕组模板。它们会被音频能量检测认为“有声音”，但并不一定是需要字幕的正文语音。

脚本现在区分两类缺口：

```text
blocking_uncovered_gaps_after_recovery
ignored_uncovered_gaps_after_recovery
```

含义：

- `blocking_uncovered_gaps_after_recovery`：补漏后仍可能是正文语音漏字幕，需要复查。
- `ignored_uncovered_gaps_after_recovery`：补漏确认是空文本、水印、片头片尾模板或非正文音频，不阻塞验收。

最终批量验收只要求 blocking 缺口为 0。

### 2.5 支持根目录视频直接处理

ASR 容器现在把项目根目录只读挂载到：

```text
/workspace
```

所以根目录下的：

```text
input2.mp4
input3.mp4
...
```

都可以直接用脚本处理，不需要手动复制到 `videos/`。

### 2.6 批量验收脚本

新增：

```text
tools/batch_generate_subtitles.py
```

运行：

```powershell
python tools/batch_generate_subtitles.py
```

它会自动查找项目根目录和 `videos/` 目录下的视频，逐个生成字幕和报告。

输出：

```text
data/results/batch/<视频名>/<视频名>.srt
data/results/batch/<视频名>/<视频名>.vtt
data/results/batch/<视频名>/<视频名>_subtitle.txt
data/results/batch/<视频名>/<视频名>_report.json
data/results/batch/batch_report.md
data/results/batch/batch_report.json
```

## 3. 当前批量验收结果

本次已经对 10 个真实视频跑完整批量验收：

| 视频 | 状态 | 时长(s) | 耗时(s) | 耗时/视频 | 字幕条数 | 补漏前缺口 | 补漏后阻塞缺口 |
|---|---:|---:|---:|---:|---:|---:|---:|
| input.mp4 | ok | 751.2 | 163.5 | 0.218 | 90 | 1 | 0 |
| input10.mp4 | ok | 488.6 | 132.1 | 0.270 | 69 | 4 | 0 |
| input2.mp4 | ok | 636.3 | 168.8 | 0.265 | 98 | 1 | 0 |
| input3.mp4 | ok | 749.5 | 166.9 | 0.223 | 113 | 7 | 0 |
| input4.mp4 | ok | 623.7 | 135.8 | 0.218 | 82 | 1 | 0 |
| input5.mp4 | ok | 242.0 | 16.6 | 0.069 | 5 | 1 | 0 |
| input6.mp4 | ok | 343.1 | 60.7 | 0.177 | 39 | 0 | 0 |
| input7.mp4 | ok | 321.3 | 43.1 | 0.134 | 59 | 13 | 0 |
| input8.mp4 | ok | 266.3 | 8.8 | 0.033 | 0 | 1 | 0 |
| input9.mp4 | ok | 661.8 | 155.3 | 0.235 | 83 | 2 | 0 |

结论：

- 10 个视频全部通过。
- 所有视频耗时都小于视频时长的一半。
- 所有视频补漏后 blocking 缺口为 0。
- `input8.mp4` 没有可用正文字幕，原始 ASR 只出现 `Amara.org` 模板，脚本正确生成空字幕并通过验收。

完整机器生成报告见：

```text
data/results/batch/batch_report.md
data/results/batch/batch_report.json
```

## 4. 推荐使用方式

生成默认视频字幕：

```powershell
python tools/generate_video_subtitles.py
```

生成某个根目录视频字幕：

```powershell
python tools/generate_video_subtitles.py --media-path input2.mp4 --output-dir data/results/input2 --basename input2
```

批量生成并验收所有视频：

```powershell
python tools/batch_generate_subtitles.py
```

如果要更慢但更强调领域词，可以启用两遍模式：

```powershell
python tools/generate_video_subtitles.py --passes 2
```

## 5. 仍然保留的工程边界

当前方案已经解决“泛化处理多个视频”和“漏段自动补救”的工程问题，但它不是人工精校系统。

仍然可能存在：

- 个别词识别不如人工字幕准确。
- 方言、多人抢话、强背景音乐下准确率下降。
- 音效或音乐可能被有声检测捕捉，但会进入 ignored 缺口，不会被当成正文漏字幕。

这些属于本地 Whisper 模型能力边界，不是 Kafka/Flink 或字幕导出链路的问题。
