ALTER TABLE brand_full_knowledge_files
    ADD COLUMN change_origin VARCHAR(32) NOT NULL DEFAULT 'frontend' COMMENT '全量知识库变更来源：frontend/api' AFTER source_task_id,
    ADD INDEX idx_brand_full_knowledge_origin (brand_code, change_origin, version_no, revision_no, id);
