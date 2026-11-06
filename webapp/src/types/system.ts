export type HealthResponse = {
  status: string;
  collection_name: string;
};

export type BackgroundJobUploadTaskFileSummary = {
  file_id: number;
  file_index: number;
  file_name: string;
  file_role?: string | null;
  status: string;
  file_size?: number | null;
  file_hash?: string | null;
  content_type?: string | null;
  converted_version?: number | null;
  document_id?: string | null;
  source_type?: string | null;
  chunk_count?: number | null;
  asset_id?: number | null;
  full_knowledge_file_id?: number | null;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
};

export type BackgroundJobUploadTaskSummary = {
  task_id: string;
  task_type?: string | null;
  status: string;
  file_count: number;
  success_count: number;
  failed_count: number;
  pending_count: number;
  processing_count: number;
  brand_code?: string | null;
  brand_name?: string | null;
  metadata: Record<string, unknown>;
  error_message?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  files: BackgroundJobUploadTaskFileSummary[];
};

export type BackgroundJob = {
  job_id: string;
  job_type: string;
  source_type?: string | null;
  source_id?: string | null;
  status: string;
  priority: number;
  retry_count: number;
  max_retries: number;
  next_retry_at?: string | null;
  locked_by?: string | null;
  locked_at?: string | null;
  last_error_message?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  payload: Record<string, unknown>;
  result: Record<string, unknown>;
  upload_task?: BackgroundJobUploadTaskSummary | null;
};

export type BackgroundJobListResponse = {
  jobs: BackgroundJob[];
  limit: number;
  offset: number;
  total: number;
  status_counts: Record<string, number>;
};
