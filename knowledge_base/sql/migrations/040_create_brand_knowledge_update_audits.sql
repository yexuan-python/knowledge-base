CREATE TABLE IF NOT EXISTS brand_knowledge_update_audits (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    audit_id VARCHAR(64) NOT NULL COMMENT '同一次 knowledge/update 的审计批次ID',
    brand_id BIGINT NOT NULL COMMENT '品牌ID',
    brand_code VARCHAR(128) NULL COMMENT '品牌编码',
    brand_name VARCHAR(255) NOT NULL COMMENT '品牌名称',
    knowledge_revision VARCHAR(128) NULL COMMENT '本次更新后的知识版本号',
    section VARCHAR(64) NOT NULL COMMENT '发生变化的 section 标识',
    section_title VARCHAR(128) NOT NULL COMMENT 'section 展示标题',
    change_action VARCHAR(32) NOT NULL COMMENT '变更动作：update/delete',
    before_json JSON NULL COMMENT '变更前内容',
    after_json JSON NULL COMMENT '变更后内容',
    source_type VARCHAR(32) NOT NULL DEFAULT 'knowledge_update' COMMENT '数据来源',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_bkua_brand_code_created (brand_code, created_at, id),
    INDEX idx_bkua_brand_id_created (brand_id, created_at, id),
    INDEX idx_bkua_audit_id (audit_id)
) COMMENT='knowledge/update 结构化变更审计表';
