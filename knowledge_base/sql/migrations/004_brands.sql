CREATE TABLE IF NOT EXISTS brands (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    brand_name VARCHAR(255) NOT NULL,
    brand_alias VARCHAR(255) NULL,
    brand_logo TEXT NULL,
    website TEXT NULL,
    intro TEXT NULL,
    email VARCHAR(255) NULL,
    competitors_json JSON NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_brand_name (brand_name)
) COMMENT='品牌主表';
