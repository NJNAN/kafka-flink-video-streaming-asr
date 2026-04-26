import type { TimelineData } from "../types";

interface SubtitleTimelineProps {
  timeline: TimelineData;
  selectedSubtitleId: string;
  onSubtitleSelect: (subtitleId: string) => void;
}

function left(start: number, duration: number) {
  return `${(start / duration) * 100}%`;
}

function width(start: number, end: number, duration: number) {
  return `${Math.max(((end - start) / duration) * 100, 1.5)}%`;
}

function formatTime(seconds: number) {
  const mins = Math.floor(seconds / 60).toString().padStart(2, "0");
  const secs = Math.floor(seconds % 60).toString().padStart(2, "0");
  return `${mins}:${secs}`;
}

export function SubtitleTimeline({ timeline, selectedSubtitleId, onSubtitleSelect }: SubtitleTimelineProps) {
  const duration = timeline.durationSeconds;

  return (
    <section className="timeline-panel">
      <div className="timeline-header">
        <h3>字幕覆盖率时间轴</h3>
        <div className="timeline-ruler">
          <span>00:00</span>
          <span>{formatTime(duration / 2)}</span>
          <span>{formatTime(duration)}</span>
        </div>
      </div>

      <div className="timeline-layers">
        <div className="layer-label">有声区间</div>
        <div className="timeline-lane voice-lane">
          {timeline.voiceRanges.map((range) => (
            <span
              className="range-block voice-block"
              key={range.id}
              style={{ left: left(range.start, duration), width: width(range.start, range.end, duration) }}
            />
          ))}
        </div>

        <div className="layer-label">字幕区间</div>
        <div className="timeline-lane subtitle-lane">
          {timeline.subtitleSegments.map((segment) => (
            <button
              type="button"
              className={`range-block subtitle-block subtitle-${segment.status} ${
                selectedSubtitleId === segment.id ? "is-selected" : ""
              }`}
              key={segment.id}
              style={{ left: left(segment.start, duration), width: width(segment.start, segment.end, duration) }}
              onClick={() => onSubtitleSelect(segment.id)}
              title={segment.text}
            >
              <span>{segment.status === "recovered" ? "补" : "字"}</span>
            </button>
          ))}
        </div>

        <div className="layer-label">补漏/缺口</div>
        <div className="timeline-lane gap-lane">
          {timeline.gapSegments.map((segment) => (
            <span
              className={`range-block ${segment.kind === "recovery" ? "recovery-block" : "gap-block"}`}
              key={segment.id}
              style={{ left: left(segment.start, duration), width: width(segment.start, segment.end, duration) }}
              title={segment.label}
            >
              {segment.kind === "recovery" ? "补" : "!"}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}
