import type { ExportFile, QualityMetric, QualityReport, TimelineData } from "../types";
import { SubtitleEditorPanel } from "./SubtitleEditorPanel";

interface ResultExportPanelProps {
  quality: QualityReport;
  exports: ExportFile[];
  timeline: TimelineData;
  taskId?: string;
  onOpenResultsFolder?: () => void;
  onCopyPath?: (path: string) => void;
  onExportZip?: () => void;
  onSaveEditedSubtitles?: (segments: Array<{ start: number; end: number; text: string }>) => void;
}

const stateClass: Record<QualityMetric["state"], string> = {
  pass: "result-pass",
  review: "result-review",
  fail: "result-fail"
};

export function ResultExportPanel({
  quality,
  exports,
  timeline,
  taskId,
  onOpenResultsFolder,
  onCopyPath,
  onExportZip,
  onSaveEditedSubtitles
}: ResultExportPanelProps) {
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
              <button type="button" onClick={onOpenResultsFolder}>打开目录</button>
              <button type="button" onClick={() => onCopyPath?.(file.path)}>复制路径</button>
            </div>
          </article>
        ))}
      </div>

      <div className="result-actions">
        <button className="skeuo-button primary export-all" type="button" onClick={onExportZip}>导出 ZIP</button>
        <button className="skeuo-button" type="button" onClick={onOpenResultsFolder}>打开结果目录</button>
        <button className="skeuo-button" type="button">重新生成字幕</button>
        <button className="skeuo-button" type="button">打开原始视频</button>
      </div>

      <SubtitleEditorPanel taskId={taskId} subtitles={timeline.subtitleSegments} onExportEdited={onSaveEditedSubtitles} />
    </section>
  );
}
