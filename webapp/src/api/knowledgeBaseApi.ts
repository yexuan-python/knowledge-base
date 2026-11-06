import type {
  AttachmentConfirmResultResponse,
  AttachmentConfirmSaveRequest,
  AttachmentConfirmSaveResponse,
  AttachmentPreviewParseRequest,
  AttachmentPreviewParseResponse,
  AttachmentReviewChangesRequest,
  AttachmentReviewChangesResponse,
  BrandFactsResponse,
  BrandDeleteResponse,
  BrandLatestAiKnowledgeResponse,
  BrandKnowledgeLatestSessionResponse,
  BrandKnowledgeSessionResponse,
  BrandListResponse,
  BrandUploadRequest,
  BackgroundJobListResponse,
  HealthResponse,
  KnowledgeUpdateRequest,
  SearchResponse,
  UploadTaskCreateResponse,
  UploadTaskStatusResponse,
} from "../types";

const configuredBaseUrl = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.trim();
export const API_BASE_URL = configuredBaseUrl || "";

function buildUrl(path: string): string {
  if (!API_BASE_URL) {
    return path;
  }
  return `${API_BASE_URL}${path}`;
}

async function parseResponse<T>(response: Response): Promise<T> {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail =
      typeof payload?.detail === "string"
        ? payload.detail
        : typeof payload?.message === "string"
          ? payload.message
        : `请求失败（HTTP ${response.status}）`;
    throw new Error(detail);
  }
  return payload as T;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(buildUrl(path), init);
  return parseResponse<T>(response);
}

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>("/api/v1/health");
}

export async function getBackgroundJobs(params?: {
  limit?: number;
  offset?: number;
  status?: string;
  keyword?: string;
}): Promise<BackgroundJobListResponse> {
  const query = new URLSearchParams({
    limit: String(params?.limit ?? 50),
    offset: String(params?.offset ?? 0),
    status: params?.status || "all",
  });
  if (params?.keyword?.trim()) {
    query.set("keyword", params.keyword.trim());
  }
  return requestJson<BackgroundJobListResponse>(`/api/v1/background-jobs?${query.toString()}`);
}

export async function getBrands(keyword?: string): Promise<BrandListResponse> {
  const url = keyword?.trim()
    ? `/api/v1/brands?keyword=${encodeURIComponent(keyword.trim())}`
    : "/api/v1/brands";
  return requestJson<BrandListResponse>(url);
}

export async function getLatestBrandAiKnowledge(params: {
  brandCode: string;
}): Promise<BrandLatestAiKnowledgeResponse> {
  return requestJson<BrandLatestAiKnowledgeResponse>("/api/v1/brands/ai-knowledge/latest", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      brand_code: params.brandCode,
    }),
  });
}

export async function uploadDocuments(params: {
  files: File[];
  metadata?: Record<string, unknown>;
  chunkSize?: number;
  chunkOverlap?: number;
}): Promise<UploadTaskCreateResponse> {
  const formData = new FormData();
  params.files.forEach((file) => {
    formData.append("files", file);
  });
  if (params.metadata && Object.keys(params.metadata).length > 0) {
    formData.append("metadata", JSON.stringify(params.metadata));
  }
  if (typeof params.chunkSize === "number") {
    formData.append("chunk_size", String(params.chunkSize));
  }
  if (typeof params.chunkOverlap === "number") {
    formData.append("chunk_overlap", String(params.chunkOverlap));
  }

  return requestJson<UploadTaskCreateResponse>("/api/v1/documents/upload", {
    method: "POST",
    body: formData,
  });
}

export async function getUploadTaskStatus(taskId: string): Promise<UploadTaskStatusResponse> {
  return requestJson<UploadTaskStatusResponse>("/api/v1/documents/upload-tasks", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      task_id: taskId,
    }),
  });
}

export async function searchDocuments(params: {
  query: string;
  topK?: number;
  documentIds?: string[];
  sourceTypes?: string[];
  brandName?: string;
  category?: string;
  subcategory?: string;
}): Promise<SearchResponse> {
  return requestJson<SearchResponse>("/api/v1/search", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      query: params.query,
      top_k: params.topK ?? 5,
      document_ids: params.documentIds?.length ? params.documentIds : undefined,
      source_types: params.sourceTypes?.length ? params.sourceTypes : undefined,
      brand_name: params.brandName || params.category || undefined,
      category: params.category || undefined,
      subcategory: params.subcategory || undefined,
    }),
  });
}

export async function searchBrandFacts(params: {
  brandName: string;
  query?: string;
  topK?: number;
}): Promise<BrandFactsResponse> {
  return requestJson<BrandFactsResponse>("/api/v1/brands/facts", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      brand_name: params.brandName,
      query: params.query || undefined,
      top_k: params.topK ?? 5,
    }),
  });
}

export const searchCategoryFacts = searchBrandFacts;

export async function uploadBrand(payload: BrandUploadRequest): Promise<UploadTaskCreateResponse> {
  return requestJson<UploadTaskCreateResponse>("/api/v1/brands/upload", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function previewParseBrandAttachments(
  payload: AttachmentPreviewParseRequest,
): Promise<AttachmentPreviewParseResponse> {
  return requestJson<AttachmentPreviewParseResponse>("/api/v1/brands/attachments/preview-parse", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function confirmBrandAttachmentParse(
  payload: AttachmentConfirmSaveRequest,
): Promise<AttachmentConfirmSaveResponse> {
  return requestJson<AttachmentConfirmSaveResponse>("/api/v1/brands/attachments/confirm", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function getBrandAttachmentConfirmResult(
  jobId: string,
): Promise<AttachmentConfirmResultResponse> {
  return requestJson<AttachmentConfirmResultResponse>(
    `/api/v1/brands/attachments/confirm/result/${encodeURIComponent(jobId)}`,
  );
}

export async function reviewBrandAttachmentChanges(
  payload: AttachmentReviewChangesRequest,
): Promise<AttachmentReviewChangesResponse> {
  return requestJson<AttachmentReviewChangesResponse>("/api/v1/brands/attachments/review-changes", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function deleteBrand(
  brandName: string,
  dryRun: boolean,
): Promise<BrandDeleteResponse> {
  return requestJson<BrandDeleteResponse>("/api/v1/brands/delete", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      brand_name: brandName,
      dry_run: dryRun,
    }),
  });
}

export async function updateKnowledge(
  payload: KnowledgeUpdateRequest,
): Promise<Record<string, unknown>> {
  return requestJson<Record<string, unknown>>("/api/v1/knowledge/update", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
}

export async function startBrandAttachmentConflictSession(params: {
  taskId: string;
  initialMessage?: string;
}): Promise<BrandKnowledgeSessionResponse> {
  return requestJson<BrandKnowledgeSessionResponse>("/api/v1/brands/knowledge-base/conflict-sessions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      task_id: params.taskId,
      initial_message: params.initialMessage || undefined,
    }),
  });
}

export async function startBrandKnowledgeSession(params: {
  sessionType: "initial_generation" | "knowledge_iteration";
  taskId?: string;
  brandCode?: string;
  brandName?: string;
  iterationMode?: "attachments_only" | "attachments_with_instruction" | "instruction_only";
  initialMessage?: string;
  updateInstruction?: string;
}): Promise<BrandKnowledgeSessionResponse> {
  return requestJson<BrandKnowledgeSessionResponse>("/api/v1/brands/knowledge-base/sessions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_type: params.sessionType,
      task_id: params.taskId || undefined,
      brand_code: params.brandCode || undefined,
      brand_name: params.brandName || undefined,
      iteration_mode: params.iterationMode || undefined,
      initial_message: params.initialMessage || undefined,
      update_instruction: params.updateInstruction || undefined,
    }),
  });
}

export async function getLatestBrandAttachmentConflictSession(params: {
  brandCode: string;
  brandName?: string;
}): Promise<BrandKnowledgeLatestSessionResponse> {
  return requestJson<BrandKnowledgeLatestSessionResponse>("/api/v1/brands/knowledge-base/conflict-session/latest", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      brand_code: params.brandCode,
      brand_name: params.brandName || undefined,
    }),
  });
}

export async function submitBrandAttachmentConflictResolutions(
  payload: {
    sessionId: string;
    roundNo: number;
    resolutions: Array<{
      conflict_id: string;
      decision: string;
      selected_option_id?: string | null;
      final_content?: string | null;
    }>;
    forceReingest?: boolean;
  },
): Promise<BrandKnowledgeSessionResponse> {
  return requestJson<BrandKnowledgeSessionResponse>("/api/v1/brands/knowledge-base/conflict-sessions/resolutions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      session_id: payload.sessionId,
      round_no: payload.roundNo,
      resolutions: payload.resolutions,
      force_reingest: Boolean(payload.forceReingest),
    }),
  });
}
