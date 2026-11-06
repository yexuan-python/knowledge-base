CREATE TABLE IF NOT EXISTS document_summaries (
    document_id VARCHAR(128) PRIMARY KEY,
    category VARCHAR(255) NOT NULL,
    summary TEXT,
    url TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_summaries_category (category)
) COMMENT='存储文档的AI生成摘要及原始URL';
