import type { TaskItem } from "../types";

interface TaskSidebarProps {
  tasks: TaskItem[];
  selectedTaskId: string;
  onTaskSelect: (taskId: string) => void;
}

const stateLabel: Record<TaskItem["status"], string> = {
  running: "处理中",
  queued: "等待",
  done: "完成",
  review: "复查",
  failed: "失败"
};

export function TaskSidebar({ tasks, selectedTaskId, onTaskSelect }: TaskSidebarProps) {
  return (
    <aside className="task-drawer">
      <div className="drawer-header">
        <span>任务抽屉</span>
        <strong>{tasks.length}</strong>
      </div>

      <div className="task-list">
        {tasks.map((task) => (
          <button
            type="button"
            key={task.id}
            className={`task-card ${selectedTaskId === task.id ? "is-selected" : ""}`}
            onClick={() => onTaskSelect(task.id)}
          >
            <span className={`task-thumb task-thumb-${task.thumbnailTone}`}>
              <span className="play-glyph" />
            </span>
            <span className="task-copy">
              <span className="task-title">{task.title}</span>
              <span className="task-source">{task.source}</span>
              <span className="task-meta">
                <span className={`status-pill status-${task.status}`}>{stateLabel[task.status]}</span>
                <span>{task.elapsed} / {task.duration}</span>
              </span>
              <span className="progress-groove" aria-label={`进度 ${task.progress}%`}>
                <span style={{ width: `${task.progress}%` }} />
              </span>
            </span>
          </button>
        ))}
      </div>
    </aside>
  );
}
