import { useMemo, useState } from "react";
import type { SubtitleSegment } from "../types";

interface SubtitleEditorPanelProps {
  taskId?: string;
  subtitles: SubtitleSegment[];
  onExportEdited?: (segments: Array<{ start: number; end: number; text: string }>) => void;
}

function cloneSegments(subtitles: SubtitleSegment[]) {
  return subtitles.map((item) => ({ ...item }));
}

export function SubtitleEditorPanel({ taskId, subtitles, onExportEdited }: SubtitleEditorPanelProps) {
  const initial = useMemo(() => cloneSegments(subtitles), [subtitles]);
  const [items, setItems] = useState(initial);
  const [selectedId, setSelectedId] = useState(initial[0]?.id ?? "");
  const selectedIndex = items.findIndex((item) => item.id === selectedId);
  const selected = selectedIndex >= 0 ? items[selectedIndex] : items[0];

  const updateSelected = (patch: Partial<SubtitleSegment>) => {
    if (!selected) {
      return;
    }
    setItems((current) => current.map((item) => (item.id === selected.id ? { ...item, ...patch } : item)));
  };

  const deleteSelected = () => {
    if (!selected) {
      return;
    }
    const next = items.filter((item) => item.id !== selected.id);
    setItems(next);
    setSelectedId(next[Math.max(0, selectedIndex - 1)]?.id ?? "");
  };

  const mergeWith = (direction: "prev" | "next") => {
    if (!selected || selectedIndex < 0) {
      return;
    }
    const targetIndex = direction === "prev" ? selectedIndex - 1 : selectedIndex + 1;
    const target = items[targetIndex];
    if (!target) {
      return;
    }
    const merged = {
      ...selected,
      id: `${target.id}-${selected.id}`,
      start: Math.min(target.start, selected.start),
      end: Math.max(target.end, selected.end),
      text: direction === "prev" ? `${target.text}${selected.text}` : `${selected.text}${target.text}`
    };
    const next = items.filter((_, index) => index !== selectedIndex && index !== targetIndex);
    next.splice(Math.min(selectedIndex, targetIndex), 0, merged);
    setItems(next);
    setSelectedId(merged.id);
  };

  const splitSelected = () => {
    if (!selected) {
      return;
    }
    const midpoint = Math.max(1, Math.floor(selected.text.length / 2));
    const timeMid = selected.start + (selected.end - selected.start) / 2;
    const first = { ...selected, id: `${selected.id}-a`, end: timeMid, text: selected.text.slice(0, midpoint).trim() };
    const second = { ...selected, id: `${selected.id}-b`, start: timeMid, text: selected.text.slice(midpoint).trim() };
    setItems((current) => current.flatMap((item) => (item.id === selected.id ? [first, second] : [item])));
    setSelectedId(first.id);
  };

  return (
    <section className="subtitle-editor">
      <div className="engraved-heading">字幕编辑器</div>
      <div className="editor-grid">
        <div className="subtitle-list-paper">
          {items.map((item, index) => (
            <button
              type="button"
              className={item.id === selected?.id ? "is-selected" : ""}
              key={item.id}
              onClick={() => setSelectedId(item.id)}
            >
              <span>{index + 1}</span>
              <p>{item.text}</p>
              <small>{item.start.toFixed(1)}s - {item.end.toFixed(1)}s</small>
            </button>
          ))}
        </div>

        <div className="subtitle-edit-card">
          {selected ? (
            <>
              <label>
                <span>开始时间</span>
                <input type="number" step="0.1" value={selected.start} onChange={(event) => updateSelected({ start: Number(event.target.value) })} />
              </label>
              <label>
                <span>结束时间</span>
                <input type="number" step="0.1" value={selected.end} onChange={(event) => updateSelected({ end: Number(event.target.value) })} />
              </label>
              <label className="editor-textarea">
                <span>字幕文本</span>
                <textarea value={selected.text} onChange={(event) => updateSelected({ text: event.target.value })} />
              </label>
              <div className="editor-actions">
                <button type="button" onClick={() => mergeWith("prev")}>合并上一条</button>
                <button type="button" onClick={() => mergeWith("next")}>合并下一条</button>
                <button type="button" onClick={splitSelected}>拆分</button>
                <button type="button" onClick={deleteSelected}>删除</button>
                <button
                  type="button"
                  disabled={!taskId}
                  onClick={() => onExportEdited?.(items.map((item) => ({ start: item.start, end: item.end, text: item.text })))}
                >
                  重新导出 SRT/VTT/TXT
                </button>
              </div>
              {!taskId && <small className="editor-note">当前是预览任务，选择桌面任务后可写入对应结果目录。</small>}
            </>
          ) : (
            <p>暂无字幕可编辑。</p>
          )}
        </div>
      </div>
    </section>
  );
}
