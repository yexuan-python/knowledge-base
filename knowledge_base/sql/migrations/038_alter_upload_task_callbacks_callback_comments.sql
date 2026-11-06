ALTER TABLE upload_task_callbacks
    MODIFY COLUMN callback_type VARCHAR(64) NOT NULL COMMENT '回调类型：brand_knowledge_status / brand_knowledge_completed / attachment_delete_completed',
    MODIFY COLUMN request_payload_json JSON NULL COMMENT '回调请求体JSON；brand_knowledge_completed 必带 knowledge，brand_knowledge_status 不带 knowledge',
    COMMENT = '上传任务回调记录表';
