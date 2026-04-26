import type { QualityMetric, QualityReport, SubtitleSegment } from "../types";

interface QualityReportPanelProps {
  quality: QualityReport;
  selectedSubtitle: SubtitleSegment | null;
  compact?: boolean;
}

const metricClass: Record<QualityMetric["state"], string> = {
  pass: "badge-pass",
  review: "badge-review",
  fail: "badge-fail"
};

export function QualityReportPanel({ quality, selectedSubtitle, compact = false }: QualityReportPanelProps) {
  return (
    <section className={`quality-panel ${compact ? "is-compact" : ""}`}>
      <div className="engraved-heading">质量检查</div>

      <div className="metric-grid">
        {quality.metrics.map((metric) => (
          <div className="metric-plate" key={metric.key}>
            <span>{metric.label}</span>
            <strong>{metric.value}</strong>
            <em className={metricClass[metric.state]}>{metric.state === "pass" ? "通过" : metric.state === "review" ? "复查" : "失败"}</em>
            <small>{metric.hint}</small>
          </div>
        ))}
      </div>

      <div className="hotword-bank">
        <div className="engraved-subheading">热词</div>
        <div>
          {quality.hotwords.map((word) => (
            <span className="hotword-chip" key={word}>{word}</span>
          ))}
        </div>
      </div>

      {selectedSubtitle && !compact && (
        <div className="subtitle-detail">
          <div className="engraved-subheading">字幕块详情</div>
          <dl>
            <div>
              <dt>开始</dt>
              <dd>{selectedSubtitle.start.toFixed(1)}s</dd>
            </div>
            <div>
              <dt>结束</dt>
              <dd>{selectedSubtitle.end.toFixed(1)}s</dd>
            </div>
            <div>
              <dt>耗时</dt>
              <dd>{selectedSubtitle.processingMs}ms</dd>
            </div>
            <div>
              <dt>状态</dt>
              <dd>{selectedSubtitle.status}</dd>
            </div>
          </dl>
          <p>{selectedSubtitle.text}</p>
          <div className="detail-keywords">
            {selectedSubtitle.keywords.map((keyword) => (
              <span key={keyword}>{keyword}</span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}
