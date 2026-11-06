ALTER TABLE upload_task_files
    ADD COLUMN file_role VARCHAR(64) NULL COMMENT '文件角色：attachment/brand_ai_knowledge/legacy_document' AFTER original_filename,
    ADD COLUMN content_type VARCHAR(128) NULL COMMENT '文件内容类型' AFTER converted_version,
    ADD COLUMN oss_key VARCHAR(512) NULL COMMENT 'OSS对象Key' AFTER content_type,
    ADD COLUMN oss_url TEXT NULL COMMENT 'OSS访问地址' AFTER oss_key,
    ADD COLUMN asset_id BIGINT NULL COMMENT '普通附件资产ID' AFTER oss_url,
    ADD COLUMN full_knowledge_file_id BIGINT NULL COMMENT '正式知识库文件ID' AFTER asset_id;
