ALTER TABLE brand_knowledge_facts
    ADD COLUMN fact_scope VARCHAR(64) NOT NULL DEFAULT 'official_kb' COMMENT '事实作用域：official_kb/attachment_temp' AFTER brand_name,
    ADD COLUMN source_task_id VARCHAR(64) NULL COMMENT '来源上传任务ID' AFTER source_document_id,
    ADD COLUMN source_asset_id BIGINT NULL COMMENT '来源附件资产ID' AFTER source_task_id,
    ADD INDEX idx_brand_knowledge_facts_scope_task (brand_code, fact_scope, source_task_id);
