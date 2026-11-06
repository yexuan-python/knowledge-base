import { useEffect, useMemo, useRef, useState } from "react";

import {
  getBrands,
  getUploadTaskStatus,
  startBrandKnowledgeSession,
  submitBrandAttachmentConflictResolutions,
  uploadDocuments,
} from "../../api/knowledgeBaseApi";
import BrandSearchSelect from "../../components/BrandSearchSelect";
import type {
  ActivityItem,
  BrandListItem,
  BrandKnowledgeConflictItem,
  BrandKnowledgeSessionResponse,
  ChatMessage,
  UploadTaskStatusResponse,
} from "../../types";

function createMessage(role: ChatMessage["role"], content: string): ChatMessage {
  return {
    id: `${role}_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
    role,
    content,
  };
}

function resolveSessionType(response: BrandKnowledgeSessionResponse): string {
  if (response.session_type?.trim()) {
    return response.session_type.trim();
  }
  if (response.session_kind === "attachment_conflict") {
    return "initial_generation";
  }
  return response.session_kind || "";
}

function formatSessionTypeLabel(sessionType: string): string {
  if (sessionType === "initial_generation") {
    return "第一次生成";
  }
  if (sessionType === "knowledge_iteration") {
    return "知识库迭代";
  }
  return sessionType || "未设置";
}

function wait(milliseconds: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, milliseconds);
  });
}

type ConflictChoice =
  | {
      mode: "choose_option";
      selectedOptionId: string;
    }
  | {
      mode: "keep_both";
    };

type SelectedConflictMap = Record<string, ConflictChoice>;
type ResolutionPayloadItem = {
  conflict_id: string;
  decision: string;
  selected_option_id?: string | null;
  final_content?: string | null;
};
type SessionMode = "initial_generation" | "knowledge_iteration";
type IterationMode = "attachments_only" | "attachments_with_instruction" | "instruction_only";

function buildResolutionSummary(conflicts: BrandKnowledgeConflictItem[], selectedOptions: SelectedConflictMap): string {
  const lines = ["本轮冲突决策："];
  conflicts.forEach((conflict, index) => {
    const selectedChoice = selectedOptions[conflict.conflict_id];
    if (!selectedChoice) {
      return;
    }
    if (selectedChoice.mode === "keep_both") {
      lines.push(`冲突${index + 1}（${conflict.topic}）：${conflict.options.length}个结果都保留`);
      return;
    }
    const selectedOption = conflict.options.find((option) => option.option_id === selectedChoice.selectedOptionId);
    if (!selectedOption) {
      return;
    }
    lines.push(`冲突${index + 1}（${conflict.topic}）：选择 ${selectedOption.option_id} - ${selectedOption.content}`);
  });
  return lines.join("\n");
}

function buildResolutions(
  conflicts: BrandKnowledgeConflictItem[],
  selectedOptions: SelectedConflictMap,
): ResolutionPayloadItem[] {
  return conflicts.flatMap<ResolutionPayloadItem>((conflict) => {
    const selectedChoice = selectedOptions[conflict.conflict_id];
    if (!selectedChoice) {
      return [];
    }
    if (selectedChoice.mode === "keep_both") {
      return [
        {
          conflict_id: conflict.conflict_id,
          decision: "keep_both",
          final_content: conflict.options.map((option) => `${option.option_id}. ${option.content}`).join("\n"),
        },
      ];
    }
    return [
      {
        conflict_id: conflict.conflict_id,
        decision: "choose_option",
        selected_option_id: selectedChoice.selectedOptionId,
      },
    ];
  });
}

export type BrandKnowledgeChatPageProps = {
  onActivity?: (title: string, detail: string, tone?: ActivityItem["tone"]) => void;
  onSessionChange?: (session: BrandKnowledgeSessionResponse | null) => void;
};

export default function BrandKnowledgeChatPage(props: BrandKnowledgeChatPageProps) {
  const { onActivity, onSessionChange } = props;
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([
    createMessage("assistant", "请选择会话类型和品牌。第一次生成会先做冲突扫描；知识库迭代会基于最新版知识库生成新版 Markdown。"),
  ]);
  const [sessionMode, setSessionMode] = useState<SessionMode>("initial_generation");
  const [iterationMode, setIterationMode] = useState<IterationMode>("attachments_only");
  const [updateInstruction, setUpdateInstruction] = useState("");
  const [brands, setBrands] = useState<BrandListItem[]>([]);
  const [selectedBrandId, setSelectedBrandId] = useState("");
  const [brandLoading, setBrandLoading] = useState(false);
  const [attachmentFiles, setAttachmentFiles] = useState<File[]>([]);
  const [loading, setLoading] = useState(false);
  const [statusText, setStatusText] = useState("未开始");
  const [uploadStatus, setUploadStatus] = useState<UploadTaskStatusResponse | null>(null);
  const [roundNo, setRoundNo] = useState(0);
  const [brandName, setBrandName] = useState("");
  const [sessionType, setSessionType] = useState("");
  const [finalMarkdown, setFinalMarkdown] = useState<string>("");
  const [finalFilename, setFinalFilename] = useState<string>("");
  const [sourceDocuments, setSourceDocuments] = useState<BrandKnowledgeSessionResponse["source_documents"]>([]);
  const [conflicts, setConflicts] = useState<BrandKnowledgeConflictItem[]>([]);
  const [selectedOptions, setSelectedOptions] = useState<SelectedConflictMap>({});
  const inputRef = useRef<HTMLInputElement | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const hasPendingConflicts = conflicts.length > 0;
  const selectedConflictCount = useMemo(
    () => conflicts.filter((conflict) => Boolean(selectedOptions[conflict.conflict_id])).length,
    [conflicts, selectedOptions],
  );
  const canSubmitResolutions = hasPendingConflicts && selectedConflictCount === conflicts.length && !loading;
  const selectedBrand = useMemo(
    () => brands.find((brand) => String(brand.id) === selectedBrandId) || null,
    [brands, selectedBrandId],
  );
  const canSend = useMemo(
    () => {
      const hasBrand = Boolean(selectedBrand?.brand_code?.trim()) && Boolean(selectedBrand?.brand_name?.trim());
      const needsAttachments =
        sessionMode === "initial_generation" ||
        iterationMode === "attachments_only" ||
        iterationMode === "attachments_with_instruction";
      const needsInstruction =
        sessionMode === "knowledge_iteration" &&
        (iterationMode === "attachments_with_instruction" || iterationMode === "instruction_only");
      return (
        hasBrand &&
        (!needsAttachments || attachmentFiles.length > 0) &&
        (!needsInstruction || Boolean(updateInstruction.trim())) &&
        !loading &&
        !hasPendingConflicts
      );
    },
    [sessionMode, iterationMode, selectedBrand, attachmentFiles.length, updateInstruction, loading, hasPendingConflicts],
  );

  useEffect(() => {
    let cancelled = false;

    async function loadBrandOptions() {
      setBrandLoading(true);
      try {
        const response = await getBrands();
        if (cancelled) {
          return;
        }
        setBrands(response.brands || []);
      } catch (error) {
        if (!cancelled) {
          const messageText = error instanceof Error ? error.message : "品牌列表加载失败";
          onActivity?.("品牌列表加载失败", messageText, "warning");
        }
      } finally {
        if (!cancelled) {
          setBrandLoading(false);
        }
      }
    }

    void loadBrandOptions();
    return () => {
      cancelled = true;
    };
  }, [onActivity]);

  useEffect(() => {
    setSelectedOptions((prev) => {
      if (!conflicts.length) {
        return {};
      }
      const next: SelectedConflictMap = {};
      conflicts.forEach((conflict) => {
        const selected = prev[conflict.conflict_id];
        if (!selected) {
          return;
        }
        if (selected.mode === "keep_both") {
          next[conflict.conflict_id] = selected;
          return;
        }
        if (conflict.options.some((option) => option.option_id === selected.selectedOptionId)) {
          next[conflict.conflict_id] = selected;
        }
      });
      return next;
    });
  }, [conflicts]);

  function syncSessionState(response: BrandKnowledgeSessionResponse) {
    setSessionId(response.session_id);
    setBrandName(response.brand_name);
    setSessionType(resolveSessionType(response));
    setStatusText(response.status);
    setRoundNo(response.round_no);
    setFinalMarkdown(response.final_markdown || "");
    setFinalFilename(response.final_filename || "");
    setSourceDocuments(response.source_documents || []);
    setConflicts(response.conflicts || []);
    onSessionChange?.(response);
  }

  async function waitForUploadTaskReady(taskId: string): Promise<UploadTaskStatusResponse> {
    const terminalStatuses = new Set(["completed", "completed_with_errors", "failed"]);
    let latestStatus: UploadTaskStatusResponse | null = null;
    for (let attempt = 0; attempt < 90; attempt += 1) {
      latestStatus = await getUploadTaskStatus(taskId);
      setUploadStatus(latestStatus);
      setStatusText(`附件解析：${latestStatus.status}`);
      if (terminalStatuses.has(latestStatus.status)) {
        return latestStatus;
      }
      await wait(2000);
    }
    throw new Error("附件解析等待超时，请稍后重试");
  }

  function handleDownloadMarkdown() {
    if (!finalMarkdown.trim()) {
      return;
    }
    const blob = new Blob([finalMarkdown], { type: "text/markdown;charset=utf-8" });
    const objectUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    const fallbackDate = new Date()
      .toLocaleDateString("zh-CN", {
        year: "2-digit",
        month: "2-digit",
        day: "2-digit",
      })
      .replace(/\//g, "");
    link.href = objectUrl;
    link.download = finalFilename || `【${brandName || "品牌"}】品牌AI知识库_V1_${fallbackDate}.md`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(objectUrl);
  }

  async function handleStartKnowledgeSession() {
    const brandCode = selectedBrand?.brand_code?.trim() || "";
    const brandNameInput = selectedBrand?.brand_name?.trim() || "";
    if (!brandCode || !brandNameInput || loading || hasPendingConflicts || !canSend) {
      return;
    }

    const needsAttachments =
      sessionMode === "initial_generation" ||
      iterationMode === "attachments_only" ||
      iterationMode === "attachments_with_instruction";
    const actionLabel =
      sessionMode === "initial_generation"
        ? "创建第一次生成会话"
        : `创建知识库迭代会话（${iterationMode}）`;
    setMessages((prev) => [
      ...prev,
      createMessage(
        "user",
        `${actionLabel}：${brandNameInput}（${brandCode}）${
          needsAttachments ? `，上传 ${attachmentFiles.length} 个附件` : ""
        }${updateInstruction.trim() ? `\n\n${updateInstruction.trim()}` : ""}`,
      ),
    ]);
    setLoading(true);
    setStatusText(needsAttachments ? "附件上传中" : "知识库迭代生成中");
    setUploadStatus(null);

    try {
      let taskId: string | undefined;
      if (needsAttachments) {
        const uploadResponse = await uploadDocuments({
          files: attachmentFiles,
          metadata: {
            brand_code: brandCode,
            brand_name: brandNameInput,
            category: brandNameInput,
            force_attachment: true,
          },
        });
        taskId = uploadResponse.task_id;
        onActivity?.(
          "附件上传任务已创建",
          `${brandNameInput} · ${uploadResponse.task_id} · ${uploadResponse.file_count} 个文件`,
          "success",
        );
        setStatusText("附件解析中");

        const completedUploadTask = await waitForUploadTaskReady(uploadResponse.task_id);
        const successfulFileCount = Number(completedUploadTask.success_count || 0);
        if (completedUploadTask.status === "failed" || successfulFileCount <= 0) {
          throw new Error(completedUploadTask.error_message || "附件解析失败，没有可用于生成知识库的成功文件");
        }
      }

      setStatusText(sessionMode === "initial_generation" ? "冲突扫描中" : "知识库迭代生成中");
      const response = await startBrandKnowledgeSession({
        sessionType: sessionMode,
        taskId,
        brandCode,
        brandName: brandNameInput,
        iterationMode: sessionMode === "knowledge_iteration" ? iterationMode : undefined,
        updateInstruction: updateInstruction.trim() || undefined,
      });

      syncSessionState(response);
      const hasWebArticleError = response.source_documents.some(
        (document) =>
          document.source_type === "web_article_error" ||
          document.source_role === "iteration_web_article_error",
      );
      const shouldKeepInputsForUrlFailure =
        sessionMode === "knowledge_iteration" &&
        response.status === "waiting_user_input" &&
        hasWebArticleError;
      if (!shouldKeepInputsForUrlFailure) {
        setAttachmentFiles([]);
        setUpdateInstruction("");
        if (fileInputRef.current) {
          fileInputRef.current.value = "";
        }
      }

      const assistantContent =
        response.assistant_message?.trim() ||
        response.final_markdown?.trim() ||
        "本轮已完成。";

      setMessages((prev) => [...prev, createMessage("assistant", assistantContent)]);
      const activityTitle =
        sessionMode === "initial_generation"
          ? "第一次生成会话已创建"
          : response.status === "waiting_user_input"
            ? "知识库迭代等待补充内容"
            : "知识库迭代已完成";
      onActivity?.(
        activityTitle,
        `${response.brand_name} · 状态 ${response.status} · 轮次 ${response.round_no}`,
        "success",
      );
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "请求失败";
      setMessages((prev) => [...prev, createMessage("assistant", `处理失败：${messageText}`)]);
      onActivity?.("知识会话失败", messageText, "warning");
    } finally {
      setLoading(false);
      window.setTimeout(() => {
        inputRef.current?.focus();
      }, 0);
    }
  }

  async function handleSubmitResolutions() {
    if (!sessionId || !canSubmitResolutions) {
      return;
    }

    const resolutions = buildResolutions(conflicts, selectedOptions);
    const resolutionSummary = buildResolutionSummary(conflicts, selectedOptions);

    setMessages((prev) => [...prev, createMessage("user", resolutionSummary)]);
    setLoading(true);

    try {
      const response = await submitBrandAttachmentConflictResolutions({
        sessionId,
        roundNo,
        resolutions,
      });

      syncSessionState(response);
      setSelectedOptions({});

      const assistantContent =
        response.assistant_message?.trim() ||
        response.final_markdown?.trim() ||
        "本轮已完成。";

      setMessages((prev) => [...prev, createMessage("assistant", assistantContent)]);
      onActivity?.(
        "知识冲突已提交",
        `${response.brand_name} · 状态 ${response.status} · 轮次 ${response.round_no}`,
        "success",
      );
    } catch (error) {
      const messageText = error instanceof Error ? error.message : "提交失败";
      setMessages((prev) => [...prev, createMessage("assistant", `提交失败：${messageText}`)]);
      onActivity?.("知识冲突提交失败", messageText, "warning");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="workspace-grid workspace-grid-session">
      <section className="surface-panel session-panel">
        <div className="panel-header">
          <div>
            <div className="eyebrow">Knowledge Session</div>
            <h2>品牌知识会话台</h2>
            <p>当前页面使用知识会话新入口：第一次生成先确认冲突；知识库迭代直接生成新版正式知识库。</p>
          </div>
          <div className="status-pills">
            <span className="status-pill">类型：{formatSessionTypeLabel(sessionType)}</span>
            <span className="status-pill">状态：{statusText}</span>
            <span className="status-pill">轮次：{roundNo}</span>
            {brandName ? <span className="status-pill">品牌：{brandName}</span> : null}
          </div>
        </div>

        <div className="messages messages-large">
          {messages.map((message) => (
            <div
              key={message.id}
              className={`message-row ${message.role === "user" ? "message-row-user" : "message-row-assistant"}`}
            >
              <div
                className={`message-bubble ${message.role === "user" ? "message-bubble-user" : "message-bubble-assistant"}`}
              >
                <div className="message-role">{message.role === "user" ? "你" : "知识助手"}</div>
                <div className="message-content">{message.content}</div>
              </div>
            </div>
          ))}
        </div>

        {hasPendingConflicts ? (
          <div className="surface-panel session-conflict-panel">
            <div className="panel-header session-conflict-header">
              <div>
                <div className="eyebrow">Conflict Review</div>
                <h2>本轮冲突确认</h2>
                <p>逐条选择处理方案，全部选完后再统一提交。</p>
              </div>
              <div className="status-pills">
                <span className="status-pill">
                  已选择：{selectedConflictCount}/{conflicts.length}
                </span>
              </div>
            </div>

            <div className="conflict-list">
              {conflicts.map((conflict, index) => (
                <div key={conflict.conflict_id} className="detail-card conflict-card">
                  <div className="detail-card-title">冲突 {index + 1}</div>
                  <div className="conflict-topic">{conflict.topic}</div>
                  {conflict.description ? (
                    <div className="conflict-description">{conflict.description}</div>
                  ) : null}
                  <div className="conflict-option-list">
                    {conflict.options.map((option) => {
                      const selectedChoice = selectedOptions[conflict.conflict_id];
                      const checked =
                        selectedChoice?.mode === "choose_option" &&
                        selectedChoice.selectedOptionId === option.option_id;
                      return (
                        <label
                          key={`${conflict.conflict_id}_${option.option_id}`}
                          className={`conflict-option ${checked ? "conflict-option-selected" : ""}`}
                        >
                          <input
                            type="radio"
                            name={`conflict_${conflict.conflict_id}`}
                            value={option.option_id}
                            checked={checked}
                            onChange={() => {
                              setSelectedOptions((prev) => ({
                                ...prev,
                                [conflict.conflict_id]: {
                                  mode: "choose_option",
                                  selectedOptionId: option.option_id,
                                },
                              }));
                            }}
                            disabled={loading}
                          />
                          <div className="conflict-option-body">
                            <div className="conflict-option-title">选项 {option.option_id}</div>
                            <div className="conflict-option-content">{option.content}</div>
                            <div className="conflict-option-meta">
                              来源：{option.source_files.join("、") || "未提供"}
                            </div>
                          </div>
                        </label>
                      );
                    })}

                    {conflict.options.length >= 2 ? (
                      <label
                        className={`conflict-option ${
                          selectedOptions[conflict.conflict_id]?.mode === "keep_both" ? "conflict-option-selected" : ""
                        }`}
                      >
                        <input
                          type="radio"
                          name={`conflict_${conflict.conflict_id}`}
                          value="keep_both"
                          checked={selectedOptions[conflict.conflict_id]?.mode === "keep_both"}
                          onChange={() => {
                            setSelectedOptions((prev) => ({
                              ...prev,
                              [conflict.conflict_id]: {
                                mode: "keep_both",
                              },
                            }));
                          }}
                          disabled={loading}
                        />
                        <div className="conflict-option-body">
                          <div className="conflict-option-title">同时保留</div>
                          <div className="conflict-option-content">
                            这个冲突的{conflict.options.length}个结果都保留，让后续知识库同时体现多种表述。
                          </div>
                          <div className="conflict-option-meta">提交时会以 `keep_both` 决策发送到后端。</div>
                        </div>
                      </label>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>

            <div className="conflict-submit-bar">
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setSelectedOptions({});
                }}
                disabled={loading || selectedConflictCount === 0}
              >
                清空本轮选择
              </button>
              <button type="button" onClick={() => void handleSubmitResolutions()} disabled={!canSubmitResolutions}>
                {loading ? "提交中..." : "提交本轮决策"}
              </button>
            </div>
          </div>
        ) : null}

        <div className="chat-input-bar dashboard-input-bar">
          <div className="session-create-form">
            <div className="two-up-row">
              <label className="field-block">
                <span>会话类型</span>
                <select
                  value={sessionMode}
                  onChange={(event) => setSessionMode(event.target.value as SessionMode)}
                  disabled={loading || hasPendingConflicts}
                >
                  <option value="initial_generation">第一次生成</option>
                  <option value="knowledge_iteration">知识库迭代</option>
                </select>
              </label>
              <div className="field-block">
                <label htmlFor="session-brand-name">品牌名称</label>
                <BrandSearchSelect
                  ref={inputRef}
                  inputId="session-brand-name"
                  brands={brands}
                  selectedBrand={selectedBrand}
                  onSelect={(brand) => {
                    setSelectedBrandId(brand ? String(brand.id) : "");
                    if (brand && !brands.some((item) => item.id === brand.id)) {
                      setBrands((current) => [brand, ...current]);
                    }
                  }}
                  disabled={loading || hasPendingConflicts || brandLoading}
                  loading={brandLoading}
                />
              </div>
            </div>

            {sessionMode === "knowledge_iteration" ? (
              <label className="field-block">
                <span>迭代模式</span>
                <select
                  value={iterationMode}
                  onChange={(event) => setIterationMode(event.target.value as IterationMode)}
                  disabled={loading || hasPendingConflicts}
                >
                  <option value="attachments_only">A：单文件/多附件补充</option>
                  <option value="attachments_with_instruction">B：附件 + 文字要求</option>
                  <option value="instruction_only">C：纯文字要求</option>
                </select>
              </label>
            ) : null}

            <label className="field-block">
              <span>附件</span>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                onChange={(event) => {
                  setAttachmentFiles(Array.from(event.target.files || []));
                }}
                disabled={loading || hasPendingConflicts || (sessionMode === "knowledge_iteration" && iterationMode === "instruction_only")}
              />
              <div className="file-selection-text">
                {attachmentFiles.length
                  ? `已选择 ${attachmentFiles.length} 个文件：${attachmentFiles.map((file) => file.name).join("、")}`
                  : sessionMode === "knowledge_iteration" && iterationMode === "instruction_only"
                    ? "C 模式不需要附件。"
                    : "请选择用于本轮会话的附件，支持多文件。"}
              </div>
            </label>

            {sessionMode === "knowledge_iteration" &&
            (iterationMode === "attachments_with_instruction" || iterationMode === "instruction_only") ? (
              <label className="field-block">
                <span>文字要求</span>
                <textarea
                  value={updateInstruction}
                  onChange={(event) => setUpdateInstruction(event.target.value)}
                  disabled={loading || hasPendingConflicts}
                  rows={4}
                  placeholder="例如：请把本次附件中的研学内容补充进最新版知识库，并保留原有酒店/温泉章节。"
                />
              </label>
            ) : null}

            {uploadStatus ? (
              <div className="muted-text">
                上传任务：{uploadStatus.status} · 成功 {uploadStatus.success_count}/{uploadStatus.file_count}
                {uploadStatus.failed_count ? ` · 失败 ${uploadStatus.failed_count}` : ""}
              </div>
            ) : null}

            <div className="inline-actions">
              <button type="button" onClick={() => void handleStartKnowledgeSession()} disabled={!canSend}>
                {loading
                  ? "处理中..."
                  : sessionMode === "initial_generation"
                    ? "上传附件并创建会话"
                    : iterationMode === "instruction_only"
                      ? "创建迭代会话"
                      : "上传附件并迭代"}
              </button>
              <button
                type="button"
                className="secondary-button"
                onClick={() => {
                  setAttachmentFiles([]);
                  if (fileInputRef.current) {
                    fileInputRef.current.value = "";
                  }
                }}
                disabled={loading || !attachmentFiles.length}
              >
                清空附件
              </button>
            </div>
          </div>
        </div>
      </section>

      <aside className="surface-panel session-side-panel">
        <div className="panel-header">
          <div>
            <div className="eyebrow">Preview</div>
            <h2>知识内容预览</h2>
          </div>
        </div>

        <div className="detail-list">
          <div className="detail-card">
            <div className="detail-card-title">当前 Session</div>
            <div className="detail-card-value selectable-text">{sessionId || "尚未创建"}</div>
          </div>

          <div className="detail-card">
            <div className="detail-card-title">来源文档</div>
            {sourceDocuments.length ? (
              <div className="source-document-list">
                {sourceDocuments.map((document) => (
                  <div key={document.document_id} className="source-document-item">
                    <strong>{document.original_filename}</strong>
                    <span>{document.document_id}</span>
                    {document.source_type === "web_article_error" ||
                    document.source_role === "iteration_web_article_error" ? (
                      <span className="warning-text">
                        {document.error_message || "链接内容提取失败，请复制链接内容到文字要求框"}
                      </span>
                    ) : null}
                    {document.source_url ? <span>{document.source_url}</span> : null}
                    {document.subcategory ? <span>子分类：{document.subcategory}</span> : null}
                  </div>
                ))}
              </div>
            ) : (
              <div className="muted-text">暂无来源文档</div>
            )}
          </div>

          <div className="detail-card">
            <div className="detail-card-title">最终知识库</div>
            {finalMarkdown ? (
              <div style={{ marginBottom: 12 }}>
                <button type="button" className="secondary-button" onClick={handleDownloadMarkdown}>
                  下载 Markdown
                </button>
              </div>
            ) : null}
            <pre className="code-block">{finalMarkdown || "当前会话尚未生成 final_markdown"}</pre>
          </div>
        </div>
      </aside>
    </div>
  );
}
