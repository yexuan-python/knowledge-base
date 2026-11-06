CREATE TABLE IF NOT EXISTS brand_products (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    brand_name VARCHAR(255) NOT NULL,
    product_name VARCHAR(255) NOT NULL,
    product_alias TEXT NULL,
    product_description TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_brand_product_name (brand_name, product_name),
    INDEX idx_brand_products_brand (brand_name)
) COMMENT='品牌产品表';
