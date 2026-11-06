ALTER TABLE brand_knowledge_sessions
    ADD COLUMN brand_code VARCHAR(64) NULL COMMENT '品牌业务编码' AFTER brand_id,
    ADD COLUMN source_task_id VARCHAR(128) NULL COMMENT '来源上传任务ID' AFTER brand_name,
    ADD COLUMN session_kind VARCHAR(64) NOT NULL DEFAULT 'legacy_chat' COMMENT '会话类型：legacy_chat/attachment_conflict/revision' AFTER source_task_id,
    ADD COLUMN latest_scan_summary TEXT NULL COMMENT '最近一次冲突扫描摘要' AFTER latest_conflict_markdown,
    ADD COLUMN latest_auto_merged_json JSON NULL COMMENT '最近一次自动消解结果' AFTER latest_scan_summary,
    ADD COLUMN final_full_knowledge_file_id BIGINT NULL COMMENT '最终生成的正式知识库文件ID' AFTER final_oss_key,
    ADD COLUMN final_document_id VARCHAR(128) NULL COMMENT '最终生成的Milvus文档ID' AFTER final_full_knowledge_file_id,
    ADD INDEX idx_brand_knowledge_source_task (source_task_id, updated_at),
    ADD INDEX idx_brand_knowledge_brand_code_status (brand_code, status, updated_at);
