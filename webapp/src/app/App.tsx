import { useEffect, useMemo, useState } from "react";

import AppShell from "./AppShell";
import { API_BASE_URL, getHealth, getUploadTaskStatus } from "../api/knowledgeBaseApi";
import { createActivity } from "../lib/activity";
import DashboardPage from "../pages/DashboardPage";
import BrandsPage from "../pages/BrandsPage";
import SearchPage from "../pages/SearchPage";
import SessionsPage from "../pages/SessionsPage";
import TasksPage from "../pages/TasksPage";
import type {
  ActivityItem,
  BrandKnowledgeSessionResponse,
  DashboardMetrics,
  HealthResponse,
  NavigationKey,
  UploadTaskCreateResponse,
  UploadTaskStatusResponse,
} from "../types";

const ACTIVE_TASK_STATUSES = new Set(["queued", "processing"]);

export default function App() {
  const [activeNav, setActiveNav] = useState<NavigationKey>("dashboard");
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [lastTask, setLastTask] = useState<UploadTaskStatusResponse | null>(null);
  const [recentUploadTasks, setRecentUploadTasks] = useState<UploadTaskStatusResponse[]>([]);
  const [lastSession, setLastSession] = useState<BrandKnowledgeSessionResponse | null>(null);
  const [activities, setActivities] = useState<ActivityItem[]>([]);
  const [selectedBrandName, setSelectedBrandName] = useState("");
  const [taskSearchKeyword, setTaskSearchKeyword] = useState("");

  const apiBaseLabel = useMemo(() => API_BASE_URL || "同源代理 /api", []);
  const activeTaskIds = useMemo(
    () => recentUploadTasks
      .filter((task) => ACTIVE_TASK_STATUSES.has(task.status))
      .map((task) => task.task_id)
      .join("|"),
    [recentUploadTasks],
  );

  function addActivity(title: string, detail: string, tone: ActivityItem["tone"] = "neutral") {
    setActivities((prev) => [createActivity(title, detail, tone), ...prev].slice(0, 14));
  }

  async function refreshHealth() {
    try {
      const response = await getHealth();
      setHealth(response);
      addActivity("健康检查成功", `status=${response.status} · collection=${response.collection_name}`, "success");
    } catch (error) {
      addActivity("健康检查失败", error instanceof Error ? error.message : "未知错误", "warning");
    }
  }

  useEffect(() => {
    void refreshHealth();
  }, []);

  function upsertUploadTask(task: UploadTaskStatusResponse) {
    setLastTask(task);
    setRecentUploadTasks((prev) => [task, ...prev.filter((item) => item.task_id !== task.task_id)].slice(0, 10));
  }

  useEffect(() => {
    if (!activeTaskIds) {
      return;
    }
    const pollingTaskIds = activeTaskIds.split("|").filter(Boolean);

    let cancelled = false;
    let timerId: number | undefined;

    async function pollTaskStatus() {
      try {
        const latestTasks = await Promise.all(pollingTaskIds.map((taskId) => getUploadTaskStatus(taskId)));
        if (cancelled) {
          return;
        }
        latestTasks.forEach(upsertUploadTask);
        if (latestTasks.some((task) => ACTIVE_TASK_STATUSES.has(task.status))) {
          timerId = window.setTimeout(() => void pollTaskStatus(), 3000);
        }
      } catch {
        if (!cancelled) {
          timerId = window.setTimeout(() => void pollTaskStatus(), 5000);
        }
      }
    }

    timerId = window.setTimeout(() => void pollTaskStatus(), 3000);
    return () => {
      cancelled = true;
      if (timerId !== undefined) {
        window.clearTimeout(timerId);
      }
    };
  }, [activeTaskIds]);

  function handleTaskCreated(task: UploadTaskCreateResponse) {
    addActivity("上传任务已创建", `${task.task_id} · ${task.message}`, "success");
  }

  async function handleTaskCreatedWithPolling(task: UploadTaskCreateResponse) {
    handleTaskCreated(task);
    try {
      const latestTask = await getUploadTaskStatus(task.task_id);
      upsertUploadTask(latestTask);
    } catch {
      // Ignore polling failure in UI bootstrap flow.
    }
  }

  function handleSessionChange(session: BrandKnowledgeSessionResponse | null) {
    setLastSession(session);
  }

  function handleViewTask(taskId: string) {
    const normalizedTaskId = taskId.trim();
    if (!normalizedTaskId) {
      return;
    }
    setTaskSearchKeyword(normalizedTaskId);
    setActiveNav("tasks");
    addActivity("已打开任务中心", `搜索 task_id=${normalizedTaskId}`, "neutral");
  }

  const dashboardMetrics: DashboardMetrics = {
    apiBaseUrl: apiBaseLabel,
    health,
    lastTask,
    lastSession,
    recentActivities: activities,
  };

  return (
    <AppShell
      activeNav={activeNav}
      apiBaseLabel={apiBaseLabel}
      healthStatus={health?.status || null}
      selectedBrandName={selectedBrandName}
      onNavChange={setActiveNav}
    >
      {activeNav === "dashboard" ? (
        <DashboardPage metrics={dashboardMetrics} onRefreshHealth={refreshHealth} />
      ) : null}

      {activeNav === "brands" ? (
        <BrandsPage
          selectedBrandName={selectedBrandName}
          onSelectedBrandNameChange={setSelectedBrandName}
          onTaskCreated={(task) => {
            void handleTaskCreatedWithPolling(task);
          }}
          onViewTask={handleViewTask}
          onActivity={addActivity}
        />
      ) : null}

      {activeNav === "tasks" ? (
        <TasksPage initialKeyword={taskSearchKeyword} onActivity={addActivity} />
      ) : null}

      {activeNav === "search" ? <SearchPage onActivity={addActivity} /> : null}

      {activeNav === "sessions" ? (
        <SessionsPage onActivity={addActivity} onSessionChange={handleSessionChange} />
      ) : null}
    </AppShell>
  );
}
