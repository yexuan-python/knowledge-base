DELETE legacy
FROM upload_task_callbacks AS legacy
JOIN upload_task_callbacks AS current
  ON current.task_id = legacy.task_id
 AND current.callback_type = CASE
    WHEN legacy.callback_type = 'attachment_conflict_waiting_user_input' THEN 'brand_knowledge_status'
    WHEN legacy.callback_type IN ('attachment_conflict_completed', 'attachment_confirm_completed')
        THEN 'brand_knowledge_completed'
    ELSE legacy.callback_type
END
WHERE legacy.callback_type IN (
    'attachment_conflict_waiting_user_input',
    'attachment_conflict_completed',
    'attachment_confirm_completed'
)
  AND legacy.callback_type <> current.callback_type;
