ALTER TABLE brand_attachment_assets
    ADD COLUMN asset_kind VARCHAR(32) NULL COMMENT '附件资产类型：file/image' AFTER content_type,
    ADD COLUMN image_summary TEXT NULL COMMENT '图片 LLM 摘要描述' AFTER fulltext_url,
    ADD COLUMN image_tags_json TEXT NULL COMMENT '图片 LLM 标签 JSON 数组' AFTER image_summary;
