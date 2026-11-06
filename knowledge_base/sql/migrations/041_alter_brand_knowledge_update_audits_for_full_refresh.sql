ALTER TABLE brand_knowledge_update_audits
  ADD COLUMN source_task_id VARCHAR(128) NULL COMMENT '来源任务ID，如 confirm:{draft_id}:{review_id} 或 knowledge_update:{uuid}' AFTER source_type,
  ADD COLUMN source_job_id VARCHAR(128) NULL COMMENT '来源后台任务ID' AFTER source_task_id,
  ADD COLUMN source_name VARCHAR(255) NULL COMMENT '来源Markdown文件名' AFTER source_job_id,
  ADD COLUMN source_oss_key VARCHAR(512) NULL COMMENT '来源Markdown OSS key' AFTER source_name,
  ADD COLUMN full_knowledge_claimed_job_id VARCHAR(128) NULL COMMENT '认领该变更的全量知识库生成任务ID' AFTER source_oss_key,
  ADD COLUMN full_knowledge_claimed_at TIMESTAMP NULL DEFAULT NULL COMMENT '认领时间' AFTER full_knowledge_claimed_job_id,
  ADD COLUMN full_knowledge_job_id VARCHAR(128) NULL COMMENT '成功消费该变更的全量知识库生成任务ID' AFTER full_knowledge_claimed_at,
  ADD COLUMN full_knowledge_consumed_at TIMESTAMP NULL DEFAULT NULL COMMENT '消费时间' AFTER full_knowledge_job_id,
  ADD INDEX idx_bkua_source_task (source_type, source_task_id),
  ADD INDEX idx_bkua_brand_source_unconsumed (
    brand_code,
    source_type,
    full_knowledge_job_id,
    full_knowledge_claimed_job_id,
    created_at,
    id
  );
