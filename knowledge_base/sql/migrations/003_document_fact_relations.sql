CREATE TABLE IF NOT EXISTS document_fact_relations (
    document_id VARCHAR(128),
    fact_id VARCHAR(128),
    PRIMARY KEY (document_id, fact_id),
    INDEX idx_fact_id (fact_id)
) COMMENT='文档与事实';
