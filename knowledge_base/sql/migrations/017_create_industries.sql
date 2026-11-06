CREATE TABLE IF NOT EXISTS industries (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    code VARCHAR(50) NOT NULL,
    name VARCHAR(100) NOT NULL,
    level BIGINT DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_industries_code (code),
    KEY idx_industries_name (name)
) COMMENT='行业字典表';
