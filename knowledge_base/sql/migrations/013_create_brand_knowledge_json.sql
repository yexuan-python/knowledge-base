CREATE TABLE IF NOT EXISTS brand_knowledge_json (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    brand_id BIGINT NOT NULL COMMENT '品牌ID，关联brands.id',
    knowledge_type VARCHAR(64) NOT NULL COMMENT '知识类型：company_info/management_team/competitors/honors/cases/sensitive_topics/attachments',
    content_json JSON NOT NULL COMMENT '知识内容JSON',
    source_task_id VARCHAR(128) NULL COMMENT '来源上传任务ID',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_brand_knowledge_type (brand_id, knowledge_type),
    INDEX idx_brand_knowledge_brand (brand_id),
    INDEX idx_brand_knowledge_type (knowledge_type)
) COMMENT='品牌扩展知识JSON表';
