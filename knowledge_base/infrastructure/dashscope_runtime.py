from __future__ import annotations

import logging

import dashscope


logger = logging.getLogger(__name__)
_configured_base_http_api_url: str | None = None


def configure_dashscope(settings: object) -> None:
    global _configured_base_http_api_url

    base_http_api_url = str(getattr(settings, "dashscope_base_http_api_url", "") or "").strip()
    if not base_http_api_url:
        return

   

    dashscope.base_http_api_url = base_http_api_url
    logger.info("DashScope base_http_api_url configured: %s", dashscope.base_http_api_url)
