CREATE TABLE IF NOT EXISTS brand_knowledge_facts (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    brand_code VARCHAR(64) NOT NULL COMMENT '品牌业务编码',
    brand_name VARCHAR(255) NOT NULL COMMENT '品牌名称',
    fact_id VARCHAR(128) NOT NULL COMMENT '品牌内去重后的事实ID',
    fact_text TEXT NOT NULL COMMENT '事实文本',
    normalized_fact_hash CHAR(64) NOT NULL COMMENT '规范化事实内容SHA256',
    source_document_id VARCHAR(128) NOT NULL COMMENT '来源文档ID',
    full_knowledge_file_id BIGINT NULL COMMENT '来源知识库文件ID',
    version_no INT NULL COMMENT '来源版本号',
    knowledge_date CHAR(8) NULL COMMENT '来源版本日期YYYYMMDD',
    section_path VARCHAR(512) NULL COMMENT '来源章节路径',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_brand_knowledge_fact_hash (brand_code, normalized_fact_hash),
    INDEX idx_brand_knowledge_facts_brand (brand_code),
    INDEX idx_brand_knowledge_facts_document (source_document_id),
    INDEX idx_brand_knowledge_facts_fact_id (fact_id)
) COMMENT='品牌AI知识库事实表';
