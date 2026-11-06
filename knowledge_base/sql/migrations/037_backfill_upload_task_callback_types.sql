UPDATE upload_task_callbacks
SET callback_type = CASE
    WHEN callback_type = 'attachment_conflict_waiting_user_input' THEN 'brand_knowledge_status'
    WHEN callback_type IN ('attachment_conflict_completed', 'attachment_confirm_completed')
        THEN 'brand_knowledge_completed'
    ELSE callback_type
END
WHERE callback_type IN (
    'attachment_conflict_waiting_user_input',
    'attachment_conflict_completed',
    'attachment_confirm_completed'
);
