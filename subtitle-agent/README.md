# StreamSense Subtitle Agent

这是一个独立的离线视频字幕 Agent，不是 `desktop-ui/` 的新增按钮。

它会围绕一个本地视频完成：

1. 规划字幕生成任务。
2. 调用原项目 `tools/generate_video_subtitles.py` 生成基础字幕。
3. 用当前字幕、质量报告、领域词表、Agent 知识、历史字幕和项目文档建立 RAG 知识库。
4. 调用 OpenAI-compatible 大模型 API 建立全片上下文审校规则。
5. 调用大模型动态归纳本视频术语表。
6. 调用大模型逐段修正字幕错词，并保存每一处 AI revision。
7. 调用大模型做全局术语一致性检查。
8. 调用大模型做字幕语义排版优化。
9. 进行字幕可读性拆分、阅读节奏优化和完整性检查，避免导出字幕出现空白段。
10. 输出 clean / creator 多版本字幕任务包。

## 目录位置

推荐放在原项目根目录：

```text
基于 Kafka-Flink 的视频流语音转写与关键词分析系统/
└── subtitle-agent/
```

## 安装依赖

```powershell
cd subtitle-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 配置大模型

复制环境变量模板：

```powershell
Copy-Item .env.example .env
```

把 `.env` 改成你的真实配置：

```env
LLM_API_BASE=https://api.deepseek.com
LLM_API_KEY=your_api_key_here
LLM_MODEL=deepseek-v4-flash
```

不要把 `.env` 提交到 Git。

## 启动 Textual TUI

```powershell
python app.py
```

快捷键：

- `v`：输入/修改视频路径。
- `p`：修改领域 Profile。
- `g`：开始运行 Agent。
- `l`：清空日志。
- `q`：退出。

## 命令行模式

```powershell
python agent_main.py --video ..\input2.mp4 --profile bigdata --goal "生成高质量字幕并检查专业词"
```

## 输出文件

每次运行会生成：

```text
data/results/agent_tasks/<agent_task_id>/
├── original.srt
├── revised.srt
├── revised.ass
├── revised.clean.ass
├── revised.creator.ass
├── subtitle.txt
├── final_segments.json
├── source_report.json
├── agent_plan.json
├── rag_index.jsonl
├── rag_hits.json
├── ai_context_brief.json
├── ai_glossary.json
├── ai_segment_revisions.json
├── term_consistency_report.json
├── semantic_edit_report.json
├── rhythm_report.json
├── correction_integrity_report.json
├── subtitle_integrity_report.json
├── agent_suggestions.json
├── agent_report.md
└── run_log.txt
```

其中：

- `agent_plan.json` 证明 Agent 做了任务规划。
- `rag_hits.json` 证明审校基于 RAG 检索。
- `ai_context_brief.json` 是 AI 对全片主题、口吻、术语和字幕策略的总体理解。
- `ai_glossary.json` 是 AI 根据当前视频和 RAG 动态归纳的术语表。
- `ai_segment_revisions.json` 是逐段 AI 修正记录，包含原文、修正文、理由和置信度。
- `term_consistency_report.json` 记录全片术语统一规则和实际应用记录。
- `semantic_edit_report.json` 记录 AI 做过的语义排版优化。
- `rhythm_report.json` 记录字幕阅读节奏优化。
- `subtitle_integrity_report.json` 会记录导出前是否补回过空白字幕段。
- `agent_suggestions.json` 是结构化字幕建议。
- `agent_report.md` 是答辩和展示用报告。
- `revised.ass` 是带样式字幕，适合播放器、剪辑软件或后续压制到视频里。
- `revised.clean.ass` 是干净通用版样式字幕。
- `revised.creator.ass` 是更适合短视频/创作者风格的样式字幕。
