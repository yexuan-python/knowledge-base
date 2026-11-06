from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from knowledge_base.alerts.schemas import DocumentAlert

from .mysql_base import MySQLStoreBase


class DocumentAlertStore(MySQLStoreBase):
    def insert_document_alert(self, alert: DocumentAlert) -> tuple[int, bool]:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO document_alert (
                        alert_type,
                        alert_name,
                        dedupe_key,
                        task_id,
                        document_id,
                        document_name,
                        reason,
                        payload_json,
                        send_status,
                        send_response,
                        send_error,
                        sent_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE id = LAST_INSERT_ID(id)
                    """,
                    (
                        alert.alert_type,
                        alert.alert_name,
                        alert.dedupe_key,
                        alert.task_id,
                        alert.document_id,
                        alert.document_name,
                        alert.reason,
                        json.dumps(alert.payload_json, ensure_ascii=False),
                        alert.send_status,
                        alert.send_response,
                        alert.send_error,
                        alert.sent_at,
                    ),
                )
                return cursor.lastrowid, cursor.rowcount == 1

    def update_document_alert_send_result(
        self,
        *,
        dedupe_key: str,
        send_status: str,
        send_response: Optional[str] = None,
        send_error: Optional[str] = None,
        sent_at: Optional[datetime] = None,
    ) -> None:
        with self._get_conn() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE document_alert
                    SET send_status = %s,
                        send_response = %s,
                        send_error = %s,
                        sent_at = %s
                    WHERE dedupe_key = %s
                    """,
                    (send_status, send_response, send_error, sent_at, dedupe_key),
                )
