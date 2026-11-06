import type { UploadTaskStatusResponse } from "./documents";
import type { BrandKnowledgeSessionResponse } from "./sessions";
import type { HealthResponse } from "./system";

export type ChatRole = "assistant" | "user";

export type NavigationKey =
  | "dashboard"
  | "brands"
  | "tasks"
  | "search"
  | "sessions";

export type ChatOption = {
  label: string;
  value: string;
};

export type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
  options?: ChatOption[];
};

export type ActivityItem = {
  id: string;
  title: string;
  detail: string;
  tone: "neutral" | "success" | "warning";
  createdAt: string;
};

export type DashboardMetrics = {
  health?: HealthResponse | null;
  apiBaseUrl: string;
  lastTask?: UploadTaskStatusResponse | null;
  lastSession?: BrandKnowledgeSessionResponse | null;
  recentActivities: ActivityItem[];
};
