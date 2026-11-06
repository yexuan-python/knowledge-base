ALTER TABLE brand_products
    DROP INDEX uk_brand_product_name,
    DROP INDEX uk_brand_id_product_name,
    ADD INDEX idx_brand_products_brand_name_product_name (brand_name, product_name),
    ADD INDEX idx_brand_products_brand_id_product_name (brand_id, product_name);
