export type BrandAttachment = {
  name: string;
  url: string;
};

export type AttachmentPreviewParseRequest = {
  brand_name: string;
  brand_code?: string | null;
  attachments: BrandAttachment[];
};

export type BrandKnowledgeSnapshot = {
  basic_info?: Record<string, unknown>;
  products?: Array<Record<string, unknown>>;
  company_profile?: Record<string, unknown>;
  management_team?: Array<Record<string, unknown>>;
  competitors?: Array<Record<string, unknown>>;
  authority_honors?: Array<Record<string, unknown>>;
  customers_cases?: Array<Record<string, unknown>>;
  official_media_matrix?: Array<Record<string, unknown>>;
  official_malls?: Array<Record<string, unknown>>;
  sensitive_topics?: Record<string, unknown>;
  attachments?: Array<Record<string, unknown>>;
  other_info?: Array<Record<string, unknown>>;
};

export type AttachmentPreviewParseResponse = {
  draft_id: string;
  brand_name: string;
  candidate_snapshot: BrandKnowledgeSnapshot;
  field_labels?: Record<string, string>;
  knowledge_revision?: string | null;
};

export type AttachmentReviewChangeSummary = {
  added_field_count: number;
  modified_field_count: number;
  deleted_field_count: number;
};

export type AttachmentReviewChangeItem = {
  field_path: string;
  field_label?: string | null;
  change_type: string;
  old_value?: unknown;
  new_value?: unknown;
};

export type AttachmentReviewChangesRequest = {
  draft_id: string;
  candidate_snapshot: BrandKnowledgeSnapshot;
  brand_code?: string | null;
  brand_name?: string | null;
  knowledge_revision?: string | null;
};

export type AttachmentReviewChangesResponse = {
  review_id: string;
  draft_id: string;
  brand_code?: string | null;
  brand_name: string;
  knowledge_revision?: string | null;
  summary: AttachmentReviewChangeSummary;
  changes: AttachmentReviewChangeItem[];
  warnings: string[];
  can_confirm: boolean;
};

export type AttachmentConfirmSaveRequest = {
  draft_id: string;
  review_id: string;
  confirmed_text?: string | null;
  brand_name?: string | null;
  knowledge_revision?: string | null;
};

export type AttachmentConfirmSaveResponse = {
  draft_id: string;
  brand_code?: string | null;
  brand_id?: number | null;
  brand_name: string;
  status: string;
  updated_sections: string[];
  knowledge_revision?: string | null;
  final_markdown_oss_key?: string | null;
  final_markdown_oss_url?: string | null;
  final_document_id?: string | null;
  original_attachments: Array<Record<string, unknown>>;
  attachment_documents?: Array<Record<string, unknown>>;
  background_job_id?: string | null;
  background_job_status?: string | null;
  confirm_callback_status?: string | null;
};

export type AttachmentConfirmResultData = {
  version: string;
  brand_code?: string | null;
  brand_id?: number | null;
  brand_name: string;
  updated_sections: string[];
  knowledge_revision: string;
  final_markdown_oss_key: string;
  final_markdown_oss_url: string;
  final_document_id: string;
  original_attachments: Array<Record<string, unknown>>;
  attachment_documents: Array<Record<string, unknown>>;
  confirm_callback_status: string;
  oss_url_md: string;
  oss_url_pdf: string;
};

export type AttachmentConfirmResultResponse = {
  code: number;
  message: string;
  data?: AttachmentConfirmResultData | null;
};

export type BrandCompetitor = {
  name: string;
  website?: string | null;
};

export type BrandProduct = {
  name?: string | null;
  product_alias?: string | null;
  product_images?: string[];
  product_description?: string | null;
  product_link?: string | null;
  attachments?: BrandAttachment[];
  competitors?: string | null;
};

export type BrandUploadRequest = {
  brand_code?: string | null;
  brand_name: string;
  brand_alias?: string | null;
  brand_logo?: string | null;
  website?: string[];
  enterprise_subject?: string | null;
  business_license_url?: string | null;
  intro?: string | null;
  email?: string | null;
  products?: BrandProduct[];
  competitors?: BrandCompetitor[];
  attachments?: BrandAttachment[];
};

export type BrandListItem = {
  id: number;
  brand_code?: string | null;
  brand_name: string;
  brand_alias?: string | null;
  website?: string[];
  intro?: string | null;
  updated_at?: string | null;
};

export type BrandListResponse = {
  keyword?: string | null;
  brands: BrandListItem[];
};

export type BrandLatestAiKnowledgeData = {
  brand_code: string;
  brand_name: string;
  brand_id?: number | null;
  file_name: string;
  oss_key: string;
  oss_url: string;
  version_no?: number | null;
  created_at?: string | null;
  source?: string | null;
};

export type BrandLatestAiKnowledgeResponse = {
  code: number;
  message: string;
  data?: BrandLatestAiKnowledgeData | null;
};

export type BrandDeleteCounts = {
  brands: number;
  brand_products: number;
  brand_knowledge_json: number;
  brand_attachment_assets: number;
  brand_knowledge_sessions: number;
  brand_knowledge_session_rounds: number;
  brand_knowledge_facts: number;
  documents: number;
  document_registry: number;
  document_categories: number;
  document_summaries?: number;
  document_fact_relations: number;
  brand_full_knowledge_files: number;
  brand_knowledge_ingestion_jobs: number;
  background_jobs: number;
  upload_tasks: number;
  upload_task_files: number;
  upload_task_callbacks: number;
  ai_knowledge_oss_objects: number;
  confirmed_knowledge_oss_objects: number;
  oss_objects: number;
};

export type BrandDeleteResponse = {
  brand_code?: string | null;
  brand_id?: number | null;
  brand_name: string;
  dry_run: boolean;
  executed: boolean;
  message: string;
  counts: BrandDeleteCounts;
};

export type KnowledgeUpdateRequest = {
  basic_info: Record<string, unknown>;
  products?: Array<Record<string, unknown>>;
  company_profile?: Record<string, unknown> | null;
  management_team?: Array<Record<string, unknown>>;
  competitors?: Array<Record<string, unknown>>;
  authority_honors?: Array<Record<string, unknown>>;
  customers_cases?: Array<Record<string, unknown>>;
  official_media_matrix?: Array<Record<string, unknown>>;
  official_malls?: Array<Record<string, unknown>>;
  sensitive_topics?: Record<string, string[]>;
  attachments?: Array<Record<string, unknown>>;
  other_info?: Array<Record<string, unknown>>;
};
