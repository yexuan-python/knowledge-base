CREATE TABLE IF NOT EXISTS brand_full_knowledge_files (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    brand_id BIGINT NOT NULL COMMENT '品牌ID，关联brands.id',
    brand_name VARCHAR(255) NOT NULL COMMENT '品牌名称',
    version_no INT NOT NULL COMMENT '版本号，从1开始递增',
    file_name VARCHAR(255) NOT NULL COMMENT '完整知识库Markdown文件名',
    oss_key VARCHAR(512) NULL COMMENT 'OSS对象Key',
    oss_url TEXT NULL COMMENT 'OSS下载链接',
    content_markdown LONGTEXT NOT NULL COMMENT '完整知识库Markdown内容',
    conflict_count INT NOT NULL DEFAULT 0 COMMENT '冲突数量',
    conflicts_json JSON NULL COMMENT '冲突详情',
    source_task_id VARCHAR(128) NULL COMMENT '来源上传任务ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_brand_full_knowledge_version (brand_id, version_no),
    UNIQUE KEY uk_brand_full_knowledge_task (brand_id, source_task_id),
    INDEX idx_brand_full_knowledge_brand (brand_id),
    INDEX idx_brand_full_knowledge_task (source_task_id)
) COMMENT='品牌全量AI知识库Markdown文件表';
