import { useEffect, useMemo, useState } from "react";
import { fetchWorkbenchSnapshot } from "./api/apiClient";
import { AppShell } from "./components/AppShell";
import type { AppTab, SubtitleSegment, WorkbenchSnapshot } from "./types";

export function App() {
  const [snapshot, setSnapshot] = useState<WorkbenchSnapshot | null>(null);
  const [activeTab, setActiveTab] = useState<AppTab>("workbench");
  const [selectedTaskId, setSelectedTaskId] = useState("task-dino");
  const [selectedSubtitleId, setSelectedSubtitleId] = useState("sub-003");

  useEffect(() => {
    fetchWorkbenchSnapshot().then(setSnapshot);
  }, []);

  const selectedTask = useMemo(() => {
    if (!snapshot) {
      return null;
    }
    return snapshot.tasks.find((task) => task.id === selectedTaskId) ?? snapshot.tasks[0];
  }, [selectedTaskId, snapshot]);

  const selectedSubtitle = useMemo<SubtitleSegment | null>(() => {
    if (!snapshot) {
      return null;
    }
    return snapshot.timeline.subtitleSegments.find((item) => item.id === selectedSubtitleId) ?? null;
  }, [selectedSubtitleId, snapshot]);

  if (!snapshot || !selectedTask) {
    return <div className="boot-screen">StreamSense 工作台正在装入...</div>;
  }

  return (
    <AppShell
      snapshot={snapshot}
      activeTab={activeTab}
      selectedTask={selectedTask}
      selectedSubtitle={selectedSubtitle}
      onTabChange={setActiveTab}
      onTaskSelect={setSelectedTaskId}
      onSubtitleSelect={setSelectedSubtitleId}
    />
  );
}
