import { LiveTranscriptPanel } from "./LiveTranscriptPanel";
import { PipelineStepper } from "./PipelineStepper";
import { QualityReportPanel } from "./QualityReportPanel";
import { ResultExportPanel } from "./ResultExportPanel";
import { ServiceMonitorPanel } from "./ServiceMonitorPanel";
import { SettingsPanel } from "./SettingsPanel";
import { SubtitleTimeline } from "./SubtitleTimeline";
import { TaskSidebar } from "./TaskSidebar";
import { TopStatusBar } from "./TopStatusBar";
import { VideoPreviewPanel } from "./VideoPreviewPanel";
import type { AppTab, SubtitleSegment, TaskItem, WorkbenchSnapshot } from "../types";

interface AppShellProps {
  snapshot: WorkbenchSnapshot;
  activeTab: AppTab;
  selectedTask: TaskItem;
  selectedSubtitle: SubtitleSegment | null;
  onTabChange: (tab: AppTab) => void;
  onTaskSelect: (taskId: string) => void;
  onSubtitleSelect: (subtitleId: string) => void;
}

const tabs: Array<{ id: AppTab; label: string }> = [
  { id: "workbench", label: "任务工作台" },
  { id: "monitor", label: "实时监控" },
  { id: "results", label: "结果中心" },
  { id: "settings", label: "系统设置" }
];

export function AppShell({
  snapshot,
  activeTab,
  selectedTask,
  selectedSubtitle,
  onTabChange,
  onTaskSelect,
  onSubtitleSelect
}: AppShellProps) {
  return (
    <div className="app-leather">
      <div className="device-shell">
        <TopStatusBar services={snapshot.services} />

        <nav className="metal-tabbar" aria-label="主页面">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              className={`tab-button ${activeTab === tab.id ? "is-active" : ""}`}
              type="button"
              onClick={() => onTabChange(tab.id)}
            >
              <span>{tab.label}</span>
            </button>
          ))}
        </nav>

        <div className="desktop-grid">
          <TaskSidebar tasks={snapshot.tasks} selectedTaskId={selectedTask.id} onTaskSelect={onTaskSelect} />

          <main className={`main-bay main-bay-${activeTab}`}>
            {activeTab === "workbench" && (
              <>
                <VideoPreviewPanel selectedTask={selectedTask} />
                <SubtitleTimeline
                  timeline={snapshot.timeline}
                  selectedSubtitleId={selectedSubtitle?.id ?? ""}
                  onSubtitleSelect={onSubtitleSelect}
                />
              </>
            )}

            {activeTab === "monitor" && <ServiceMonitorPanel services={snapshot.services} logs={snapshot.logs} />}

            {activeTab === "results" && (
              <ResultExportPanel quality={snapshot.quality} exports={snapshot.exports} timeline={snapshot.timeline} />
            )}

            {activeTab === "settings" && <SettingsPanel />}
          </main>

          <aside className="inspector-bay">
            {activeTab === "monitor" ? (
              <QualityReportPanel quality={snapshot.quality} selectedSubtitle={selectedSubtitle} compact />
            ) : activeTab === "results" ? (
              <QualityReportPanel quality={snapshot.quality} selectedSubtitle={selectedSubtitle} />
            ) : activeTab === "settings" ? (
              <ServiceMonitorPanel services={snapshot.services} logs={snapshot.logs.slice(0, 2)} compact />
            ) : (
              <QualityReportPanel quality={snapshot.quality} selectedSubtitle={selectedSubtitle} />
            )}
          </aside>
        </div>

        <footer className="bottom-dock">
          <PipelineStepper steps={snapshot.pipeline} />
          <LiveTranscriptPanel logs={snapshot.logs} />
        </footer>
      </div>
    </div>
  );
}
