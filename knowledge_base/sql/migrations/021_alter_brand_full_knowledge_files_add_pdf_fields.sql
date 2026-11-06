ALTER TABLE brand_full_knowledge_files
    ADD COLUMN pdf_file_name VARCHAR(255) NULL COMMENT '完整知识库PDF文件名' AFTER file_name,
    ADD COLUMN pdf_oss_key VARCHAR(512) NULL COMMENT 'PDF OSS对象Key' AFTER oss_url,
    ADD COLUMN pdf_oss_url TEXT NULL COMMENT 'PDF OSS下载链接' AFTER pdf_oss_key;
