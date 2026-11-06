ALTER TABLE brand_attachment_assets
    ADD COLUMN converted_version INT NULL COMMENT '附件解析版本号' AFTER parsed_markdown,
    ADD COLUMN fulltext_key VARCHAR(512) NULL COMMENT '附件解析 Markdown OSS Key' AFTER converted_version,
    ADD COLUMN fulltext_url TEXT NULL COMMENT '附件解析 Markdown OSS URL' AFTER fulltext_key;
