import { useEffect, useState } from "react";

const modelOptions = ["small", "base", "medium", "large-v3"];
const hotwords = ["Kafka", "Flink", "字幕补漏", "语音识别", "流处理"];
const corrections = ["卡夫卡 => Kafka", "弗林克 => Flink", "微斯珀 => Whisper"];

export function SettingsPanel() {
  const [settings, setSettings] = useState(() => {
    try {
      return JSON.parse(window.localStorage.getItem("streamsense.desktop.settings") ?? "{}") as Record<string, string | boolean>;
    } catch {
      return {};
    }
  });
  const [recoveryEnabled, setRecoveryEnabled] = useState(settings.recoveryEnabled !== false);
  const [hotwordInput, setHotwordInput] = useState("");

  useEffect(() => {
    window.localStorage.setItem("streamsense.desktop.settings", JSON.stringify({ ...settings, recoveryEnabled }));
  }, [recoveryEnabled, settings]);

  const setSetting = (key: string, value: string) => {
    setSettings((current) => ({ ...current, [key]: value }));
  };

  return (
    <section className="settings-panel">
      <div className="settings-head">
        <h2>系统设置</h2>
        <p>模型、VAD、字幕、热词和错词纠正</p>
      </div>

      <div className="settings-groups">
        <fieldset>
          <legend>ASR 模型</legend>
          <label>
            <span>ASR_MODEL <em title="对应 faster-whisper 模型名称">?</em></span>
            <select value={String(settings.model ?? "large-v3")} onChange={(event) => setSetting("model", event.target.value)}>
              {modelOptions.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </label>
          <label>
            <span>ASR_DEVICE <em title="cuda 适合 NVIDIA GPU，cpu 用于无显卡环境">?</em></span>
            <select value={String(settings.device ?? "cuda")} onChange={(event) => setSetting("device", event.target.value)}>
              <option>cuda</option>
              <option>cpu</option>
            </select>
          </label>
          <label>
            <span>ASR_COMPUTE_TYPE</span>
            <select value={String(settings.computeType ?? "float16")} onChange={(event) => setSetting("computeType", event.target.value)}>
              <option>float16</option>
              <option>int8_float16</option>
              <option>int8</option>
            </select>
          </label>
        </fieldset>

        <fieldset>
          <legend>VAD 与字幕</legend>
          <SliderRow
            label="VAD aggressive"
            min="0"
            max="3"
            value={String(settings.vadAggressive ?? "2")}
            onChange={(value) => setSetting("vadAggressive", value)}
          />
          <SliderRow
            label="切片目标长度 ms"
            min="1000"
            max="8000"
            value={String(settings.vadTargetChunkMs ?? "3000")}
            onChange={(value) => setSetting("vadTargetChunkMs", value)}
          />
          <SliderRow
            label="最长切片 ms"
            min="2000"
            max="12000"
            value={String(settings.vadHardMaxChunkMs ?? "4500")}
            onChange={(value) => setSetting("vadHardMaxChunkMs", value)}
          />
          <SliderRow
            label="字幕最大字符数"
            min="40"
            max="160"
            value={String(settings.subtitleMaxChars ?? "110")}
            onChange={(value) => setSetting("subtitleMaxChars", value)}
          />
          <div className="switch-row">
            <span>启用字幕补漏</span>
            <button
              type="button"
              className={`skeuo-switch ${recoveryEnabled ? "is-on" : ""}`}
              onClick={() => setRecoveryEnabled((value) => !value)}
              aria-pressed={recoveryEnabled}
            >
              <span />
            </button>
          </div>
        </fieldset>

        <fieldset className="paper-list-group">
          <legend>热词词表</legend>
          <div className="paper-list">
            {hotwords.map((word) => (
              <div key={word}>
                <span>{word}</span>
                <button type="button">删除</button>
              </div>
            ))}
          </div>
          <div className="list-editor">
            <input value={hotwordInput} onChange={(event) => setHotwordInput(event.target.value)} placeholder="新增热词" />
            <button type="button">添加</button>
            <button type="button">导入</button>
          </div>
        </fieldset>

        <fieldset className="paper-list-group">
          <legend>错词纠正表</legend>
          <div className="paper-list">
            {corrections.map((item) => (
              <div key={item}>
                <span>{item}</span>
                <button type="button">删除</button>
              </div>
            ))}
          </div>
          <div className="list-editor">
            <input placeholder="错误词 => 正确词" />
            <button type="button">添加</button>
            <button type="button">导入</button>
          </div>
        </fieldset>
      </div>
    </section>
  );
}

function SliderRow({
  label,
  min,
  max,
  value,
  onChange
}: {
  label: string;
  min: string;
  max: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="slider-row">
      <span>{label} <em title="后续接入任务配置接口">?</em></span>
      <input type="range" min={min} max={max} value={value} onChange={(event) => onChange(event.target.value)} />
      <output>{value}</output>
    </label>
  );
}
