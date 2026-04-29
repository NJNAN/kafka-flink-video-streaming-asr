/// <reference types="vite/client" />

interface Window {
  streamsenseLive?: {
    startServices: () => Promise<{ ok: boolean; data?: unknown; error?: string; logs?: string[] }>;
    stopServices: () => Promise<{ ok: boolean; data?: unknown; error?: string; logs?: string[] }>;
    health: () => Promise<{ ok: boolean; data?: unknown; error?: string; logs?: string[] }>;
    getLogs: () => Promise<{ ok: boolean; data?: string[]; error?: string; logs?: string[] }>;
    openMicrophoneSettings: () => Promise<{ ok: boolean; data?: unknown; error?: string; logs?: string[] }>;
    openCameraSettings: () => Promise<{ ok: boolean; data?: unknown; error?: string; logs?: string[] }>;
    onLogLine: (callback: (line: string) => void) => () => void;
  };
}
