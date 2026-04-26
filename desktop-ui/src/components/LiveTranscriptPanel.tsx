import type { LogLine } from "../types";

interface LiveTranscriptPanelProps {
  logs: LogLine[];
}

export function LiveTranscriptPanel({ logs }: LiveTranscriptPanelProps) {
  return (
    <section className="lcd-log">
      <div className="dock-title">实时转写日志</div>
      <div className="lcd-window">
        {logs.map((line) => (
          <div className={`log-line log-${line.level.toLowerCase()}`} key={line.id}>
            <span>{line.time}</span>
            <strong>{line.source}</strong>
            <p>{line.message}</p>
          </div>
        ))}
      </div>
    </section>
  );
}
