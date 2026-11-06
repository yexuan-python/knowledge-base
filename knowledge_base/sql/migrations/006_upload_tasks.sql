CREATE TABLE IF NOT EXISTS upload_tasks (
    task_id VARCHAR(128) PRIMARY KEY,
    status VARCHAR(32) NOT NULL,
    file_count INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    pending_count INT NOT NULL DEFAULT 0,
    processing_count INT NOT NULL DEFAULT 0,
    metadata_json JSON NULL,
    chunk_size INT NULL,
    chunk_overlap INT NULL,
    error_message TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_upload_tasks_status (status, created_at)
) COMMENT='批量上传任务';
