import type { ExportFile, QualityMetric, QualityReport, TimelineData } from "../types";

interface ResultExportPanelProps {
  quality: QualityReport;
  exports: ExportFile[];
  timeline: TimelineData;
}

const stateClass: Record<QualityMetric["state"], string> = {
  pass: "result-pass",
  review: "result-review",
  fail: "result-fail"
};

export function ResultExportPanel({ quality, exports, timeline }: ResultExportPanelProps) {
  return (
    <section className="result-center">
      <div className="file-cabinet-head">
        <div>
          <h2>结果中心</h2>
          <p>字幕预览、质量报告与导出托盘</p>
        </div>
        <span>{timeline.subtitleSegments.length} 条预览字幕</span>
      </div>

      <div className="result-metrics">
        {quality.metrics.slice(0, 7).map((metric) => (
          <div className={`result-badge ${stateClass[metric.state]}`} key={metric.key}>
            <small>{metric.label}</small>
            <strong>{metric.value}</strong>
          </div>
        ))}
      </div>

      <div className="subtitle-paper-preview">
        {timeline.subtitleSegments.slice(0, 4).map((segment) => (
          <p key={segment.id}>
            <span>{segment.start.toFixed(1)}s - {segment.end.toFixed(1)}s</span>
            {segment.text}
          </p>
        ))}
      </div>

      <div className="export-tray">
        {exports.map((file) => (
          <article className="document-card" key={file.path}>
            <div className={`document-icon doc-${file.type.toLowerCase()}`}>{file.type}</div>
            <div>
              <h3>{file.fileName}</h3>
              <p>{file.path}</p>
              <small>{file.size} · {file.status === "ready" ? "可导出" : "草稿"}</small>
            </div>
            <div className="document-actions">
              <button type="button">预览</button>
              <button type="button">打开目录</button>
              <button type="button">复制路径</button>
            </div>
          </article>
        ))}
      </div>

      <button className="skeuo-button primary export-all" type="button">导出压缩包</button>
    </section>
  );
}
