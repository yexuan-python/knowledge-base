import { useEffect, useState } from "react";

import { getBackgroundJobs } from "../api/knowledgeBaseApi";
import SectionIntro from "../components/SectionIntro";
import type { ActivityItem, BackgroundJob } from "../types";

const ACTIVE_JOB_STATUSES = new Set(["waiting", "processing", "retrying"]);
const PAGE_SIZE = 50;

type JobStatusFilter = "all" | "waiting" | "processing" | "success" | "failed" | "other";

const JOB_STATUS_FILTERS: Array<{
  key: JobStatusFilter;
  label: string;
}> = [
  { key: "all", label: "全部" },
  { key: "waiting", label: "等待" },
  { key: "processing", label: "进行" },
  { key: "success", label: "成功" },
  { key: "failed", label: "失败" },
  { key: "other", label: "其他" },
];

const JOB_TYPE_LABELS: Record<string, string> = {
  upload_task_process: "上传任务处理",
  brand_full_knowledge_refresh: "品牌知识库刷新",
  brand_knowledge_update_full_generation: "品牌知识更新",
  attachment_confirm_pipeline: "附件确认处理",
  attachment_confirm_full_generation: "附件确认生成",
  attachment_conflict_resolution: "附件冲突处理",
};

const STATUS_LABELS: Record<string, string> = {
  waiting: "等待",
  retrying: "等待重试",
  processing: "进行中",
  success: "成功",
  failed: "失败",
  queued: "排队中",
  pending: "等待",
  completed: "完成",
  partial_success: "部分成功",
};

function buildStatusCounts(total: number, rawCounts: Record<string, number>): Record<JobStatusFilter, number> {
  const waiting = Number(rawCounts.waiting || 0) + Number(rawCounts.retrying || 0);
  const processing = Number(rawCounts.processing || 0);
  const success = Number(rawCounts.success || 0);
  const failed = Number(rawCounts.failed || 0);
  return {
    all: total,
    waiting,
    processing,
    success,
    failed,
    other: Math.max(0, total - waiting - processing - success - failed),
  };
}

function labelJobType(jobType: string): string {
  return JOB_TYPE_LABELS[jobType] || jobType;
}

function labelStatus(status: string): string {
  return STATUS_LABELS[status] || status;
}

function getJobTone(job: BackgroundJob): ActivityItem["tone"] {
  if (job.status === "failed" || hasUploadTaskFailure(job)) {
    return "warning";
  }
  if (job.status === "success") {
    return "success";
  }
  return "neutral";
}

function resolveUploadTaskId(job: BackgroundJob): string {
  const taskId = job.upload_task?.task_id?.trim();
  if (taskId) {
    return taskId;
  }
  const payloadTaskId = typeof job.payload.task_id === "string" ? job.payload.task_id.trim() : "";
  const sourceTaskId = typeof job.payload.source_task_id === "string" ? job.payload.source_task_id.trim() : "";
  return payloadTaskId || sourceTaskId;
}

function hasUploadTaskFailure(job: BackgroundJob): boolean {
  return Boolean(
    job.upload_task &&
      (job.upload_task.status === "failed" ||
        job.upload_task.failed_count > 0 ||
        job.upload_task.files.some((file) => file.status === "failed")),
  );
}

function getFailureReasons(job: BackgroundJob): string[] {
  const reasons = [job.last_error_message, job.upload_task?.error_message]
    .map((message) => message?.trim())
    .filter((message): message is string => Boolean(message));

  for (const file of job.upload_task?.files || []) {
    if (file.status !== "failed") {
      continue;
    }
    reasons.push(file.error_message?.trim() || `${file.file_name || "未命名文件"} 处理失败`);
  }

  return [...new Set(reasons)];
}

function resolveJobBrand(job: BackgroundJob): string {
  const uploadTaskBrandName = job.upload_task?.brand_name?.trim() || "";
  const uploadTaskBrandCode = job.upload_task?.brand_code?.trim() || "";
  if (uploadTaskBrandName && uploadTaskBrandCode) {
    return `${uploadTaskBrandName} · ${uploadTaskBrandCode}`;
  }
  if (uploadTaskBrandName || uploadTaskBrandCode) {
    return uploadTaskBrandName || uploadTaskBrandCode;
  }
  const brandName = typeof job.payload.brand_name === "string" ? job.payload.brand_name.trim() : "";
  const brandCode = typeof job.payload.brand_code === "string" ? job.payload.brand_code.trim() : "";
  if (brandName && brandCode) {
    return `${brandName} · ${brandCode}`;
  }
  return brandName || brandCode || "未识别品牌";
}

function resolveJobSource(job: BackgroundJob): string {
  const taskId = typeof job.payload.task_id === "string" ? job.payload.task_id.trim() : "";
  const sourceTaskId = typeof job.payload.source_task_id === "string" ? job.payload.source_task_id.trim() : "";
  return [job.source_type, job.source_id, taskId || sourceTaskId].filter(Boolean).join(" · ") || "无来源信息";
}

function resolveUploadTaskProgress(job: BackgroundJob): string | null {
  const uploadTask = job.upload_task;
  if (!uploadTask) {
    return null;
  }
  return [
    `上传任务 ${labelStatus(uploadTask.status)}`,
    `${uploadTask.file_count} 个文件`,
    `成功 ${uploadTask.success_count}`,
    `失败 ${uploadTask.failed_count}`,
    `处理中 ${uploadTask.processing_count}`,
    `等待 ${uploadTask.pending_count}`,
  ].join(" · ");
}

type TasksPageProps = {
  initialKeyword?: string;
  onActivity: (title: string, detail: string, tone?: ActivityItem["tone"]) => void;
};

export default function TasksPage(props: TasksPageProps) {
  const { initialKeyword = "", onActivity } = props;
  const [jobs, setJobs] = useState<BackgroundJob[]>([]);
  const [statusCounts, setStatusCounts] = useState<Record<JobStatusFilter, number>>({
    all: 0,
    waiting: 0,
    processing: 0,
    success: 0,
    failed: 0,
    other: 0,
  });
  const [total, setTotal] = useState(0);
  const [refreshing, setRefreshing] = useState(false);
  const [statusFilter, setStatusFilter] = useState<JobStatusFilter>("all");
  const [currentPage, setCurrentPage] = useState(1);
  const [keywordInput, setKeywordInput] = useState(initialKeyword);
  const [keyword, setKeyword] = useState(initialKeyword.trim());
  const [copiedIdentifier, setCopiedIdentifier] = useState("");

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const pageStart = total ? (currentPage - 1) * PAGE_SIZE + 1 : 0;
  const pageEnd = Math.min(currentPage * PAGE_SIZE, total);

  async function loadJobs(params?: { page?: number; silent?: boolean }) {
    const page = params?.page ?? currentPage;
    const offset = (page - 1) * PAGE_SIZE;
    setRefreshing(true);
    try {
      const response = await getBackgroundJobs({
        limit: PAGE_SIZE,
        offset,
        status: statusFilter,
        keyword,
      });
      const nextTotalPages = Math.max(1, Math.ceil(response.total / PAGE_SIZE));
      if (page > nextTotalPages) {
        setCurrentPage(nextTotalPages);
        return;
      }
      setJobs(response.jobs);
      setTotal(response.total);
      setStatusCounts(buildStatusCounts(response.status_counts.all ?? response.total, response.status_counts));
      if (!params?.silent) {
        onActivity(
          "后台任务列表已刷新",
          `第 ${page}/${nextTotalPages} 页，显示 ${response.jobs.length} 条任务`,
          "success",
        );
      }
    } catch (error) {
      onActivity("后台任务列表刷新失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setRefreshing(false);
    }
  }

  useEffect(() => {
    void loadJobs({ silent: true });
  }, [statusFilter, currentPage, keyword]);

  useEffect(() => {
    if (!jobs.some((job) => ACTIVE_JOB_STATUSES.has(job.status))) {
      return;
    }
    const timerId = window.setTimeout(() => {
      void loadJobs({ silent: true });
    }, 3000);
    return () => window.clearTimeout(timerId);
  }, [jobs, statusFilter, currentPage, keyword]);

  useEffect(() => {
    const normalizedInitialKeyword = initialKeyword.trim();
    setKeywordInput(normalizedInitialKeyword);
    setKeyword(normalizedInitialKeyword);
    setCurrentPage(1);
  }, [initialKeyword]);

  function selectStatusFilter(nextFilter: JobStatusFilter) {
    setStatusFilter(nextFilter);
    setCurrentPage(1);
  }

  function goToPage(page: number) {
    setCurrentPage(Math.min(Math.max(page, 1), totalPages));
  }

  function applyKeywordSearch() {
    setKeyword(keywordInput.trim());
    setCurrentPage(1);
  }

  function clearKeywordSearch() {
    setKeywordInput("");
    setKeyword("");
    setCurrentPage(1);
  }

  async function copyIdentifier(label: string, value: string, options?: { key: string; activityDetail: string }) {
    const normalizedValue = value.trim();
    if (!normalizedValue) {
      return;
    }
    const copiedKey = options?.key || `${label}:${normalizedValue}`;
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("当前浏览器不支持剪贴板访问");
      }
      await navigator.clipboard.writeText(normalizedValue);
      setCopiedIdentifier(copiedKey);
      window.setTimeout(() => {
        setCopiedIdentifier((current) => (current === copiedKey ? "" : current));
      }, 1600);
      onActivity(`已复制 ${label}`, options?.activityDetail || normalizedValue, "success");
    } catch (error) {
      const failedKey = `failed:${copiedKey}`;
      setCopiedIdentifier(failedKey);
      window.setTimeout(() => {
        setCopiedIdentifier((current) => (current === failedKey ? "" : current));
      }, 3000);
      onActivity(`复制 ${label} 失败`, error instanceof Error ? error.message : "未知错误", "warning");
    }
  }

  return (
    <div className="workspace-grid">
      <section className="surface-panel">
        <SectionIntro
          eyebrow="Jobs"
          title="任务中心"
          description="查看 background_jobs 表里的后台任务，包括上传任务消费、知识库生成、附件确认和重试状态。"
        />
        <div className="toolbar-row">
          <input
            value={keywordInput}
            onChange={(event) => setKeywordInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                applyKeywordSearch();
              }
            }}
            placeholder="搜索 job_id / task_id / 品牌 / 文件名"
          />
          <button type="button" onClick={applyKeywordSearch} disabled={refreshing}>
            搜索任务
          </button>
          {keyword ? (
            <button type="button" className="secondary-button" onClick={clearKeywordSearch} disabled={refreshing}>
              清空搜索
            </button>
          ) : null}
          <button
            type="button"
            className="secondary-button"
            onClick={() => void loadJobs()}
            disabled={refreshing}
          >
            {refreshing ? "刷新中..." : "刷新任务"}
          </button>
        </div>
        <div className="segmented-filter" aria-label="任务状态筛选">
          {JOB_STATUS_FILTERS.map((filter) => (
            <button
              key={filter.key}
              type="button"
              className={`segmented-filter-button ${statusFilter === filter.key ? "segmented-filter-button-active" : ""}`}
              onClick={() => selectStatusFilter(filter.key)}
            >
              {filter.label}
              <span>{statusCounts[filter.key]}</span>
            </button>
          ))}
        </div>
        <div className="muted-text" style={{ marginTop: 12 }}>
          第 {currentPage}/{totalPages} 页，显示 {pageStart}-{pageEnd} / {total} 条
          {statusFilter === "all" ? "全部任务" : "当前筛选任务"}
          {keyword ? ` · 搜索：${keyword}` : ""}
        </div>
        <div className="activity-list" style={{ marginTop: 16 }}>
          {jobs.length ? (
            jobs.map((job) => {
              const isActive = ACTIVE_JOB_STATUSES.has(job.status);
              const taskId = resolveUploadTaskId(job);
              const failureReasons = getFailureReasons(job);
              const hasFailure = job.status === "failed" || hasUploadTaskFailure(job) || failureReasons.length > 0;
              return (
                <article
                  key={job.job_id}
                  className={`activity-item task-job-card activity-${getJobTone(job)} ${hasFailure ? "task-job-card-failed" : ""}`}
                >
                  <div className="activity-head">
                    <strong>
                      {labelJobType(job.job_type)} · {labelStatus(job.status)}
                    </strong>
                    <span>{isActive ? "运行中" : job.updated_at || job.created_at || "-"}</span>
                  </div>
                  <div className="task-identifier-row">
                    <span>Job ID</span>
                    <code className="selectable-text">{job.job_id}</code>
                    <button
                      type="button"
                      className="task-copy-button"
                      onClick={() => void copyIdentifier("job_id", job.job_id)}
                      aria-label="复制 job_id"
                    >
                      {copiedIdentifier === `job_id:${job.job_id}` ? "已复制" : copiedIdentifier === `failed:job_id:${job.job_id}` ? "复制失败" : "复制"}
                    </button>
                  </div>
                  {taskId ? (
                    <div className="task-identifier-row">
                      <span>Task ID</span>
                      <code className="selectable-text">{taskId}</code>
                      <button
                        type="button"
                        className="task-copy-button"
                        onClick={() => void copyIdentifier("task_id", taskId)}
                        aria-label="复制 task_id"
                      >
                        {copiedIdentifier === `task_id:${taskId}` ? "已复制" : copiedIdentifier === `failed:task_id:${taskId}` ? "复制失败" : "复制"}
                      </button>
                    </div>
                  ) : null}
                  {hasFailure ? (
                    <div className="task-failure-summary" role="status">
                      <strong>失败原因</strong>
                      <span>{failureReasons[0] || "当前任务有失败记录，请展开查看处理详情。"}</span>
                      {failureReasons.length > 1 ? <small>另有 {failureReasons.length - 1} 条失败信息</small> : null}
                      {failureReasons.length ? (
                        <button
                          type="button"
                          className="task-copy-button task-copy-error"
                          onClick={() => void copyIdentifier("错误信息", failureReasons.join("\n\n"), {
                            key: `error:${job.job_id}`,
                            activityDetail: `job_id=${job.job_id}`,
                          })}
                          aria-label={`复制任务 ${job.job_id} 的全部错误信息`}
                        >
                          {copiedIdentifier === `error:${job.job_id}` ? "已复制" : copiedIdentifier === `failed:error:${job.job_id}` ? "复制失败" : "复制错误"}
                        </button>
                      ) : null}
                      {copiedIdentifier === `failed:error:${job.job_id}` ? (
                        <small>无法访问剪贴板，请展开详情手动复制。</small>
                      ) : null}
                    </div>
                  ) : null}
                  <details className="task-details">
                    <summary>查看任务详情</summary>
                    <div className="task-details-content">
                      <div className="activity-detail">
                        {resolveJobBrand(job)} · {resolveJobSource(job)}
                      </div>
                      {resolveUploadTaskProgress(job) ? (
                        <div className="activity-detail">{resolveUploadTaskProgress(job)}</div>
                      ) : null}
                      <div className="activity-detail">
                        优先级 {job.priority} · 重试 {job.retry_count}/{job.max_retries}
                        {job.next_retry_at ? ` · 下次重试 ${job.next_retry_at}` : ""}
                        {job.locked_by ? ` · worker ${job.locked_by}` : ""}
                      </div>
                      {failureReasons.length ? (
                        <div className="task-error-list">
                          <strong>原始错误信息</strong>
                          {failureReasons.map((reason) => (
                            <div key={reason} className="activity-detail warning-text selectable-text">
                              {reason}
                            </div>
                          ))}
                        </div>
                      ) : null}
                      {job.upload_task?.files.length ? (
                        <div className="task-file-list">
                          <strong>文件处理明细（{job.upload_task.files.length}）</strong>
                          {job.upload_task.files.map((file) => (
                            <div key={file.file_id || `${job.job_id}:${file.file_index}`} className="task-file-item">
                              <div className="task-file-head">
                                <strong>{file.file_name || "未命名文件"}</strong>
                                <span>{labelStatus(file.status)}</span>
                              </div>
                              <div className="activity-detail">
                                {file.file_role || "未识别类型"}
                                {file.document_id ? ` · document ${file.document_id}` : ""}
                                {file.asset_id ? ` · asset ${file.asset_id}` : ""}
                                {file.full_knowledge_file_id ? ` · knowledge ${file.full_knowledge_file_id}` : ""}
                              </div>
                              {file.error_message ? (
                                <div className="activity-detail warning-text selectable-text">{file.error_message}</div>
                              ) : null}
                            </div>
                          ))}
                        </div>
                      ) : taskId ? (
                        <div className="activity-detail muted-text">关联上传任务暂未记录文件处理明细。</div>
                      ) : null}
                    </div>
                  </details>
                </article>
              );
            })
          ) : (
            <div className="empty-state">
              {total ? "当前筛选下没有任务。" : "还没有后台任务记录，或当前服务暂未返回 background_jobs 列表。"}
            </div>
          )}
        </div>
        {totalPages > 1 ? (
          <div className="pagination-row">
            <button
              type="button"
              className="secondary-button"
              onClick={() => goToPage(currentPage - 1)}
              disabled={refreshing || currentPage <= 1}
            >
              上一页
            </button>
            <span className="muted-text">
              第 {currentPage} 页 / 共 {totalPages} 页
            </span>
            <button
              type="button"
              className="secondary-button"
              onClick={() => goToPage(currentPage + 1)}
              disabled={refreshing || currentPage >= totalPages}
            >
              下一页
            </button>
          </div>
        ) : null}
      </section>
    </div>
  );
}
