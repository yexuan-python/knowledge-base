from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

import requests


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TianyanchaCompanyProfile:
    company_name: str | None = None
    english_name: str | None = None
    website: str | None = None
    brand_logo: str | None = None
    company_intro: str | None = None
    email: str | None = None
    customer_service_hotline: str | None = None
    official_wechat_account: str | None = None
    registered_capital: str | None = None
    established_time: str | None = None
    company_address: str | None = None
    unified_social_credit_code: str | None = None
    legal_representative: str | None = None
    registration_status: str | None = None
    registration_authority: str | None = None
    company_type: str | None = None
    industry: str | None = None
    industry_classification: str | None = None
    insured_count: str | None = None
    personnel_scale: str | None = None
    company_tags: str | None = None
    approval_date: str | None = None
    business_term_start: str | None = None
    business_term_end: str | None = None


@dataclass(frozen=True)
class TianyanchaManagementMember:
    name: str | None = None
    title: str | None = None
    profile: str | None = None
    other_info: str | None = None


class TianyanchaClient:
    _DEFAULT_PROTOCOL_VERSIONS = (
        "2025-03-26",
        "2024-11-05",
    )

    def __init__(self, settings: Any) -> None:
        self._settings = settings
        self._session_id: str | None = None
        self.last_debug_trace: list[dict[str, Any]] = []

    @staticmethod
    def _normalize_str(value: Any) -> str | None:
        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None

    @staticmethod
    def _pick_first(payload: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            value = payload.get(key)
            normalized = TianyanchaClient._normalize_str(value)
            if normalized:
                return normalized
        return None

    @staticmethod
    def _extract_text_content(payload: Any) -> str:
        if isinstance(payload, dict):
            content = payload.get("content")
            if isinstance(content, list):
                text_parts: list[str] = []
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("type") or "").strip().lower() != "text":
                        continue
                    text = TianyanchaClient._normalize_str(item.get("text"))
                    if text:
                        text_parts.append(text)
                return "\n".join(text_parts)
            text = payload.get("text")
            return TianyanchaClient._normalize_str(text) or ""
        if isinstance(payload, list):
            return "\n".join(
                text for text in (TianyanchaClient._extract_text_content(item) for item in payload) if text
            )
        return ""

    @staticmethod
    def _parse_markdown_table_fields(markdown_text: str) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for raw_line in markdown_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|") or not line.endswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            key = cells[0]
            value = cells[1]
            if not key or key == "字段":
                continue
            if set(key) <= {"-", ":"} or set(value) <= {"-", ":"}:
                continue
            if value and value not in {"", "-", "—", "未披露"}:
                parsed[key] = value
        return parsed

    @staticmethod
    def _parse_markdown_table_rows(markdown_text: str) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        headers: list[str] | None = None
        for raw_line in markdown_text.splitlines():
            line = raw_line.strip()
            if not line.startswith("|") or not line.endswith("|"):
                continue
            cells = [cell.strip() for cell in line.strip("|").split("|")]
            if len(cells) < 2:
                continue
            if headers is None:
                if any(not cell for cell in cells):
                    continue
                headers = cells
                continue
            if all(set(cell) <= {"-", ":"} for cell in cells):
                continue
            if len(cells) < len(headers):
                cells.extend([""] * (len(headers) - len(cells)))
            row = {
                headers[index]: value
                for index, value in enumerate(cells[: len(headers)])
                if headers[index]
            }
            if row:
                rows.append(row)
        return rows

    @staticmethod
    def _extract_management_markdown_section(markdown_text: str) -> str:
        lines = markdown_text.splitlines()
        start_index: int | None = None
        for index, raw_line in enumerate(lines):
            line = raw_line.strip()
            if not line:
                continue
            if "主要人员" in line or "高管" in line or "管理层" in line:
                start_index = index
                break
        if start_index is None:
            return markdown_text

        collected: list[str] = []
        table_started = False
        for raw_line in lines[start_index:]:
            line = raw_line.strip()
            if line.startswith("##") and collected:
                break
            if line.startswith("###") and collected and table_started:
                break
            if line.startswith("####") and collected and table_started:
                break
            if line.startswith("|") and line.endswith("|"):
                table_started = True
                collected.append(raw_line)
                continue
            if table_started:
                if not line:
                    collected.append(raw_line)
                    continue
                if line.startswith(">"):
                    break
                if not line.startswith("|"):
                    break
            elif collected:
                collected.append(raw_line)
        extracted = "\n".join(collected).strip()
        return extracted or markdown_text

    @staticmethod
    def _looks_like_management_name(value: str | None) -> bool:
        normalized = TianyanchaClient._normalize_str(value)
        if not normalized:
            return False
        if any(token in normalized for token in ("名称", "企业名称", "值", "ok")):
            return False
        if normalized.isdigit():
            return False
        if "-" in normalized and any(char.isdigit() for char in normalized):
            return False
        if any(token in normalized for token in ("有限公司", "有限责任公司", "股份有限公司")):
            return False
        if any(token in normalized for token in ("北京市", "上海市", "深圳市", "广州市", "区", "路", "号", "室")):
            return False
        return True

    @staticmethod
    def _looks_like_management_title(value: str | None) -> bool:
        normalized = TianyanchaClient._normalize_str(value)
        if not normalized:
            return True
        keywords = (
            "董事",
            "监事",
            "经理",
            "总监",
            "总裁",
            "ceo",
            "cto",
            "cfo",
            "coo",
            "创始人",
            "合伙人",
            "负责人",
            "财务",
            "执行",
            "副总",
            "总经理",
            "秘",
            "主席",
        )
        lowered = normalized.lower()
        return any(keyword in lowered for keyword in keywords)

    @staticmethod
    def _has_enrichment_fields(profile: TianyanchaCompanyProfile) -> bool:
        return any(
            (
                profile.english_name,
                profile.website,
                profile.brand_logo,
                profile.company_intro,
                profile.email,
                profile.customer_service_hotline,
                profile.official_wechat_account,
                profile.registered_capital,
                profile.established_time,
                profile.company_address,
            )
        )

    @staticmethod
    def _safe_response_payload(response: Any) -> dict[str, Any]:
        try:
            payload = response.json()
        except Exception:
            payload = None
        if isinstance(payload, dict):
            return payload

        text = TianyanchaClient._normalize_str(getattr(response, "text", None))
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {"message": text}
        return parsed if isinstance(parsed, dict) else {}

    @classmethod
    def _is_skipable_tool_error(cls, exc: BaseException) -> bool:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        if status_code not in {402, 403, 429}:
            return False
        payload = cls._safe_response_payload(response)
        error = cls._normalize_str(payload.get("error"))
        message = cls._normalize_str(payload.get("message")) or cls._normalize_str(
            payload.get("error_description")
        )
        required_plan = cls._normalize_str(payload.get("requiredPlan"))
        if status_code == 403:
            return bool(
                error == "insufficient_entitlement"
                or required_plan
                or (message and ("权益" in message or "VIP" in message.upper()))
            )
        if status_code == 402:
            return bool(
                error in {"insufficient_balance", "quota_exceeded"}
                or (message and (
                    "余额" in message
                    or "额度" in message
                    or "quota" in message.lower()
                    or "limit" in message.lower()
                ))
            )
        if status_code == 429:
            return bool(
                error == "rate_limited"
                or (message and (
                    "限流" in message
                    or "频率过快" in message
                    or "too many requests" in message.lower()
                    or "rate limit" in message.lower()
                ))
            )
        return False

    @classmethod
    def _log_skipable_tool_error(cls, *, exc: BaseException, tool_name: str) -> None:
        response = getattr(exc, "response", None)
        payload = cls._safe_response_payload(response)
        status_code = getattr(response, "status_code", None)
        logger.info(
            "Tianyancha tool skipped due to limited entitlement tool_name=%s status_code=%s error=%s required_plan=%s message=%s",
            tool_name,
            status_code,
            cls._normalize_str(payload.get("error")),
            cls._normalize_str(payload.get("requiredPlan")),
            cls._normalize_str(payload.get("message")) or cls._normalize_str(payload.get("error_description")),
        )

    @staticmethod
    def _extract_data_object(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            content_text = TianyanchaClient._extract_text_content(payload)
            if content_text:
                parsed_markdown = TianyanchaClient._parse_markdown_table_fields(content_text)
                if parsed_markdown:
                    parsed_markdown["_raw_text"] = content_text
                    return parsed_markdown
            for key in (
                "structuredContent",
                "result",
                "data",
                "content",
            ):
                candidate = payload.get(key)
                if isinstance(candidate, dict):
                    return candidate
                if isinstance(candidate, list):
                    for item in candidate:
                        if isinstance(item, dict):
                            if isinstance(item.get("json"), dict):
                                return item["json"]
                            if isinstance(item.get("structuredContent"), dict):
                                return item["structuredContent"]
                            if isinstance(item.get("data"), dict):
                                return item["data"]
            return payload
        return {}

    @staticmethod
    def _extract_sse_json_objects(raw_text: str) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        lines = raw_text.splitlines()
        data_lines: list[str] = []
        for line in lines:
            if line.startswith("data:"):
                data_lines.append(line[5:].strip())
                continue
            if not line.strip() and data_lines:
                chunk = "\n".join(data_lines).strip()
                data_lines.clear()
                if not chunk or chunk == "[DONE]":
                    continue
                try:
                    parsed = json.loads(chunk)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    payloads.append(parsed)
        if data_lines:
            chunk = "\n".join(data_lines).strip()
            if chunk and chunk != "[DONE]":
                try:
                    parsed = json.loads(chunk)
                except json.JSONDecodeError:
                    parsed = None
                if isinstance(parsed, dict):
                    payloads.append(parsed)
        return payloads

    @staticmethod
    def _tool_matches_registration_info(tool: dict[str, Any]) -> bool:
        haystacks = [
            str(tool.get("name") or "").lower(),
            str(tool.get("title") or "").lower(),
            str(tool.get("description") or "").lower(),
        ]
        return any(
            keyword in haystack
            for haystack in haystacks
            for keyword in ("registration", "工商", "登记", "basic", "基本信息")
        )

    @staticmethod
    def _tool_matches_management_info(tool: dict[str, Any]) -> bool:
        haystacks = [
            str(tool.get("name") or "").lower(),
            str(tool.get("title") or "").lower(),
            str(tool.get("description") or "").lower(),
        ]
        return any(
            keyword in haystack
            for haystack in haystacks
            for keyword in ("management", "manager", "高管", "主要人员", "管理层")
        )

    @staticmethod
    def _extract_data_rows(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("items", "rows", "data", "list", "content", "result"):
                candidate = payload.get(key)
                if isinstance(candidate, list):
                    return [item for item in candidate if isinstance(item, dict)]
            return [payload]
        return []

    def enabled(self) -> bool:
        return bool(
            self._settings.tianyancha_enabled
            and self._normalize_str(self._settings.tianyancha_api_key)
            and self._normalize_str(self._settings.tianyancha_mcp_url)
        )

    def _request_headers(self, *, protocol_version: str) -> dict[str, str]:
        return {
            "Authorization": str(self._settings.tianyancha_api_key),
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": protocol_version,
        }

    def _start_session(self, *, protocol_version: str) -> str:
        response = requests.post(
            self._settings.tianyancha_mcp_url,
            headers=self._request_headers(protocol_version=protocol_version),
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            timeout=self._settings.tianyancha_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") or {}
        session_id = self._normalize_str(result.get("sessionId")) or self._normalize_str(
            response.headers.get("Mcp-Session-Id")
        ) or self._normalize_str(
            response.headers.get("mcp-session-id")
        )
        if not session_id:
            raise ValueError("Tianyancha MCP initialize missing session id")
        requests.post(
            self._settings.tianyancha_mcp_url,
            headers={
                **self._request_headers(protocol_version=protocol_version),
                "Mcp-Session-Id": session_id,
            },
            json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
            timeout=self._settings.tianyancha_timeout_seconds,
        ).raise_for_status()
        return session_id

    def _ensure_session(self) -> tuple[str, str]:
        last_error: Exception | None = None
        for protocol_version in self._DEFAULT_PROTOCOL_VERSIONS:
            if self._session_id:
                return self._session_id, protocol_version
            try:
                self._session_id = self._start_session(protocol_version=protocol_version)
                return self._session_id, protocol_version
            except Exception as exc:
                last_error = exc
                self._session_id = None
        if last_error is not None:
            raise last_error
        raise RuntimeError("Tianyancha MCP session init failed")

    def _call_tool(self, *, tool_name: str, arguments: dict[str, Any]) -> Any:
        self.last_debug_trace = []
        session_id, protocol_version = self._ensure_session()
        payload = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }
        response = requests.post(
            self._settings.tianyancha_mcp_url,
            headers={
                **self._request_headers(protocol_version=protocol_version),
                "Mcp-Session-Id": session_id,
            },
            json=payload,
            timeout=self._settings.tianyancha_timeout_seconds,
        )
        response.raise_for_status()
        content_type = str(response.headers.get("content-type") or "").lower()
        if "text/event-stream" in content_type:
            raw_text = response.text
            payloads = self._extract_sse_json_objects(raw_text)
            self.last_debug_trace = payloads
            for item in reversed(payloads):
                if isinstance(item, dict) and "result" in item:
                    return item.get("result")
            return payloads[-1] if payloads else {}
        payload = response.json()
        self.last_debug_trace = [payload] if isinstance(payload, dict) else []
        return payload.get("result") if isinstance(payload, dict) else payload

    def _list_tools(self) -> list[dict[str, Any]]:
        session_id, protocol_version = self._ensure_session()
        response = requests.post(
            self._settings.tianyancha_mcp_url,
            headers={
                **self._request_headers(protocol_version=protocol_version),
                "Mcp-Session-Id": session_id,
            },
            json={"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            timeout=self._settings.tianyancha_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        result = payload.get("result") or {}
        tools = result.get("tools") or []
        return [item for item in tools if isinstance(item, dict)]

    def _resolve_tool(self, matcher: Any, fallback_keywords: tuple[str, ...]) -> dict[str, Any] | None:
        try:
            tools = self._list_tools()
        except Exception:
            tools = []
        for tool in tools:
            if matcher(tool):
                return tool
        for tool in tools:
            haystack = " ".join(
                str(tool.get(field) or "").lower() for field in ("name", "title", "description")
            )
            if any(keyword in haystack for keyword in fallback_keywords):
                return tool
        return None

    def _build_lookup_arguments(self, tool: dict[str, Any], lookup_name: str) -> dict[str, Any]:
        input_schema = tool.get("inputSchema")
        properties = {}
        if isinstance(input_schema, dict):
            candidate = input_schema.get("properties")
            if isinstance(candidate, dict):
                properties = candidate

        if "company_name" in properties:
            return {"company_name": lookup_name}
        if "searchKey" in properties:
            return {"searchKey": lookup_name}
        if "company_id" in properties:
            return {"company_name": lookup_name}
        return {"company_name": lookup_name}

    def lookup_company_profile(
        self,
        *,
        brand_name: str | None,
        company_name: str | None,
    ) -> TianyanchaCompanyProfile | None:
        if not self.enabled():
            return None
        resolved_brand_name = self._normalize_str(brand_name)
        resolved_company_name = self._normalize_str(company_name)
        lookup_name = resolved_company_name or resolved_brand_name
        if not lookup_name:
            return None

        tool = self._resolve_tool(
            self._tool_matches_registration_info,
            ("registration", "工商", "登记", "basic", "基本信息"),
        )
        if not tool:
            return None
        tool_name = self._normalize_str(tool.get("name"))
        if not tool_name:
            return None

        try:
            result = self._call_tool(
                tool_name=tool_name,
                arguments=self._build_lookup_arguments(tool, lookup_name),
            )
        except requests.exceptions.HTTPError as exc:
            if self._is_skipable_tool_error(exc):
                self._log_skipable_tool_error(exc=exc, tool_name=tool_name)
                return None
            raise
        payload = self._extract_data_object(result)
        if not payload:
            return None

        profile = TianyanchaCompanyProfile(
            company_name=self._pick_first(payload, ("公司名称", "企业名称", "companyName", "name")),
            english_name=self._pick_first(payload, ("英文名称", "englishName")),
            website=self._pick_first(payload, ("官网", "网址", "website", "webSite")),
            brand_logo=self._pick_first(payload, ("logo", "logo_url", "品牌logo", "品牌LOGO", "brandLogo")),
            company_intro=self._pick_first(payload, ("企业简介", "公司简介", "companyIntro", "intro", "profile")),
            email=self._pick_first(payload, ("邮箱", "email")),
            customer_service_hotline=self._pick_first(payload, ("电话", "联系电话", "客服热线", "phone")),
            official_wechat_account=self._pick_first(payload, ("公众号", "官方微信", "officialWechatAccount")),
            registered_capital=self._pick_first(payload, ("注册资本", "registeredCapital")),
            established_time=self._pick_first(payload, ("成立日期", "成立时间", "establishedTime")),
            company_address=self._pick_first(payload, ("注册地址", "企业地址", "companyAddress", "address")),
            unified_social_credit_code=self._pick_first(payload, ("统一社会信用代码", "creditCode")),
            legal_representative=self._pick_first(payload, ("法定代表人", "legalRepresentative")),
            registration_status=self._pick_first(payload, ("登记状态", "经营状态", "registrationStatus")),
            registration_authority=self._pick_first(payload, ("登记机关", "registrationAuthority")),
            company_type=self._pick_first(payload, ("企业类型", "公司类型", "companyType")),
            industry=self._pick_first(payload, ("所属行业", "行业", "industry")),
            industry_classification=self._pick_first(payload, ("行业分类", "industryClassification")),
            insured_count=self._pick_first(payload, ("参保人数", "insuredCount")),
            personnel_scale=self._pick_first(payload, ("人员规模", "personnelScale")),
            company_tags=self._pick_first(payload, ("标签", "companyTags")),
            approval_date=self._pick_first(payload, ("核准日期", "approvalDate")),
            business_term_start=self._pick_first(payload, ("营业期限自", "businessTermStart")),
            business_term_end=self._pick_first(payload, ("营业期限至", "businessTermEnd")),
        )
        if not self._has_enrichment_fields(profile) and not profile.company_name:
            return None
        return profile

    def lookup_company_management(
        self,
        *,
        brand_name: str | None,
        company_name: str | None,
    ) -> list[TianyanchaManagementMember]:
        if not self.enabled():
            return []
        resolved_brand_name = self._normalize_str(brand_name)
        resolved_company_name = self._normalize_str(company_name)
        lookup_name = resolved_company_name or resolved_brand_name
        if not lookup_name:
            return []

        tool = self._resolve_tool(
            self._tool_matches_management_info,
            ("management", "manager", "高管", "主要人员", "管理层"),
        )
        if not tool:
            return []
        tool_name = self._normalize_str(tool.get("name"))
        if not tool_name:
            return []

        try:
            result = self._call_tool(
                tool_name=tool_name,
                arguments=self._build_lookup_arguments(tool, lookup_name),
            )
        except requests.exceptions.HTTPError as exc:
            if self._is_skipable_tool_error(exc):
                self._log_skipable_tool_error(exc=exc, tool_name=tool_name)
                return []
            raise
        content_text = self._extract_text_content(result)
        if content_text:
            management_text = self._extract_management_markdown_section(content_text)
            table_rows = self._parse_markdown_table_rows(management_text)
            if table_rows:
                rows = table_rows
            else:
                rows = self._extract_data_rows(result)
        else:
            rows = self._extract_data_rows(result)

        members: list[TianyanchaManagementMember] = []
        for item in rows:
            name = self._pick_first(item, ("姓名", "名称", "name"))
            title = self._pick_first(item, ("职位", "职务", "title", "position"))
            profile = self._pick_first(item, ("简介", "profile", "介绍"))
            other_info = self._pick_first(item, ("其他信息", "备注", "otherInfo"))
            if not self._looks_like_management_name(name):
                continue
            if not self._looks_like_management_title(title):
                continue
            members.append(
                TianyanchaManagementMember(
                    name=name,
                    title=title,
                    profile=profile,
                    other_info=other_info,
                )
            )
        return members[:3]
