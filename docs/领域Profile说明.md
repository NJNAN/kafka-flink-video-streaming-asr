# 领域 Profile 说明

领域 Profile 用于给不同类型的视频配置不同热词和纠错词表，提升领域词识别效果。

## 1. 已内置 Profile

```text
config/profiles/bigdata_keywords.txt
config/profiles/bigdata_corrections.txt
config/profiles/course_keywords.txt
config/profiles/course_corrections.txt
config/profiles/meeting_keywords.txt
config/profiles/meeting_corrections.txt
config/profiles/dino_keywords.txt
config/profiles/dino_corrections.txt
```

## 2. 命令行使用

```powershell
python tools/generate_video_subtitles.py `
  --media-path videos/input.mp4 `
  --profile bigdata `
  --use-static-hints `
  --output-dir data/results/profile_test `
  --basename input
```

生成的 report 会记录：

```json
{
  "profile": "bigdata",
  "profile_keyword_file": "config/profiles/bigdata_keywords.txt",
  "profile_correction_file": "config/profiles/bigdata_corrections.txt"
}
```

## 3. 桌面端使用

离线字幕桌面端现在有“领域 Profile”选择：

- 大数据课设
- 课程视频
- 会议录音
- 恐龙专题
- 通用

选择后，Electron 会把 `--profile` 参数传给 `tools/generate_video_subtitles.py`。

## 4. 新增 Profile

新增两个文件即可：

```text
config/profiles/mytopic_keywords.txt
config/profiles/mytopic_corrections.txt
```

纠错格式：

```text
错误词=>正确词
```

运行：

```powershell
python tools/generate_video_subtitles.py --media-path videos/input.mp4 --profile mytopic --use-static-hints
```

## 5. 答辩说法

```text
同一个 ASR 模型面对不同课程内容会有不同领域词。
我把热词和纠错表抽象成领域 Profile，
这样系统可以切换到大数据课设、课程视频、会议录音等场景。
```
