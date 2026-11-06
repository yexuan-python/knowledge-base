CREATE TABLE IF NOT EXISTS document_categories (
    document_id VARCHAR(128) PRIMARY KEY,
    category VARCHAR(255) NOT NULL,
    subcategory VARCHAR(255),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_category_subcategory (category, subcategory)
) COMMENT='存储文档与分类、子分类的映射关系';
