# Git 提交与仓库说明

这个项目包含大量**本地大文件**和**运行时生成文件**。如果不提前整理，第一次提交 Git 时很容易把模型缓存、视频样本、字幕结果和环境变量一起传上去。

本说明用于告诉你这个仓库现在的 Git 管理约定。

## 1. 应该提交到 Git 的内容

应该提交的是“源代码 + 配置模板 + 文档”：

- `services/`
- `flink/`
- `tools/`
- `config/`
- `docs/`
- `README.md`
- `docker-compose.yml`
- `.env.example`
- `.gitignore`
- `.gitattributes`
- 其他课题说明类 Markdown 文档

这些内容决定了项目是否能被别人复现。

## 2. 不应该提交到 Git 的内容

下面这些内容默认已经被 `.gitignore` 忽略：

- `.env`
- `models/` 下的本地模型缓存
- `videos/` 下的本地测试视频
- 根目录 `input*.mp4`
- `data/audio/` 里的切片音频
- `data/results/` 里的字幕、报告、JSONL、批量结果
- `desktop-ui/dist/`、`desktop-ui/dist-electron/` 前端构建产物
- `desktop-ui/release/`、`desktop-ui/release-*`、`desktop-ui/release-fresh/` Electron 打包产物
- `.claude/`、`.vscode/`、`.idea/` 等本机工具配置
- 各类缓存和日志文件

原因很直接：

- 这些文件体积大
- 很多是机器相关的
- 很多是运行后自动生成的
- 提交后会严重污染仓库历史

## 3. 目录保留方式

虽然 `videos/`、`models/`、`data/audio/`、`data/results/` 被忽略，但目录里保留了 `.gitkeep`，这样仓库克隆下来以后目录结构还是完整的。

## 4. 建议的首次提交流程

如果你还没有初始化 Git，可以在项目根目录执行：

```powershell
git init
git add .
git status
git commit -m "chore: initialize project repository"
```

第一次 `git status` 时，重点确认下面几类文件**没有**出现在待提交列表里：

- `.env`
- `models/` 里的模型目录
- `videos/` 里的视频文件
- `data/results/` 里的字幕和报告
- `data/audio/` 里的音频切片
- `desktop-ui/release/` 或 `desktop-ui/release-fresh/` 里的 exe、unpacked 文件
- `.claude/` 这类本机配置目录

## 5. 推荐的日常提交流程

每次改完代码后，建议按这个顺序做：

```powershell
git status
git add README.md docs services flink tools config docker-compose.yml .gitignore .gitattributes .env.example
git commit -m "feat: describe your change"
```

如果你本次只改了部分目录，就只 `git add` 这些目录，不要无脑 `git add .`。

## 6. 提交前检查清单

提交前至少检查下面几点：

1. `README.md` 是否和当前代码一致。
2. `docs/` 里的说明是否过期。
3. `.env.example` 是否覆盖了新增环境变量。
4. `.gitignore` 是否已经忽略了新增的大文件目录。
5. `git status` 是否干净，没有把运行结果误带上。

## 7. 远程仓库建议

如果你要上传到 GitHub 或 Gitee，建议仓库描述写成：

```text
基于 Kafka-Flink 的本地化视频流语音转写与关键词分析系统，支持真实视频输入、字幕生成、关键词检测与批量验收。
```

建议仓库首页展示顺序：

1. README
2. 关键架构图或流程图
3. 批量验收结果截图
4. 示例字幕文件截图
5. 课题文档说明
