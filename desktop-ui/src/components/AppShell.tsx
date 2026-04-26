import { DesktopLauncherPanel } from "./DesktopLauncherPanel";
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
import type {
  AppTab,
  BackendHealth,
  ComposeContainer,
  DataSourceState,
  EnvironmentCheck,
  SelectedVideo,
  SubtitleSegment,
  TaskItem,
  WorkbenchSnapshot
} from "../types";

interface AppShellProps {
  snapshot: WorkbenchSnapshot;
  activeTab: AppTab;
  selectedTask: TaskItem;
  selectedSubtitle: SubtitleSegment | null;
  dataSource: DataSourceState;
  desktopAvailable: boolean;
  environment: EnvironmentCheck | null;
  compose: ComposeContainer[];
  backendHealth: BackendHealth | null;
  desktopLogs: string[];
  desktopBusy: boolean;
  desktopMessage: string;
  selectedVideo: SelectedVideo | null;
  onTabChange: (tab: AppTab) => void;
  onTaskSelect: (taskId: string) => void;
  onSubtitleSelect: (subtitleId: string) => void;
  onCheckEnvironment: () => void;
  onStartServices: () => void;
  onStopServices: () => void;
  onRestartServices: () => void;
  onClearLogs: () => void;
  onCopyLogs: () => void;
  onExportLogs: () => void;
  onOpenProject: () => void;
  onOpenResults: () => void;
  onOpenVideos: () => void;
  onSelectVideo: () => void;
  onStartVideoTask: (mode: TaskItem["mode"], copyToWorkspace: boolean) => void;
  onExportZip: () => void;
  onCopyPath: (path: string) => void;
  onSaveEditedSubtitles: (segments: Array<{ start: number; end: number; text: string }>) => void;
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
  dataSource,
  desktopAvailable,
  environment,
  compose,
  backendHealth,
  desktopLogs,
  desktopBusy,
  desktopMessage,
  selectedVideo,
  onTabChange,
  onTaskSelect,
  onSubtitleSelect,
  onCheckEnvironment,
  onStartServices,
  onStopServices,
  onRestartServices,
  onClearLogs,
  onCopyLogs,
  onExportLogs,
  onOpenProject,
  onOpenResults,
  onOpenVideos,
  onSelectVideo,
  onStartVideoTask,
  onExportZip,
  onCopyPath,
  onSaveEditedSubtitles
}: AppShellProps) {
  return (
    <div className="app-leather">
      <div className="device-shell">
        <TopStatusBar services={snapshot.services} dataSource={dataSource} desktopAvailable={desktopAvailable} />

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
                <DesktopLauncherPanel
                  desktopAvailable={desktopAvailable}
                  environment={environment}
                  compose={compose}
                  backendHealth={backendHealth}
                  logs={desktopLogs}
                  busy={desktopBusy}
                  message={desktopMessage}
                  onCheckEnvironment={onCheckEnvironment}
                  onStartServices={onStartServices}
                  onStopServices={onStopServices}
                  onRestartServices={onRestartServices}
                  onClearLogs={onClearLogs}
                  onCopyLogs={onCopyLogs}
                  onExportLogs={onExportLogs}
                  onOpenProject={onOpenProject}
                  onOpenResults={onOpenResults}
                  onOpenVideos={onOpenVideos}
                />
                <VideoPreviewPanel
                  selectedTask={selectedTask}
                  selectedVideo={selectedVideo}
                  desktopAvailable={desktopAvailable}
                  onSelectVideo={onSelectVideo}
                  onStartVideoTask={onStartVideoTask}
                  onOpenVideosFolder={onOpenVideos}
                />
                <SubtitleTimeline
                  timeline={snapshot.timeline}
                  selectedSubtitleId={selectedSubtitle?.id ?? ""}
                  onSubtitleSelect={onSubtitleSelect}
                />
              </>
            )}

            {activeTab === "monitor" && <ServiceMonitorPanel services={snapshot.services} logs={snapshot.logs} compose={compose} backendHealth={backendHealth} />}

            {activeTab === "results" && (
              <ResultExportPanel
                quality={snapshot.quality}
                exports={snapshot.exports}
                timeline={snapshot.timeline}
                taskId={selectedTask.id.startsWith("task_") ? selectedTask.id : undefined}
                onOpenResultsFolder={onOpenResults}
                onCopyPath={onCopyPath}
                onExportZip={onExportZip}
                onSaveEditedSubtitles={onSaveEditedSubtitles}
              />
            )}

            {activeTab === "settings" && <SettingsPanel />}
          </main>

          <aside className="inspector-bay">
            {activeTab === "monitor" ? (
              <QualityReportPanel quality={snapshot.quality} selectedSubtitle={selectedSubtitle} compact />
            ) : activeTab === "results" ? (
              <QualityReportPanel quality={snapshot.quality} selectedSubtitle={selectedSubtitle} />
            ) : activeTab === "settings" ? (
              <ServiceMonitorPanel services={snapshot.services} logs={snapshot.logs.slice(0, 2)} compose={compose} backendHealth={backendHealth} compact />
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
