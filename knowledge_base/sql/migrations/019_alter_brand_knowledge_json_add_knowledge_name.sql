ALTER TABLE brand_knowledge_json
ADD COLUMN knowledge_name VARCHAR(128) NULL COMMENT '知识类型名称' AFTER knowledge_type;
