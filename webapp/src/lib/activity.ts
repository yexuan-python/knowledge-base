import type { ActivityItem } from "../types";

export function nowLabel(): string {
  return new Date().toLocaleString("zh-CN", { hour12: false });
}

export function createActivity(
  title: string,
  detail: string,
  tone: ActivityItem["tone"] = "neutral",
): ActivityItem {
  return {
    id: `${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    title,
    detail,
    tone,
    createdAt: nowLabel(),
  };
}
