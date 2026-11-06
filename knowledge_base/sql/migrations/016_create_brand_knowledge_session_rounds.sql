CREATE TABLE IF NOT EXISTS brand_knowledge_session_rounds (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    session_id VARCHAR(64) NOT NULL COMMENT '会话ID',
    round_no INT NOT NULL COMMENT '轮次',
    stage VARCHAR(32) NOT NULL COMMENT '阶段：initial/chat/finalize',
    user_message_text LONGTEXT NULL COMMENT '本轮用户输入',
    assistant_message_text LONGTEXT NULL COMMENT '本轮助手回复',
    request_payload_json JSON NULL COMMENT '本轮请求载荷',
    response_payload_json JSON NULL COMMENT '本轮模型原始响应',
    draft_markdown LONGTEXT NULL COMMENT '本轮草稿',
    conflicts_json JSON NULL COMMENT '本轮冲突',
    conflict_markdown LONGTEXT NULL COMMENT '本轮冲突说明markdown',
    user_resolution_json JSON NULL COMMENT '本轮用户决策',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_brand_knowledge_rounds_session (session_id, round_no)
) COMMENT='品牌知识库多轮会话轮次表';
