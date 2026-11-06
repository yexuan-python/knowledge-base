CREATE TABLE IF NOT EXISTS document_alert (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,
    alert_type VARCHAR(64) NOT NULL,
    alert_name VARCHAR(128) NOT NULL,
    dedupe_key VARCHAR(255) NOT NULL,
    task_id VARCHAR(128) NULL,
    document_id VARCHAR(128) NULL,
    document_name VARCHAR(128) NOT NULL,
    reason TEXT NULL,
    payload_json JSON NOT NULL,
    send_status VARCHAR(32) NOT NULL,
    send_response TEXT NULL,
    send_error TEXT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent_at TIMESTAMP NULL DEFAULT NULL,
    UNIQUE KEY uk_document_alert_dedupe (dedupe_key),
    INDEX idx_document_alert_type_created (alert_type, created_at)
) COMMENT = '存储文档告警信息';