import { useEffect, useMemo, useState } from "react";

import JsonEditor from "../../components/JsonEditor";
import Modal from "../../components/Modal";
import SectionIntro from "../../components/SectionIntro";
import BrandSearchSelect from "../../components/BrandSearchSelect";
import {
  deleteBrand,
  getBrands,
  getLatestBrandAiKnowledge,
  uploadBrand,
  uploadDocuments,
} from "../../api/knowledgeBaseApi";
import type {
  ActivityItem,
  BrandDeleteResponse,
  BrandListItem,
  BrandUploadRequest,
  UploadTaskCreateResponse,
} from "../../types";

export type BrandsWorkspaceProps = {
  selectedBrandName: string;
  onSelectedBrandNameChange: (brandName: string) => void;
  onTaskCreated: (task: UploadTaskCreateResponse) => void;
  onViewTask: (taskId: string) => void;
  onActivity: (title: string, detail: string, tone?: ActivityItem["tone"]) => void;
};

const ATTACHMENT_ACCEPT = ".bmp,.csv,.doc,.docx,.epub,.gif,.htm,.html,.jpeg,.jpg,.json,.md,.mobi,.pdf,.png,.ppt,.pptx,.rtf,.txt,.webp,.xls,.xlsx";

const DELETE_COUNT_LABELS: Record<string, string> = {
  brands: "品牌",
  brand_products: "品牌产品",
  brand_knowledge_json: "品牌知识库记录",
  brand_attachment_assets: "品牌附件资产",
  brand_knowledge_sessions: "知识会话",
  brand_knowledge_session_rounds: "会话轮次",
  brand_knowledge_facts: "品牌事实",
  documents: "文档",
  document_registry: "文档登记记录",
  document_categories: "文档分类记录",
  document_summaries: "文档摘要",
  document_fact_relations: "文档事实关联",
  brand_full_knowledge_files: "完整知识库文件",
  brand_knowledge_ingestion_jobs: "知识库入库任务",
  background_jobs: "后台任务",
  upload_tasks: "上传任务",
  upload_task_files: "上传任务文件",
  upload_task_callbacks: "上传任务回调",
  ai_knowledge_oss_objects: "AI 知识库 OSS 文件",
  confirmed_knowledge_oss_objects: "确认知识库 OSS 文件",
  oss_objects: "OSS 文件",
};
const DELETE_SUMMARY_KEYS = new Set([
  "brands", "brand_products", "documents", "brand_knowledge_facts", "background_jobs", "upload_tasks", "oss_objects",
]);

function triggerDownload(url: string, filename: string): void {
  const link = document.createElement("a");
  link.href = url;
  link.download = filename || "品牌AI知识库.md";
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
}

export default function BrandsWorkspace(props: BrandsWorkspaceProps) {
  const {
    onSelectedBrandNameChange,
    onTaskCreated,
    onViewTask,
    onActivity,
    selectedBrandName,
  } = props;
  const [brands, setBrands] = useState<BrandListItem[]>([]);
  const [selectedBrandId, setSelectedBrandId] = useState("");
  const [loadingAction, setLoadingAction] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showDeleteModal, setShowDeleteModal] = useState(false);
  const [attachmentUploadTargetBrand, setAttachmentUploadTargetBrand] = useState<BrandListItem | null>(null);
  const [brandToDelete, setBrandToDelete] = useState<BrandListItem | null>(null);
  const [brandDeleteResult, setBrandDeleteResult] = useState<BrandDeleteResponse | null>(null);
  const [attachmentUploadFiles, setAttachmentUploadFiles] = useState<File[]>([]);
  const [attachmentUploadTask, setAttachmentUploadTask] = useState<UploadTaskCreateResponse | null>(null);
  const [attachmentUploadInputKey, setAttachmentUploadInputKey] = useState(0);
  const [brandPayload, setBrandPayload] = useState(`{
  "brand_name": "",
  "website": [],
  "enterprise_subject": "",
  "business_license_url": "",
  "intro": "",
  "attachments": []
}`);

  const selectedBrand = useMemo(
    () => brands.find((brand) => String(brand.id) === selectedBrandId) || null,
    [brands, selectedBrandId],
  );
  const orderedBrands = useMemo(() => {
    if (!selectedBrand) {
      return brands;
    }
    return [selectedBrand, ...brands.filter((brand) => brand.id !== selectedBrand.id)];
  }, [brands, selectedBrand]);

  async function loadBrands() {
    setLoadingAction("load-brands");
    try {
      const response = await getBrands();
      setBrands(response.brands);
      onActivity("品牌列表已加载", `${response.brands.length} 个品牌`, "success");
    } catch (error) {
      onActivity("读取品牌列表失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  useEffect(() => {
    void loadBrands();
  }, []);

  useEffect(() => {
    if (!selectedBrandName) {
      setSelectedBrandId("");
      return;
    }
    const matchedBrand = brands.find((brand) => brand.brand_name === selectedBrandName);
    if (matchedBrand) {
      setSelectedBrandId(String(matchedBrand.id));
    }
  }, [brands, selectedBrandName]);

  function handleSelectBrand(brand: BrandListItem | null) {
    setSelectedBrandId(brand ? String(brand.id) : "");
    if (!brand) {
      onSelectedBrandNameChange("");
      return;
    }
    if (!brands.some((item) => item.id === brand.id)) {
      setBrands((current) => [brand, ...current]);
    }
    onSelectedBrandNameChange(brand.brand_name);
    onActivity("选中品牌", brand.brand_name, "neutral");
  }

  async function handleCreateBrand() {
    setLoadingAction("create-brand");
    try {
      const payload = JSON.parse(brandPayload) as BrandUploadRequest;
      const response = await uploadBrand(payload);
      onTaskCreated(response);
      setShowCreateModal(false);
      await loadBrands();
      onActivity("品牌创建任务已提交", `${payload.brand_name} · task_id=${response.task_id}`, "success");
    } catch (error) {
      onActivity("创建品牌失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleConfirmDeleteBrand() {
    if (!brandToDelete) {
      return;
    }
    setLoadingAction("delete-brand");
    try {
      const response = await deleteBrand(brandToDelete.brand_name, true);
      setBrandDeleteResult(response);
      setShowDeleteModal(false);
      setBrandToDelete(null);
      await loadBrands();
      onActivity("品牌已删除", `${response.brand_name} · documents=${response.counts.documents}`, "warning");
      if (selectedBrandName === response.brand_name) {
        setSelectedBrandId("");
        onSelectedBrandNameChange("");
      }
    } catch (error) {
      onActivity("删除品牌失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleDownloadLatestKnowledge(brand: BrandListItem) {
    const brandCode = brand.brand_code?.trim();
    if (!brandCode) {
      onActivity("品牌知识库下载失败", `${brand.brand_name} 缺少 brand_code`, "warning");
      return;
    }
    const actionKey = `knowledge-download:${brand.id}`;
    setLoadingAction(actionKey);
    try {
      const response = await getLatestBrandAiKnowledge({ brandCode });
      const data = response.data;
      if (!data?.oss_url) {
        throw new Error(response.message || "品牌 AI 知识库 Markdown 不存在");
      }
      triggerDownload(data.oss_url, data.file_name || "品牌AI知识库.md");
      onActivity("品牌知识库开始下载", `${data.brand_name} · ${data.file_name}`, "success");
    } catch (error) {
      onActivity("品牌知识库下载失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleAttachmentUpload() {
    if (!attachmentUploadTargetBrand) {
      return;
    }
    const brandCode = attachmentUploadTargetBrand.brand_code?.trim();
    const brandName = attachmentUploadTargetBrand.brand_name.trim();
    if (!brandCode || !brandName) {
      onActivity("附件上传失败", "当前品牌缺少 brand_code 或品牌名称", "warning");
      return;
    }
    if (!attachmentUploadFiles.length) {
      onActivity("附件上传失败", "请先选择文件", "warning");
      return;
    }

    setLoadingAction("attachment-upload");
    setAttachmentUploadTask(null);
    try {
      const response = await uploadDocuments({
        files: attachmentUploadFiles,
        metadata: {
          brand_code: brandCode,
          brand_name: brandName,
          category: brandName,
        },
      });
      setAttachmentUploadTask(response);
      onTaskCreated(response);
      setAttachmentUploadFiles([]);
      setAttachmentUploadInputKey((current) => current + 1);
      onActivity(
        "附件上传任务已创建",
        `${brandName} · ${response.task_id} · ${response.file_count} 个文件`,
        "success",
      );
      await loadBrands();
    } catch (error) {
      onActivity("附件上传失败", error instanceof Error ? error.message : "未知错误", "warning");
    } finally {
      setLoadingAction(null);
    }
  }

  async function handleCopyTaskId(taskId: string) {
    try {
      await navigator.clipboard.writeText(taskId);
      onActivity("task_id 已复制", taskId, "success");
    } catch {
      onActivity("复制 task_id 失败", "当前浏览器不允许访问剪贴板，请手动复制。", "warning");
    }
  }

  return (
    <div className="workspace-grid">
      <section className="surface-panel">
        <SectionIntro
          eyebrow="Brands"
          title="品牌中心"
          description="先从品牌列表进入，再继续创建品牌、下载品牌知识库、上传附件，或删除品牌。"
        />
        <div className="toolbar-row">
          <BrandSearchSelect
            brands={brands}
            selectedBrand={selectedBrand}
            onSelect={handleSelectBrand}
            disabled={loadingAction === "load-brands"}
            loading={loadingAction === "load-brands"}
          />
          <button
            type="button"
            className="secondary-button"
            onClick={() => void loadBrands()}
            disabled={loadingAction === "load-brands"}
          >
            {loadingAction === "load-brands" ? "刷新中..." : "刷新品牌"}
          </button>
          <button
            type="button"
            onClick={() => {
              setBrandPayload(`{
  "brand_name": "",
  "website": [],
  "enterprise_subject": "",
  "business_license_url": "",
  "intro": "",
  "attachments": []
}`);
              setShowCreateModal(true);
            }}
          >
            创建品牌
          </button>
        </div>

        {brandDeleteResult ? (
          <section className="brand-delete-summary" aria-live="polite">
            <strong>{brandDeleteResult.executed ? "已删除品牌" : "品牌删除结果"}：{brandDeleteResult.brand_name}</strong>
            {brandDeleteResult.message ? <div>{brandDeleteResult.message}</div> : null}
            <div className="brand-delete-counts">
              {Object.entries(brandDeleteResult.counts).filter(([key]) => DELETE_SUMMARY_KEYS.has(key)).map(([key, count]) => (
                <span key={key}>{DELETE_COUNT_LABELS[key] || key}：{count}</span>
              ))}
            </div>
            <details>
              <summary>查看详细结果</summary>
              <div className="brand-delete-counts">
                {Object.entries(brandDeleteResult.counts).map(([key, count]) => (
                  <span key={key}>{DELETE_COUNT_LABELS[key] || key}：{count}</span>
                ))}
              </div>
              <pre className="code-block">{JSON.stringify(brandDeleteResult, null, 2)}</pre>
            </details>
          </section>
        ) : null}

        <div className="brand-list">
          {orderedBrands.length ? (
            orderedBrands.map((brand) => {
              const knowledgeDownloadAction = `knowledge-download:${brand.id}`;
              const hasBrandCode = Boolean(brand.brand_code?.trim());
              return (
                <div
                  key={brand.id}
                  className={`brand-row-card ${selectedBrandName === brand.brand_name ? "brand-row-card-active" : ""}`}
                >
                  <button
                    type="button"
                    className="brand-row-main"
                    onClick={() => handleSelectBrand(brand)}
                  >
                    <div className="brand-row-title">{brand.brand_name}</div>
                    <div className="brand-row-subline">
                      {brand.brand_alias || "无别名"} {brand.brand_code ? `· ${brand.brand_code}` : ""}
                    </div>
                    <div className="brand-row-subline">{JSON.stringify(brand.website ?? [])}</div>
                  </button>
                  <div className="brand-row-actions">
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => void handleDownloadLatestKnowledge(brand)}
                      disabled={!hasBrandCode || loadingAction === knowledgeDownloadAction}
                    >
                      {loadingAction === knowledgeDownloadAction ? "下载中..." : "品牌知识库"}
                    </button>
                    <button
                      type="button"
                      className="secondary-button"
                      onClick={() => {
                        setAttachmentUploadTargetBrand(brand);
                        setAttachmentUploadFiles([]);
                        setAttachmentUploadTask(null);
                        setAttachmentUploadInputKey((current) => current + 1);
                      }}
                      disabled={!hasBrandCode}
                    >
                      附件上传
                    </button>
                    <button
                      type="button"
                      className="danger-button"
                      onClick={() => {
                        setBrandToDelete(brand);
                        setShowDeleteModal(true);
                      }}
                    >
                      品牌删除
                    </button>
                  </div>
                </div>
              );
            })
          ) : (
            <div className="empty-state">当前没有查到品牌，试试刷新品牌或者直接创建品牌。</div>
          )}
        </div>

      </section>

      {showCreateModal ? (
        <Modal title="创建品牌" onClose={() => setShowCreateModal(false)}>
          <JsonEditor
            label="BrandUploadRequest JSON"
            value={brandPayload}
            onChange={setBrandPayload}
            rows={16}
          />
          <div className="inline-actions">
            <button type="button" onClick={() => void handleCreateBrand()} disabled={loadingAction === "create-brand"}>
              {loadingAction === "create-brand" ? "提交中..." : "创建品牌"}
            </button>
            <button type="button" className="secondary-button" onClick={() => setShowCreateModal(false)}>
              取消
            </button>
          </div>
        </Modal>
      ) : null}

      {showDeleteModal && brandToDelete ? (
        <Modal title="确认删除品牌" onClose={() => setShowDeleteModal(false)}>
          <p className="modal-copy">
            是否真的要删除品牌 <strong>{brandToDelete.brand_name}</strong> ？
          </p>
          <div className="inline-actions">
            <button
              type="button"
              className="danger-button"
              onClick={() => void handleConfirmDeleteBrand()}
              disabled={loadingAction === "delete-brand"}
            >
              {loadingAction === "delete-brand" ? "删除中..." : "确定"}
            </button>
            <button type="button" className="secondary-button" onClick={() => setShowDeleteModal(false)}>
              取消
            </button>
          </div>
        </Modal>
      ) : null}

      {attachmentUploadTargetBrand ? (
        <Modal
          title={`附件上传 · ${attachmentUploadTargetBrand.brand_name}`}
          onClose={() => setAttachmentUploadTargetBrand(null)}
        >
          <label className="field-block">
            <span>文件</span>
            <input
              key={attachmentUploadInputKey}
              type="file"
              accept={ATTACHMENT_ACCEPT}
              multiple
              onChange={(event) => {
                setAttachmentUploadFiles(Array.from(event.target.files || []));
              }}
              disabled={loadingAction === "attachment-upload"}
            />
            <div className="file-selection-text">
              {attachmentUploadFiles.length
                ? `已选择 ${attachmentUploadFiles.length} 个文件：${attachmentUploadFiles.map((file) => file.name).join("、")}`
                : "请选择附件或品牌 AI 知识库 Markdown。"}
            </div>
          </label>
          <div className="upload-format-note">
            <p>可上传品牌附件及品牌 AI 知识库 Markdown。常见格式包括 PDF、Word、Excel、图片和 Markdown。</p>
            <p>符合“【品牌名】品牌AI知识库_V版本号_YYYYMMDD.md”格式的文件会进入正式知识库处理流程，并进行版本校验；其他 Markdown 按附件处理。</p>
          </div>

          {attachmentUploadTask ? (
            <div className="result-panel">
              <div className="result-line">
                <strong>task_id：</strong>
                {attachmentUploadTask.task_id}
              </div>
              <div className="result-line">
                <strong>状态：</strong>
                {attachmentUploadTask.status} · {attachmentUploadTask.file_count} 个文件
              </div>
              <div className="result-line">
                <strong>说明：</strong>
                {attachmentUploadTask.message}
              </div>
              <div className="inline-actions">
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => onViewTask(attachmentUploadTask.task_id)}
                >
                  查看任务中心
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  onClick={() => void handleCopyTaskId(attachmentUploadTask.task_id)}
                >
                  复制 task_id
                </button>
              </div>
            </div>
          ) : null}

          <div className="inline-actions">
            <button
              type="button"
              onClick={() => void handleAttachmentUpload()}
              disabled={loadingAction === "attachment-upload" || attachmentUploadFiles.length === 0}
            >
              {loadingAction === "attachment-upload" ? "上传中..." : "上传文件"}
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => {
                setAttachmentUploadFiles([]);
                setAttachmentUploadInputKey((current) => current + 1);
              }}
              disabled={loadingAction === "attachment-upload" || attachmentUploadFiles.length === 0}
            >
              清空文件
            </button>
            <button
              type="button"
              className="secondary-button"
              onClick={() => setAttachmentUploadTargetBrand(null)}
            >
              关闭
            </button>
          </div>
        </Modal>
      ) : null}
    </div>
  );
}
