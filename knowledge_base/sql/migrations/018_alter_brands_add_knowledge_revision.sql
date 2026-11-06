ALTER TABLE brands
MODIFY COLUMN industry_id BIGINT NULL COMMENT '所属行业ID',
ADD COLUMN knowledge_revision VARCHAR(128) NULL COMMENT '知识库版本号' AFTER industry_id;
