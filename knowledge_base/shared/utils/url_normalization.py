from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .sequence_normalization import normalize_text_sequence

_TRACKING_QUERY_KEYS = frozenset(
    {
        "fbclid",
        "from",
        "gclid",
        "mc_cid",
        "mc_eid",
        "mkt_tok",
        "msclkid",
        "spm",
        "utm_campaign",
        "utm_content",
        "utm_id",
        "utm_medium",
        "utm_source",
        "utm_term",
    }
)


def normalize_http_url(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None

    parsed = urlsplit(text)
    scheme = parsed.scheme.lower()
    if scheme not in {"http", "https"} or not parsed.netloc:
        return None

    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return None

    userinfo = ""
    if parsed.username is not None:
        userinfo = parsed.username
        if parsed.password is not None:
            userinfo = f"{userinfo}:{parsed.password}"
        userinfo = f"{userinfo}@"

    port = parsed.port
    default_port = 80 if scheme == "http" else 443
    netloc = f"{userinfo}{hostname}"
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"

    path = parsed.path or ""
    if path == "/":
        path = ""

    filtered_query_items = [
        (key, query_value)
        for key, query_value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
    ]
    query = urlencode(filtered_query_items, doseq=True)

    return urlunsplit((scheme, netloc, path, query, ""))


def _canonical_hostname_for_identity(hostname: str) -> str:
    normalized_hostname = hostname.casefold()
    if normalized_hostname.startswith("www."):
        return normalized_hostname[4:]
    return normalized_hostname


def _build_http_url_identity(normalized_url: str) -> str:
    parsed = urlsplit(normalized_url)
    hostname = _canonical_hostname_for_identity(parsed.hostname or "")
    port = parsed.port
    netloc = hostname
    if port is not None:
        netloc = f"{netloc}:{port}"
    return urlunsplit(("", netloc, parsed.path, parsed.query, ""))


def _is_better_http_url_candidate(candidate: str, current: str) -> bool:
    candidate_parts = urlsplit(candidate)
    current_parts = urlsplit(current)

    candidate_https = candidate_parts.scheme == "https"
    current_https = current_parts.scheme == "https"
    if candidate_https != current_https:
        return candidate_https

    candidate_hostname = (candidate_parts.hostname or "").casefold()
    current_hostname = (current_parts.hostname or "").casefold()
    candidate_is_www = candidate_hostname.startswith("www.")
    current_is_www = current_hostname.startswith("www.")
    if candidate_is_www != current_is_www:
        return candidate_is_www

    return False


def _merge_equivalent_http_urls(candidate: str, current: str) -> str:
    candidate_parts = urlsplit(candidate)
    current_parts = urlsplit(current)

    preferred_scheme = "https" if (
        candidate_parts.scheme == "https" or current_parts.scheme == "https"
    ) else current_parts.scheme

    candidate_hostname = (candidate_parts.hostname or "").casefold()
    current_hostname = (current_parts.hostname or "").casefold()
    canonical_hostname = _canonical_hostname_for_identity(current_parts.hostname or "")
    preferred_hostname = (
        f"www.{canonical_hostname}"
        if candidate_hostname.startswith("www.") or current_hostname.startswith("www.")
        else canonical_hostname
    )

    preferred_userinfo = ""
    if current_parts.username is not None:
        preferred_userinfo = current_parts.username
        if current_parts.password is not None:
            preferred_userinfo = f"{preferred_userinfo}:{current_parts.password}"
    elif candidate_parts.username is not None:
        preferred_userinfo = candidate_parts.username
        if candidate_parts.password is not None:
            preferred_userinfo = f"{preferred_userinfo}:{candidate_parts.password}"

    netloc = preferred_hostname
    port = current_parts.port if current_parts.port is not None else candidate_parts.port
    default_port = 80 if preferred_scheme == "http" else 443
    if port is not None and port != default_port:
        netloc = f"{netloc}:{port}"
    if preferred_userinfo:
        netloc = f"{preferred_userinfo}@{netloc}"

    return urlunsplit(
        (
            preferred_scheme,
            netloc,
            current_parts.path,
            current_parts.query,
            "",
        )
    )


def normalize_http_url_sequence(value: Any) -> list[str]:
    normalized_urls: list[str] = []
    seen_indexes: dict[str, int] = {}
    for item in normalize_text_sequence(value, split_separators=("\n",)):
        normalized = normalize_http_url(item)
        if not normalized:
            continue
        identity = _build_http_url_identity(normalized)
        existing_index = seen_indexes.get(identity)
        if existing_index is None:
            seen_indexes[identity] = len(normalized_urls)
            normalized_urls.append(normalized)
            continue
        existing_value = normalized_urls[existing_index]
        merged_value = _merge_equivalent_http_urls(normalized, existing_value)
        if merged_value != existing_value:
            normalized_urls[existing_index] = merged_value
            continue
        if _is_better_http_url_candidate(normalized, existing_value):
            normalized_urls[existing_index] = normalized
    return normalized_urls
