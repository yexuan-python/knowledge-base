export type BrandKnowledgeConflictOption = {
  option_id: string;
  content: string;
  source_files: string[];
};

export type BrandKnowledgeConflictItem = {
  conflict_id: string;
  topic: string;
  severity?: string | null;
  description?: string | null;
  options: BrandKnowledgeConflictOption[];
};

export type BrandKnowledgeAutoMergedItem = {
  topic: string;
  category: string;
  resolution: string;
  source_files: string[];
};

export type BrandKnowledgeSourceDocumentItem = {
  document_id: string;
  original_filename: string;
  source_type?: string | null;
  source_role?: string | null;
  fulltext_key?: string | null;
  source_url?: string | null;
  error_message?: string | null;
  subcategory?: string | null;
};

export type BrandKnowledgeSessionResponse = {
  session_id: string;
  brand_code?: string | null;
  brand_name: string;
  status: string;
  knowledge_markdown_status?: string | null;
  round_no: number;
  session_type?: string | null;
  iteration_mode?: string | null;
  session_kind?: string | null;
  source_task_id?: string | null;
  assistant_message?: string | null;
  source_documents: BrandKnowledgeSourceDocumentItem[];
  conflicts: BrandKnowledgeConflictItem[];
  conflict_markdown?: string | null;
  scan_summary?: string | null;
  auto_merged?: BrandKnowledgeAutoMergedItem[];
  final_markdown?: string | null;
  final_oss_key?: string | null;
  final_filename?: string | null;
  final_full_knowledge_file_id?: number | null;
  final_document_id?: string | null;
  knowledge_oss_url_md?: string | null;
  knowledge_oss_url_pdf?: string | null;
};

export type BrandKnowledgeSessionEmptyResponse = {
  brand_code?: string | null;
  brand_name: string;
  status: string;
  knowledge_markdown_status?: string | null;
};

export type BrandKnowledgeLatestSessionResponse =
  | BrandKnowledgeSessionResponse
  | BrandKnowledgeSessionEmptyResponse;
