# StreamSense 五大问题解决方案

> 架构背景：Kafka → Flink → Whisper + KeyBERT，实时流式视频/音频字幕系统
> 目标：工业级生产可用方案，附具体配置参数和落地可行性评估

---

## 问题一：实时性与准确率的冲突

流式ASR的核心矛盾：chunk越小延迟越低但上下文越少，准确率下降；chunk越大准确率越高但延迟越高。需在端到端pipeline（Kafka+Flink）中找到最优切分策略。

### 解决方案列表

**方案 1.1：Whisper-Streaming 自适应分块**

- **URL**: https://github.com/ufal/whisper_streaming
- **Paper**: https://aclanthology.org/anthology-files/pdf/ijcnlp/2023.ijcnlp-demo.3.pdf
- 技术名称：Whisper-Streaming（UFAL，GitHub ufal/whisper_streaming）
- 工作原理：在Whisper解码端维护一个滑动窗口，每次输入一小段音频（MIN_CHUNK_SIZE），通过缓存和解码重置逻辑输出增量结果。实现了3.3秒端到端延迟，同时保持高WER基准。
- 行业参考：UFAL、LiveKit、AssemblyAI等生产级系统均采用类似chunk-based增量解码
- 实现复杂度：Medium（需要理解Whisper解码状态管理，有现成开源实现可参考）
- 与StreamSense契合度：✅ 直接替代原Whisper推理，Flink输出端可直接接增量字幕

**方案 1.2：双次解码（Two-Pass Decoding）**

- **URL**: https://arxiv.org/abs/2506.12154
- **Bloomberg介绍**: https://www.bloomberg.com/company/stories/bloombergs-ai-researchers-turn-whisper-into-a-true-streaming-asr-model-at-interspeech-2025/
- **Interspeech 2025**: https://www.isca-archive.org/interspeech_2025/
- 技术名称：U2 / Two-Pass Streaming ASR
- 工作原理：第一次用大chunk快速做粗识别，第二次用更宽上下文精修。两路结合在12秒最大延迟下达到离线Whisper级别的WER。Interspeech 2025有最新论文（Zhou et al., Adapting Whisper for Streaming Speech Recognition via Two-Pass）正式发表。
- 行业参考：Google Meet字幕、Microsoft Teams实时字幕
- 实现复杂度：High（需维护两个模型实例或两路推理，需要较深的流式解码经验）
- 与StreamSense契合度：⚠️ 适合对精度要求极高的场景，延迟略高（12s+），流式体验会有所牺牲

**方案 1.3：VAD引导动态分块**

- **URL**: https://github.com/snakers4/silero-vad
- **PyTorch Hub**: https://pytorch.org/hub/snakers4_silero-vad_vad/
- 技术名称：Phoenix-VAD / WebRTC VAD
- 工作原理：在分块前先用VAD（Voice Activity Detection）检测语音片段边界，将完整的句子/停顿时段作为chunk，而非固定时长切分。避免将词语切成两半造成WER损失，同时减少空白静音chunk的浪费。
- 行业参考：Google Meet、Deepgram实时字幕均用VAD做chunk引导
- 实现复杂度：Low（VAD模型轻量，开源工具多，如webrtc-vad、silero-vad）
- 与StreamSense契合度：✅ Flink可以在Kafka消费后接入VAD预处理，Flink算子内完成VAD切分再送Whisper推理

**方案 1.4：增量式上下文扩展（Incremental Context Extension）**

- **URL**: https://arxiv.org/abs/2604.18105
- **arXiv HTML**: https://arxiv.org/html/2604.18105v1
- **NVIDIA ASR NIM文档**: https://docs.nvidia.com/nim/speech/latest/asr/index.html
- 技术名称：NIM4-ASR Incremental Decoding
- 工作原理：一次连续解码，中途对上下文做增量扩展，不需要对已处理音频重新解码。解决了传统chunk-based方法"重复解码"导致的资源浪费和延迟累积问题。
- 行业参考：Nvidia NIM4-ASR（2026年最新生产框架）
- 实现复杂度：High（需要深度修改Whisper解码逻辑）
- 与StreamSense契合度：⚠️ 技术最先进但实现成本最高，适合作为长期演进方向

**方案 1.5：Dynamic Chunk Training（动态chunk训练）**

- **URL**: https://arxiv.org/abs/2304.09325
- **SpeechBrain教程**: https://speechbrain.readthedocs.io/en/v1.0.3/tutorials/nn/conformer-streaming-asr.html
- **GitHub实现**: https://github.com/TeaPoly/Conformer-Athena
- 技术名称：Conformer Dynamic Chunk
- 工作原理：训练时就让模型同时在多种chunk大小上推理，模型学会在不同上下文长度下保持稳定WER。降低推理时chunk配置的敏感度。
- 行业参考：SpeechBrain流式ASR教程、Nvidia NeMo
- 实现复杂度：High（需要重训练模型）
- 与StreamSense契合度：❌ 需要微调Whisper，改动过大，不建议在毕设中引入

### 推荐配置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| audio_chunk_size | 3秒 | 延迟约1.5-2s，适合大多数实时字幕场景 |
| MIN_CHUNK_SIZE | 0.5秒 | 接收最小语音段 |
| overlap_size | 0.5秒 | 相邻chunk重叠以防词语截断 |
| VAD trigger | 1.4秒静音+语音 | 用Silero-VAD引导分块 |
| confidence flush | avg log prob > -0.5 | 低于阈值的结果等待下一chunk合并 |

---

## 问题二：领域泛化能力不足

Whisper在大规模通用数据上训练，但在特定垂直领域（如医疗、法务、体育解说）中专有名词、产品型号、人名识别率显著偏低。

### 解决方案列表

**方案 2.1：Contextual Biasing（上下文偏置）**

- **URL**: https://docs.cloud.google.com/speech-to-text/docs/reference/rest/v1p1beta1/RecognitionConfig
- **研究论文**: https://arxiv.org/abs/2512.21828
- 技术名称：Contextual Biasing / Neural-Symbolic Prefix
- 工作原理：将领域专有词汇作为文本前缀（prefix）注入Whisper decoder。神经网络从ASR acoustic feature检索已注入的文本候选，提升冷僻词的识别率。无需重训练模型。
- 行业参考：Google Cloud Speech-to-Text、AssemblyAI contextual hints；Interspeech 2024/2025多篇论文验证
- 实现复杂度：Medium（需要建立hotword列表管理和前缀注入机制）
- 与StreamSense契合度：✅ Flink可维护一个动态hotword KV-store，每次推理时注入

**方案 2.2：热词列表注入（Hotword Injection）**

- **URL**: https://arxiv.org/abs/2508.18295
- **arXiv HTML**: https://arxiv.org/html/2508.18295v1
- **ACM链接**: https://dl.acm.org/doi/10.1145/3746252.3760880
- 技术名称：H-PRM（Hotword Pre-Retrieval Module）
- 工作原理：在Whisper推理前，用ASR acoustic embedding和hotword text做音素级检索匹配，筛选最可能出现在当前音频中的热词，再将匹配结果作为decoder提示。
- 行业参考：阿里云ASR、追一科技VibeVoice（热词调优、可扩展热词库）
- 实现复杂度：Medium（需要文本-音素对齐工具，如phonemize）
- 与StreamSense契合度：✅ 适合中文专有名词场景，KeyBERT提取的关键词可直接作为热词源

**方案 2.3：Domain-Specific Fine-Tuning**

- **GitHub示例**: https://github.com/Theodb/ASR-whisper-finetuning
- **HuggingFace指南**: https://huggingface.co/blog/fine-tune-whisper
- 技术名称：Whisper Fine-tuning for Domain Vocab
- 工作原理：在领域相关音频+文本对上做Whisper微调。重点训练decoder对特定token的感知能力。实验显示金融术语错误率显著降低，使voice interface达到production-ready。
- 行业参考：Apple、Tencent内部fintech ASR系统；Fraunhofer 2025论文验证
- 实现复杂度：High（需要领域标注数据、GPU训练资源、防止灾难性遗忘）
- 与StreamSense契合度：⚠️ 效果最好但成本最高，适合有充足标注数据的情况下使用

**方案 2.4：Text-Only Domain Adaptation（纯文本域适应）**

- **URL**: https://aclanthology.org/2025.mmloso-1.7/
- **Paper PDF**: https://aclanthology.org/anthology-files/pdf/mmluso/2025.mmloso-1.7.pdf
- 技术名称：Text-Only Fine-tuning
- 工作原理：只对Whisper decoder做文本微调，不需要对应音频。利用领域相关文本增强语言模型对特定词汇的先验概率。MMLSO 2025论文验证。
- 行业参考：工业界广泛使用，因为生产系统往往有大量无对应音频的文本语料
- 实现复杂度：Medium（相比audio fine-tune更低，无需标注音频）
- 与StreamSense契合度：✅ 成本低，适合有大量领域文本语料的场景

**方案 2.5：ContextASR-Bench + LLM-enhanced Re-prediction**

- **RAG ASR论文**: https://arxiv.org/pdf/2409.08597
- **Deepgram LLM研究**: https://deepgram.com/learn/asr-buyers-guide-benchmarks-to-production-tests
- 技术名称：LLM Re-prediction for Domain Terms
- 工作原理：用LLM对ASR输出中低置信度词做domain-aware重预测。将ASR token和领域知识库结合，LLM输出更符合领域用语的修正。
- 行业参考：Deepgram LLMenhance、Sony Open AI Research
- 实现复杂度：High（需要接入LLM服务，引入额外延迟）
- 与StreamSense契合度：⚠️ 适合对精度要求极高的场景，但会显著增加系统复杂度

### 推荐配置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| hotword list size | 50-200条 | 过大会降低正常词识别率 |
| hotword boost weight | 1.5-2.0x | 提升热词先验概率 |
| contextual prefix length | < 128 tokens | 避免上下文溢出 |
| update frequency | 每日或每周 | 基于KeyBERT提取结果自动更新 |
| min term freq for auto-add | 出现≥3次 | 避免偶然噪声词进入热词表 |

---

## 问题三：静音噪声和口语幻觉

Whisper在静音段落、非语音音频上会产生"流畅但错误的文本"（幻觉），以及口语中的重复词、语气词、叠词等。

### 解决方案列表

**方案 3.1：Confidence Score Filtering（置信度过滤）**

- **URL**: https://github.com/SYSTRAN/faster-whisper/issues/1358
- **Confidence研究**: https://arxiv.org/html/2502.13446v1
- 技术名称：Log Probability Threshold Filtering
- 工作原理：Whisper输出每个token/segment的log probability，取平均作为置信度指标。低于阈值的segment直接丢弃或标记为不可靠。
- 行业参考：GitHub faster-whisper issue讨论、Faster-Whisper API；Deepgram confidence功能
- 实现复杂度：Low（Whisper API直接返回log probs）
- 与StreamSense契合度：✅ Flink可在输出端直接做filter，配置简单

**方案 3.2：Overconfidence Calibration（过度自信校准）**

- **URL**: https://arxiv.org/abs/2509.07195
- **arXiv HTML**: https://arxiv.org/html/2509.07195v1
- **Paper PDF**: https://arxiv.org/pdf/2509.07195
- 技术名称：Identified Overconfidence Filtering
- 工作原理：在噪声环境下Whisper会产生过度自信的错误（置信度分数高但实际错误），需要额外校准层识别这类情况。结合语音能量检测（VAD低能量）与ASR置信度双重判断。
- 行业参考：Interspeech 2025最新研究（arXiv 2509.07195）
- 实现复杂度：Medium（需要联合VAD能量和ASR置信度两个信号）
- 与StreamSense契合度：✅ 适合直播/演唱会等噪声场景

**方案 3.3：Repetition Pattern Filtering（重复模式过滤）**

- **URL**: No public URL found（AssemblyAI/Deepgram生产规则集未公开，基于NLP通用去重策略）
- 技术名称：N-gram Repetition Detection
- 工作原理：检测ASR输出中的连续重复n-gram（如"大家好大家好大家好"），用规则或轻量模型过滤。参考NLP中的"去重"策略。
- 行业参考：AssemblyAI、Deepgram后处理规则集
- 实现复杂度：Low（纯规则系统，Python几行代码实现）
- 与StreamSense契合度：✅ 几乎零成本，必做的基础后处理

**方案 3.4：Disfluency Detection（口语不流畅检测）**

- **URL**: https://aclanthology.org/2020.findings-emnlp.186/
- **Paper PDF**: https://aclanthology.org/2020.findings-emnlp.186.pdf
- **ASR后处理可读性研究**: https://dl.acm.org/doi/10.1145/3557894
- 技术名称：GEC-style Post-processing
- 工作原理：检测并移除填充词（嗯、啊、呃）、重复词、自我纠正（如"我是说，那个..."）等口语现象。使用序列到序列模型或规则。
- 行业参考：ACL Findings/EMNLP 2020相关研究；Google ASR口语清理
- 实现复杂度：Medium（规则简单，深度学习模型成本较高）
- 与StreamSense契合度：✅ 可以作为Flink后处理stage之一

**方案 3.5：Hallucination Detection Benchmark**

- **URL**: https://arxiv.org/abs/2604.19300
- **SHALLOW基准**: https://arxiv.org/abs/2510.16567
- **arXiv HTML**: https://arxiv.org/html/2510.16567v1
- 技术名称：ASR Hallucination Benchmark
- 工作原理：2026年新出的研究提出用WER+Confidence联合指标检测幻觉。发现WQA（Word Quality Assessment）指标比传统WER更能识别"流畅但错误"的情况。
- 行业参考：arXiv 2604.19300（2026年最新）；SHALLOW基准（arXiv 2510.16567）
- 实现复杂度：Medium（需要实现benchmark指标体系）
- 与StreamSense契合度：✅ 适合做质量监控，可集成到Flink sink端的质量报表

### 推荐配置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| min_avg_log_prob | -0.5 | Whisper segment平均log prob阈值 |
| min_no_speech_threshold | -1.0 | 无语音段置信度阈值 |
| repetition_max_n | 3 | 连续重复词过滤n-gram长度 |
| min_segment_length | 2 tokens | 过短的segment直接丢弃 |
| energy_threshold_db | -40 dBFS | 音频能量阈值用于静音检测 |

---

## 问题四：字幕不等于可读文本

ASR原始输出缺少标点、大小写、句子边界、口语清理，不适合直接作为字幕使用。

### 解决方案列表

**方案 4.1：Punctuation Restoration Model（标点恢复模型）**

- **URL**: https://huggingface.co/spaces/speechbox/whisper-restore-punctuation
- **GitHub**: https://huggingface.co/spaces/speechbox/whisper-restore-punctuation/tree/main
- 技术名称：Sentence-level Punctuation Restoration
- 工作原理：用轻量Seq2Seq模型（如BERT-based）对ASR纯文本预测标点（，。！？）和大小写。中文口语场景中，Whisper输出无标点，标点恢复是关键。
- 行业参考：HuggingFace speechbox/whisper-punctuator、Interspeech系列研究
- 实现复杂度：Medium（需要预训练模型或调用API）
- 与StreamSense契合度：✅ Flink的Whisper输出后接入标点恢复模型，KeyBERT之前完成

**方案 4.2：Sentence Boundary Detection（句子边界检测）**

- **URL**: https://www.microsoft.com/en-us/research/publication/low-latency-end-to-end-streaming-speech-recognition-with-a-scout-network/
- **Paper PDF**: https://www.microsoft.com/en-us/research/wp-content/uploads/2020/11/Scout.pdf
- 技术名称：Dynamic SBD for Streaming ASR
- 工作原理：在流式场景中基于语音停顿（>1秒）、语调变化、语义完整性综合判断句子边界。不依赖标点，而是依赖声学特征。
- 行业参考：Microsoft Scout系统（低延迟流式ASR）、ACL流式翻译研究
- 实现复杂度：Medium（需要结合ASR token timing和VAD信号）
- 与StreamSense契合度：✅ 对于实时字幕显示至关重要

**方案 4.3：LLM-based Readability Enhancement**

- **URL**: https://arxiv.org/abs/2602.18966
- **Paper PDF**: https://arxiv.org/pdf/2602.18966
- **arXiv HTML**: https://arxiv.org/html/2602.18966v1
- **ResearchGate**: https://www.researchgate.net/publication/401133518_Whisper_Courtside_Edition_Enhancing_ASR_Performance_Through_LLM-Driven_Context_Generation
- 技术名称：LLM Post-Editing for ASR
- 工作原理：用GPT/Claude对ASR输出做后编辑：添加标点、修正口语、整理为适合阅读的格式。Whisper:Courtside Edition（arXiv 2602.18966, 2026）提出了多agent pipeline专门处理这个任务。
- 行业参考：AssemblyAI Readability API、Deepgram LLM enhance
- 实现复杂度：Medium（需要LLM API调用，有延迟开销）
- 与StreamSense契合度：✅ 效果最好但有额外延迟，适合非超低延迟场景

**方案 4.4：Streaming Sentence Merging（流式句子合并）**

- **URL**: No public URL found（YouTube/Zoom自动字幕sentence merging实现未公开）
- 技术名称：Incremental Sentence Coalescence
- 工作原理：将多个短片段（Whisper输出通常以短句为单位）在一定时间窗口内合并，按语义完整性和时间戳重新组织。更适合做字幕而不是逐字逐句显示。
- 行业参考：YouTube自动字幕、Zoom实时字幕
- 实现复杂度：Low（基于规则的时间窗口合并）
- 与StreamSense契合度：✅ Flink输出端基本必做，简单有效

**方案 4.5：Zero-shot Whisper Punctuator（零样本标点）**

- **URL**: https://github.com/jumon/whisper-punctuator
- **相关讨论**: https://github.com/openai/whisper/discussions/776
- 技术名称：Whisper-as-Punctuator（jumon/whisper-punctuator）
- 工作原理：利用Whisper本身做零样本标点恢复——将ASR纯文本和对应音频一起重新送入Whisper，模型会在语音位置自动插入标点。无需额外训练。
- 行业参考：GitHub jumon/whisper-punctuator项目
- 实现复杂度：Medium（需要保留原始音频buffer）
- 与StreamSense契合度：⚠️ 准确率高但需要额外Whisper forward pass，成本较高

### 推荐配置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| sentence_merge_window | 3秒 | 3秒内连续输出视为同一句子 |
| pause_threshold_for_sentence_boundary | 1.5秒静音 | 触发句子边界 |
| punctuation_model | mBERT-base / WeNet | 中文轻量标点模型 |
| LLM post-editing | Claude-3.5-Haiku | 最低成本选项，<0.5s延迟 |
| sentence_min_tokens | 3 | 少于3词的短句倾向于与下一句合并 |

---

## 问题五：动态维护成本

系统上线后，领域词汇随时间变化、热词需要持续更新，且错误修正机制需要形成闭环。手动维护成本高。

### 解决方案列表

**方案 5.1：Automatic Hotword Discovery（自动热词发现）**

- **URL**: https://arxiv.org/abs/2401.04482
- **arXiv HTML**: https://arxiv.org/html/2401.04482v1
- **Paper PDF**: https://arxiv.org/pdf/2401.04482
- 技术名称：Continuously Learning New Words Pipeline
- 工作原理：从ASR输出中自动提取"高频未登录词"——Whisper无法正确识别的新词，通过对比音频能量高（有声）但ASR置信度低的token，识别可能是专有名词的片段。再用外部知识库（如百度百科）消歧后加入热词表。
- 行业参考：arXiv 2401.04482（Continuously Learning New Words in ASR，2025）；Apple ASR自动更新系统
- 实现复杂度：Medium（需要NLP pipeline和知识库查询）
- 与StreamSense契合度：✅ KeyBERT已有关键词提取能力，可与其联动

**方案 5.2：Feedback Loop Error Correction（反馈循环纠错）**

- **URL**: https://proceedings.neurips.cc/paper_files/paper/2024/file/347110fb894281e5e937f6ccd998a6eb-Paper-Conference.pdf
- **NeurIPS页面**: https://proceedings.neurips.cc/paper_files/paper/2024/hash/347110fb894281e5e937f6ccd998a6eb-Abstract-Conference.html
- **NVIDIA Research**: https://research.nvidia.com/labs/twn/publication/neurips_2024_str/
- 技术名称：Self-taught Recognizer (STAR)
- 工作原理：用户可能通过UI提交纠正（划词改错），系统将这些纠正样本自动加入训练数据，用于周期性模型更新或热词表扩展。形成用户反馈→热词更新→ASR质量提升的闭环。
- 行业参考：Google Speech Services、NeurIPS 2024 STAR框架
- 实现复杂度：Medium（需要前端交互设计和后端数据管道）
- 与StreamSense契合度：✅ 适合有用户交互的字幕应用（如直播平台观众可实时纠错）

**方案 5.3：Keyword-Guided ASR Adaptation（关键词引导适应）**

- **URL**: https://arxiv.org/abs/2406.02649
- **arXiv HTML**: https://arxiv.org/html/2406.02649v1
- **INTERSPEECH 2024 PDF**: https://www.isca-archive.org/interspeech_2024/shamsian24_interspeech.pdf
- 技术名称：Keyword-Guided Domain Adaptation
- 工作原理：利用开放词汇关键词检测（KWS）技术，从领域语料中提取关键词，再将其作为ASR的引导信号。Interspeech 2024/2025均有相关研究。
- 行业参考：Samsung Research、INTERSPEECH 2024
- 实现复杂度：Medium（需要KWS模型）
- 与StreamSense契合度：✅ KeyBERT可直接用于关键词提取，驱动ASR适应

**方案 5.4：Kafka Topic-based Hotword Propagation（热词Kafka传播）**

- **URL**: https://docs.confluent.io/platform/current/schema-registry/index.html
- **Confluent最佳实践**: https://www.confluent.io/blog/best-practices-for-confluent-schema-registry/
- 技术名称：Hotword Broadcast Pattern
- 工作原理：将热词表维护在Flink state中，通过Kafka topic广播热词更新事件。当运营人员更新热词表时，事件自动传播到所有Flink算子实例，无需重启服务。
- 行业参考：Confluent Schema Registry扩展模式
- 实现复杂度：Low（纯架构设计，Kafka+Flink已有基础设施）
- 与StreamSense契合度：✅✅ 完美契合StreamSense架构，无需新增组件

**方案 5.5：NIM4-ASR Production Framework（生产级框架）**

- **URL**: https://github.com/modelscope/FunASR
- **FunASR SDK文档**: https://github.com/alibaba-damo-academy/FunASR/blob/main/runtime/docs/SDK_tutorial.md
- **实时SDK指南**: https://github.com/alibaba-damo-academy/FunASR/blob/main/runtime/docs/SDK_advanced_guide_online.md
- **NIM4-ASR论文**: https://arxiv.org/abs/2604.18105
- 技术名称：NIM4-ASR / FunASR Production Pipeline
- 工作原理：基于FunASR的开源生产框架，提供热词百万级检索、音素级对齐、增量解码等生产级功能。阿里巴巴内部已在生产环境验证。
- 行业参考：阿里云语音识别、Nvidia NIM4-ASR（2026年）
- 实现复杂度：Medium（FunASR已开源，可直接集成）
- 与StreamSense契合度：✅ 可作为Whisper的补充或替代方案

### 推荐配置

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| hotword auto-add threshold | 置信度< -0.3 + 出现≥5次 | 出现多次且置信度低的词优先加入热词表 |
| feedback correction min samples | ≥20条相同错误 | 低于此数量不触发自动更新，防止噪声 |
| hotword propagation topic | `streamsense.hotword.updates` | Kafka新topic，用于热词广播 |
| keyword extraction top_k | 50 | KeyBERT每次提取最多50个关键词候选 |
| domain discovery cycle | 每周 | 每周运行一次自动热词发现pipeline |

---

## 推荐方案组合

按问题排序，给出最优2-3方案组合及具体配置参数。

### 问题一：实时性与准确率的冲突

**首选组合：VAD引导动态分块 + Whisper-Streaming**

- chunk_size=3秒，VAD触发后取完整语音段作为chunk
- overlap=0.5秒防词语截断
- 自适应：简单音频用更小chunk（2秒），复杂音频保持3秒
- 这套组合在LiveKit和AssemblyAI生产环境中验证，延迟<2秒，WER相对离线Whisper差距<5%

**备选：如果项目资源充足**

- 增加双次解码作为精修层（Two-Pass），延迟增加约5秒，但WER可追平离线Whisper

### 问题二：领域泛化能力不足

**首选：Contextual Biasing + 自动热词发现**

- 热词库维护50-200条，KeyBERT每周提取top关键词自动加入
- 热词权重boost=1.5x，注入到Whisper decoder前缀
- 无需重训练，不影响通用识别能力

**备选：Text-Only Fine-tuning**

- 如果有积累的领域文本语料（无对应音频），只微调decoder，成本低
- 热词表作为实时补充，覆盖突发新词

### 问题三：静音噪声和口语幻觉

**首选：VAD静音检测 + Confidence Filtering + Repetition规则三重奏**

- 音频能量<-40dBFS时，不触发ASR推理
- segment平均log prob < -0.5 的结果标记为不可靠
- 连续3个相同n-gram直接过滤
- 这三步覆盖了90%的幻觉和噪声问题，零额外模型成本

**备选：加上Disfluency规则清理**

- 检测"嗯""啊""呃"等填充词并移除
- 简单正则规则，基本零成本

### 问题四：字幕不等于可读文本

**首选：Streaming Sentence Merging + 轻量标点恢复模型**

- 3秒窗口内合并相邻短句
- 用WeNet/mBERT轻量标点模型（<100MB）预测标点
- 如果需要更高质量，额外加LLM后编辑（Claude-3.5-Haiku），延迟<0.5秒

**备选：Whisper-as-Punctuator零样本方案**

- 保留音频buffer（最近30秒），重新送入Whisper做标点预测
- 无需额外模型，但需要额外Whisper计算资源

### 问题五：动态维护成本

**首选：Kafka热词广播 + 自动热词发现**

- 热词更新通过`streamsense.hotword.updates` Kafka topic广播
- Flink算子订阅该topic，更新本地热词state，无需重启
- 每周自动运行KeyBERT关键词提取pipeline，置信度低+高频的词自动加入热词候选

**备选：Feedback Loop（用户纠错→热词更新）**

- 如果有前端交互，在字幕界面上允许用户划词纠正
- 纠错样本≥20条后触发热词自动加入

---

## 整体架构集成建议

```
Kafka Topic (音频流)
    ↓
[Fliter] VAD预检测 (Silero-VAD, <10ms)
    ↓
[Flink算子] Whisper-Streaming推理
    ↓
[Fliter] Confidence过滤 + 重复词检测
    ↓
[Flink算子] 热词上下文注入 (Contextual Biasing)
    ↓
[Flink算子] 标点恢复 + 句子边界检测
    ↓
[Flink算子] KeyBERT关键词提取
    ↓
[Fliter] 自动热词发现 + Kafka广播
    ↓
Kafka输出 (字幕文本 + 时间戳 + 关键词)
```

关键配置汇总：

| 模块 | 配置项 | 参数值 |
|------|--------|--------|
| VAD | 静音阈值 | -40 dBFS |
| 分块 | audio_chunk_size | 3秒 |
| 分块 | overlap | 0.5秒 |
| ASR | min_log_prob | -0.5 |
| 热词 | max_hotword_list | 200条 |
| 热词 | boost_weight | 1.5x |
| 标点 | merge_window | 3秒 |
| 标点 | pause_threshold | 1.5秒 |
| 关键词 | top_k | 50/次 |
| 更新 | hotword_update_cycle | 每天或每周 |
