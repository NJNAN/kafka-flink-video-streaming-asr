import { useState } from "react";

const modelOptions = ["small", "base", "medium", "large-v3"];
const hotwords = ["Kafka", "Flink", "字幕补漏", "语音识别", "流处理"];
const corrections = ["卡夫卡 => Kafka", "弗林克 => Flink", "微斯珀 => Whisper"];

export function SettingsPanel() {
  const [recoveryEnabled, setRecoveryEnabled] = useState(true);
  const [hotwordInput, setHotwordInput] = useState("");

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
            <select defaultValue="large-v3">
              {modelOptions.map((option) => (
                <option key={option}>{option}</option>
              ))}
            </select>
          </label>
          <label>
            <span>ASR_DEVICE <em title="cuda 适合 NVIDIA GPU，cpu 用于无显卡环境">?</em></span>
            <select defaultValue="cuda">
              <option>cuda</option>
              <option>cpu</option>
            </select>
          </label>
          <label>
            <span>ASR_COMPUTE_TYPE</span>
            <select defaultValue="float16">
              <option>float16</option>
              <option>int8_float16</option>
              <option>int8</option>
            </select>
          </label>
        </fieldset>

        <fieldset>
          <legend>VAD 与字幕</legend>
          <SliderRow label="VAD aggressive" min="0" max="3" defaultValue="2" />
          <SliderRow label="切片目标长度 ms" min="1000" max="8000" defaultValue="3000" />
          <SliderRow label="最长切片 ms" min="2000" max="12000" defaultValue="4500" />
          <SliderRow label="字幕最大字符数" min="40" max="160" defaultValue="110" />
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

function SliderRow({ label, min, max, defaultValue }: { label: string; min: string; max: string; defaultValue: string }) {
  return (
    <label className="slider-row">
      <span>{label} <em title="后续接入任务配置接口">?</em></span>
      <input type="range" min={min} max={max} defaultValue={defaultValue} />
      <output>{defaultValue}</output>
    </label>
  );
}
