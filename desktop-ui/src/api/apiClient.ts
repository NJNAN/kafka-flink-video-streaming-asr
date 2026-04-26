import { mockSnapshot } from "../data/mockData";
import type { LogLine, ServiceStatus, TaskItem, WorkbenchSnapshot } from "../types";

const API_BASE = import.meta.env.VITE_STREAMSENSE_API_BASE ?? "http://localhost:8000";
const USE_MOCK = import.meta.env.VITE_USE_MOCK !== "false";

async function requestJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`);
  if (!response.ok) {
    throw new Error(`StreamSense API ${path} returned ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function fetchHealth() {
  if (USE_MOCK) {
    return { status: "ok", consumer_running: true };
  }
  return requestJson("/health");
}

export async function fetchServices(): Promise<ServiceStatus[]> {
  if (USE_MOCK) {
    return mockSnapshot.services;
  }
  const status = await requestJson<Record<string, string | number | boolean>>("/api/status");
  return [
    {
      name: "API",
      state: status.consumer_running ? "online" : "warning",
      headline: status.consumer_running ? "consumer running" : "consumer stopped",
      metrics: status
    }
  ];
}

export async function fetchTasks(): Promise<TaskItem[]> {
  if (USE_MOCK) {
    return mockSnapshot.tasks;
  }
  return requestJson("/api/tasks");
}

export async function fetchTranscripts() {
  if (USE_MOCK) {
    return mockSnapshot.timeline.subtitleSegments;
  }
  return requestJson("/api/transcripts?limit=100");
}

export async function fetchKeywords() {
  if (USE_MOCK) {
    return mockSnapshot.quality.hotwords;
  }
  return requestJson("/api/keywords?limit=100");
}

export async function fetchResults() {
  if (USE_MOCK) {
    return mockSnapshot.exports;
  }
  return requestJson("/api/results");
}

export async function fetchLogs(): Promise<LogLine[]> {
  if (USE_MOCK) {
    return mockSnapshot.logs;
  }
  return requestJson("/api/logs");
}

export async function fetchWorkbenchSnapshot(): Promise<WorkbenchSnapshot> {
  if (USE_MOCK) {
    await new Promise((resolve) => window.setTimeout(resolve, 220));
    return mockSnapshot;
  }

  const [services, tasks, transcripts, keywords, results, logs] = await Promise.all([
    fetchServices(),
    fetchTasks(),
    fetchTranscripts(),
    fetchKeywords(),
    fetchResults(),
    fetchLogs()
  ]);

  return {
    ...mockSnapshot,
    services,
    tasks,
    timeline: {
      ...mockSnapshot.timeline,
      subtitleSegments: transcripts as WorkbenchSnapshot["timeline"]["subtitleSegments"]
    },
    quality: {
      ...mockSnapshot.quality,
      hotwords: keywords as string[]
    },
    exports: results as WorkbenchSnapshot["exports"],
    logs
  };
}
