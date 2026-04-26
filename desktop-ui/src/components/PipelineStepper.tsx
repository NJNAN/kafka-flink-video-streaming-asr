import type { PipelineStep } from "../types";

interface PipelineStepperProps {
  steps: PipelineStep[];
}

export function PipelineStepper({ steps }: PipelineStepperProps) {
  return (
    <section className="pipeline-panel" aria-label="工程链路进度">
      <div className="dock-title">视频输入 → FFmpeg/VAD → Kafka → Flink → ASR → 关键词 → 补漏 → 导出</div>
      <div className="pipeline-track">
        {steps.map((step, index) => (
          <div className={`pipeline-node node-${step.state}`} key={step.id}>
            <div className="node-connector" aria-hidden="true" />
            <div className="node-badge">{index + 1}</div>
            <div className="node-label">{step.label}</div>
            <small>{step.detail}</small>
          </div>
        ))}
      </div>
    </section>
  );
}
