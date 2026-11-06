import type { NavigationKey } from "../types";

export type NavigationItem = {
  key: NavigationKey;
  label: string;
  description: string;
};

export const NAV_ITEMS: NavigationItem[] = [
  { key: "dashboard", label: "系统概览", description: "查看 API 健康、最近任务和操作记录" },
  { key: "brands", label: "品牌中心", description: "品牌列表、搜索、创建、删除与知识更新" },
  { key: "tasks", label: "任务中心", description: "查看后台任务、重试和执行状态" },
  { key: "search", label: "检索调试", description: "做语义搜索和分类 facts 调试" },
  { key: "sessions", label: "知识会话", description: "通过多轮会话整理品牌知识库" },
];
