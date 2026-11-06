CREATE TABLE IF NOT EXISTS upload_task_callbacks (
    id BIGINT PRIMARY KEY AUTO_INCREMENT COMMENT '主键ID',
    task_id VARCHAR(128) NOT NULL COMMENT '上传任务ID',
    callback_type VARCHAR(64) NOT NULL COMMENT '回调类型：brand_knowledge_status / brand_knowledge_completed / attachment_delete_completed',
    callback_url TEXT NOT NULL COMMENT '回调目标地址',
    request_payload_json JSON NULL COMMENT '回调请求体JSON',
    status VARCHAR(32) NOT NULL COMMENT '回调状态：waiting/pending/retrying/success/failed',
    retry_count INT NOT NULL DEFAULT 0 COMMENT '已重试次数',
    next_retry_at TIMESTAMP NULL DEFAULT NULL COMMENT '下次重试时间',
    last_response_code INT NULL COMMENT '最近一次响应状态码',
    last_response_body TEXT NULL COMMENT '最近一次响应内容',
    last_error_message TEXT NULL COMMENT '最近一次错误信息',
    sent_at TIMESTAMP NULL DEFAULT NULL COMMENT '成功回调时间',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    UNIQUE KEY uk_upload_task_callback_type (task_id, callback_type),
    INDEX idx_upload_task_callbacks_status (status, next_retry_at)
 ) COMMENT='上传任务回调记录表';
