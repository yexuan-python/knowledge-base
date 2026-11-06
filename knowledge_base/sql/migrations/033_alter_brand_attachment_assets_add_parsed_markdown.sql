ALTER TABLE brand_attachment_assets
    ADD COLUMN parsed_source_type VARCHAR(64) NULL COMMENT '附件解析后的文本来源类型' AFTER content_type,
    ADD COLUMN parsed_markdown MEDIUMTEXT NULL COMMENT '附件解析后的 Markdown 文本' AFTER parsed_source_type;
