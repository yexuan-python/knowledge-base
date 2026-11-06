ALTER TABLE upload_tasks
    ADD COLUMN task_type VARCHAR(64) NULL COMMENT '任务类型：document_upload/brand_upload/brand_ai_knowledge_upload' AFTER task_id;
