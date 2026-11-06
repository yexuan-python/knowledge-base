ALTER TABLE brand_products
ADD COLUMN product_code VARCHAR(128) NULL COMMENT '上游产品编码' AFTER brand_id,
ADD UNIQUE KEY uk_brand_products_product_code (product_code),
ADD INDEX idx_brand_products_brand_product_code (brand_id, product_code);
