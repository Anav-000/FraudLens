import asyncio
from datetime import datetime, timezone, timedelta
import hashlib
import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import httpx

from app.core.config import Settings
from app.schemas.url_reputation import (
    UrlReputationResponse,
)
from app.services.url_inspector import UrlInspectorService, UrlInspectionError

logger = logging.getLogger("fraudlens.safe_browsing")

# Fixed Google Safe Browsing v5 endpoint (urls.search)
SAFE_BROWSING_V5_URL = "https://safebrowsing.googleapis.com/v5/urls:search"
SAFE_BROWSING_EXPECTED_HOST = "safebrowsing.googleapis.com"
SAFE_BROWSING_EXPECTED_PATH = "/v5/urls:search"

# Fixed Google Safe Browsing v4 endpoint (threatMatches:find)
SAFE_BROWSING_V4_URL = "https://safebrowsing.googleapis.com/v4/threatMatches:find"
SAFE_BROWSING_V4_EXPECTED_HOST = "safebrowsing.googleapis.com"
SAFE_BROWSING_V4_EXPECTED_PATH = "/v4/threatMatches:find"

# Network & Resource Limits
MAX_RESPONSE_BYTES = 65536  # 64 KiB ceiling
REQUEST_TIMEOUT_SECONDS = 10.0
CONNECT_TIMEOUT_SECONDS = 5.0
MAX_CONCURRENT_REQUESTS = 5

# Caching & Freshness Requirements
MAX_CACHE_ENTRIES = 1000
DEFAULT_CACHE_DURATION_SECONDS = 300  # 5 minutes
MAX_WARNING_FRESHNESS_SECONDS = 1800  # 30 minutes (Google warning freshness rule)
MAX_NEGATIVE_CACHE_SECONDS = 86400  # 24 hours (Google maximum negative cache window)

# Special-use / non-public domains that must never be sent to external providers
SPECIAL_USE_DOMAINS = {
    "localhost",
    "invalid",
    "test",
    "example",
    "local",
    "internal",
    "lan",
    "home.arpa",
}


class UrlReputationError(Exception):
    """
    Sanitized domain exception for URL reputation checking failures.
    Carries machine-readable diagnostic codes without exposing sensitive URLs or credentials.
    """

    def __init__(
        self,
        code: str,
        message: str,
        action: str,
        reason: Optional[str] = None,
        http_status: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.action = action
        self.reason = reason
        self.http_status = http_status


class MalformedProviderResponse(ValueError):
    """Contains only a fixed diagnostic reason, never provider data."""


def _parse_cache_duration(duration_val: Any) -> float:
    # Omitted/null protobuf fields have their default value. Never invent a TTL.
    if duration_val is None:
        return 0.0
    if not isinstance(duration_val, str) or not re.fullmatch(
        r"[0-9]+(?:\.[0-9]{1,9})?s", duration_val
    ):
        raise MalformedProviderResponse("invalid_cache_duration")
    from decimal import Decimal
    seconds = Decimal(duration_val[:-1])
    if seconds > 315576000000:
        raise MalformedProviderResponse("invalid_cache_duration")
    # Round down to datetime precision so caching never exceeds provider expiry.
    return int(min(seconds, Decimal(MAX_NEGATIVE_CACHE_SECONDS)) * 1000000) / 1000000


def _parse_provider_response(data: Any) -> Tuple[List[str], float]:
    if not isinstance(data, dict):
        raise MalformedProviderResponse("non_object_json")
    if "error" in data:
        raise MalformedProviderResponse("error_in_success_response")
    threats = data.get("threats")
    if threats is None:
        threats = []
    if not isinstance(threats, list):
        raise MalformedProviderResponse("invalid_threats_type")
    threat_types = []
    for threat in threats:
        if not isinstance(threat, dict):
            raise MalformedProviderResponse("invalid_threat_entry")
        if not isinstance(threat.get("url"), str) or not threat["url"]:
            raise MalformedProviderResponse("invalid_threat_url")
        types = threat.get("threatTypes", threat.get("threat_types"))
        if not isinstance(types, list) or not types or any(
            not isinstance(t, str) or not t.strip() or t == "THREAT_TYPE_UNSPECIFIED"
            for t in types
        ):
            raise MalformedProviderResponse("invalid_threat_types")
        threat_types.extend(types)
    duration = _parse_cache_duration(data.get("cacheDuration", data.get("cache_duration")))
    return threat_types, duration


def _parse_v4_provider_response(data: Any) -> Tuple[List[str], float]:
    if not isinstance(data, dict):
        raise MalformedProviderResponse("non_object_json")
    if "error" in data:
        raise MalformedProviderResponse("error_in_success_response")
    matches = data.get("matches")
    if matches is None:
        matches = []
    if not isinstance(matches, list):
        raise MalformedProviderResponse("invalid_matches_type")

    threat_types: List[str] = []
    durations: List[float] = []

    for match in matches:
        if not isinstance(match, dict):
            raise MalformedProviderResponse("invalid_threat_entry")
        threat_type = match.get("threatType", match.get("threat_type"))
        if not isinstance(threat_type, str) or not threat_type.strip() or threat_type == "THREAT_TYPE_UNSPECIFIED":
            raise MalformedProviderResponse("invalid_threat_types")
        threat_types.append(threat_type.strip())

        threat_entry = match.get("threat")
        if threat_entry is not None:
            if not isinstance(threat_entry, dict):
                raise MalformedProviderResponse("invalid_threat_entry")
            url_val = threat_entry.get("url")
            if not isinstance(url_val, str) or not url_val:
                raise MalformedProviderResponse("invalid_threat_url")

        # Documented per-match cacheDuration
        cd = match.get("cacheDuration", match.get("cache_duration"))
        dur = _parse_cache_duration(cd)
        durations.append(dur)

    # Validate top-level cacheDuration if present
    top_cd = data.get("cacheDuration", data.get("cache_duration"))
    top_duration = _parse_cache_duration(top_cd) if top_cd is not None else None

    if threat_types:
        # Per-match cacheDuration: if multiple matches are combined into one cached result,
        # do not keep the combined result past the earliest match expiry.
        # Earliest expiry is min(durations); if any match omitted cacheDuration, dur is 0.0.
        match_duration = min(durations) if durations else 0.0
        return threat_types, match_duration
    else:
        # Documented empty JSON object {} or {"matches": []}:
        # Do not cache that result using an invented 300-second default.
        # If top-level cacheDuration is explicitly provided, use it; otherwise 0.0.
        neg_duration = top_duration if top_duration is not None else 0.0
        return [], neg_duration


class SafeBrowsingService:
    """
    Client for Google Safe Browsing API v5 (urls.search).
    Enforces strict zero-leakage privacy boundaries, in-memory hashed caching,
    bounded timeouts, bounded concurrency, and non-automatic retry policies.
    """

    def __init__(self, inspector: Optional[UrlInspectorService] = None) -> None:
        self._inspector = inspector or UrlInspectorService()
        self._cache: Dict[str, Tuple[UrlReputationResponse, datetime, datetime]] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

    def _strip_fragment_and_canonicalize(self, raw_url: str) -> Tuple[str, any]:
        """
        Validates URL using Phase 4A structural validation and builds the exact
        checked_url with the fragment stripped and path/query preserved.
        """
        inspected = self._inspector.inspect_url(raw_url)

        # 1. Reject embedded credentials / userinfo
        if inspected.has_userinfo:
            raise UrlReputationError(
                code="FORBIDDEN_DESTINATION",
                reason="embedded_credentials",
                message="URLs containing embedded usernames or credentials (@) cannot be submitted for reputation checking.",
                action="Remove user credentials from the URL before checking reputation.",
            )

        # 2. Reject non-public IP literals
        if inspected.is_ip_address and inspected.ip_scope != "public":
            raise UrlReputationError(
                code="FORBIDDEN_DESTINATION",
                reason="non_public_ip",
                message=f"Private, loopback, or reserved IP destinations ({inspected.hostname}) cannot be submitted for external reputation checking.",
                action="Provide a URL pointing to a public domain name or public IP address.",
            )

        # 3. Reject local and special-use domain destinations (without DNS resolution)
        hostname_lower = inspected.hostname.lower()
        is_special_use = (
            hostname_lower in SPECIAL_USE_DOMAINS
            or any(hostname_lower.endswith(f".{suffix}") for suffix in SPECIAL_USE_DOMAINS)
            or ("." not in hostname_lower and not inspected.is_ip_address)
        )
        if is_special_use:
            raise UrlReputationError(
                code="FORBIDDEN_DESTINATION",
                reason="special_use_domain",
                message=f"Local, testing, or special-use domain '{inspected.hostname}' cannot be submitted for external reputation checking.",
                action="Provide a URL with a standard public internet domain name.",
            )

        # Build checked URL with fragment strictly stripped
        port_part = f":{inspected.port}" if (inspected.port and not inspected.is_default_port) else ""
        path = inspected.path if inspected.path else "/"
        query_part = f"?{inspected.query}" if inspected.query else ""
        checked_url = f"{inspected.scheme}://{inspected.hostname_ascii}{port_part}{path}{query_part}"

        return checked_url, inspected

    async def _lookup_cache(self, cache_key: str, now: datetime) -> Optional[UrlReputationResponse]:
        """
        Thread-safe lookup in the bounded in-memory hashed cache.
        Evicts expired entries and checks 30-minute warning freshness.
        """
        async with self._lock:
            entry = self._cache.get(cache_key)
            if not entry:
                return None
            cached_response, cached_at, expires_at = entry

            if now >= expires_at:
                # Expired according to provider cacheDuration
                del self._cache[cache_key]
                return None

            # Check 30-minute freshness rule for Google Safe Browsing
            age_seconds = (now - cached_at).total_seconds()
            is_stale = age_seconds > MAX_WARNING_FRESHNESS_SECONDS

            # Return a copy marked as cached
            return cached_response.model_copy(
                update={"is_cached": True, "is_stale": is_stale}
            )

    async def _store_cache(
        self,
        cache_key: str,
        response: UrlReputationResponse,
        cached_at: datetime,
        expires_at: datetime,
    ) -> None:
        """
        Thread-safe bounded insertion into hashed in-memory cache.
        """
        async with self._lock:
            # If at capacity, purge all expired entries first
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                expired_keys = [k for k, (_, _, exp) in self._cache.items() if cached_at >= exp]
                for k in expired_keys:
                    del self._cache[k]

            # If still at capacity, evict the oldest entry
            if len(self._cache) >= MAX_CACHE_ENTRIES:
                oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k][1])
                del self._cache[oldest_key]

            self._cache[cache_key] = (response, cached_at, expires_at)

    async def clear_cache(self) -> None:
        """Clears all entries from the in-memory cache."""
        async with self._lock:
            self._cache.clear()

    async def check_reputation(
        self,
        raw_url: str,
        consent: bool,
        settings: Settings,
    ) -> UrlReputationResponse:
        """
        Checks URL reputation against Google Safe Browsing v5 urls.search.
        Requires explicit consent. Operates only on fixed Google endpoint.
        """
        # Explicit user consent validation
        if not consent:
            raise UrlReputationError(
                code="CONSENT_REQUIRED",
                message="Explicit consent is required to check URL reputation against Google Safe Browsing.",
                action="Review the privacy disclosure and check the consent box to proceed.",
                http_status=422,
            )

        # Validate URL and strip fragment
        checked_url, _ = self._strip_fragment_and_canonicalize(raw_url)

        # Verify backend configuration
        if not settings.is_safe_browsing_configured():
            raise UrlReputationError(
                code="SERVICE_UNAVAILABLE",
                reason="provider_unconfigured",
                message="Google Safe Browsing is not configured on this server.",
                action="Set SAFE_BROWSING_API_KEY in the backend environment to enable reputation checks.",
                http_status=503,
            )

        api_key = settings.safe_browsing_api_key.get_secret_value()

        version = getattr(settings, "safe_browsing_version", "v5")
        if isinstance(version, str):
            version = version.strip().lower()
        if version not in ("v4", "v5"):
            version = "v5"

        # Generate hashed cache key (SHA-256) partitioned by version
        cache_key = hashlib.sha256(f"{version}:{checked_url}".encode("utf-8")).hexdigest()
        now = datetime.now(timezone.utc)

        # Check in-memory cache
        cached_match = await self._lookup_cache(cache_key, now)
        if cached_match is not None:
            return cached_match

        # Execute bounded outbound query to Google Safe Browsing endpoint
        now_iso = now.isoformat()
        try:
            async with self._semaphore:
                # Bounded timeout: 10.0s total, 5.0s connect
                timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=CONNECT_TIMEOUT_SECONDS)
                # Transport with zero automatic retries
                transport = httpx.AsyncHTTPTransport(retries=0)

                async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
                    if version == "v4":
                        # Explicit assertion: connect only to fixed Google v4 endpoint
                        parsed_endpoint = urllib.parse.urlsplit(SAFE_BROWSING_V4_URL)
                        if (
                            parsed_endpoint.netloc != SAFE_BROWSING_V4_EXPECTED_HOST
                            or parsed_endpoint.path != SAFE_BROWSING_V4_EXPECTED_PATH
                        ):
                            raise UrlReputationError(
                                code="SECURITY_VIOLATION",
                                message="Outbound target does not match authorized Google Safe Browsing endpoint.",
                                action="Verify service configuration.",
                                http_status=500,
                            )

                        headers = {
                            "x-goog-api-key": api_key,
                            "User-Agent": "FraudLens/1.0",
                            "Content-Type": "application/json",
                            "Accept": "application/json",
                        }
                        payload = {
                            "client": {
                                "clientId": "fraudlens",
                                "clientVersion": "1.0.0",
                            },
                            "threatInfo": {
                                "threatTypes": [
                                    "MALWARE",
                                    "SOCIAL_ENGINEERING",
                                    "UNWANTED_SOFTWARE",
                                    "POTENTIALLY_HARMFUL_APPLICATION",
                                ],
                                "platformTypes": ["ANY_PLATFORM"],
                                "threatEntryTypes": ["URL"],
                                "threatEntries": [{"url": checked_url}],
                            },
                        }
                        # Redacted logging (no raw URL, API key, or query tokens)
                        logger.info("Outbound Safe Browsing query initiated for version=v4 hash=%s", cache_key[:12])
                        resp = await client.post(SAFE_BROWSING_V4_URL, json=payload, headers=headers)
                    else:
                        # Explicit assertion: connect only to fixed Google v5 endpoint
                        parsed_endpoint = urllib.parse.urlsplit(SAFE_BROWSING_V5_URL)
                        if (
                            parsed_endpoint.netloc != SAFE_BROWSING_EXPECTED_HOST
                            or parsed_endpoint.path != SAFE_BROWSING_EXPECTED_PATH
                        ):
                            raise UrlReputationError(
                                code="SECURITY_VIOLATION",
                                message="Outbound target does not match authorized Google Safe Browsing endpoint.",
                                action="Verify service configuration.",
                                http_status=500,
                            )

                        headers = {
                            "x-goog-api-key": api_key,
                            "User-Agent": "FraudLens/1.0",
                            "Accept": "application/json",
                        }
                        params = {"urls": checked_url}

                        # Redacted logging (no raw URL, API key, or query tokens)
                        logger.info("Outbound Safe Browsing query initiated for version=v5 hash=%s", cache_key[:12])
                        resp = await client.get(SAFE_BROWSING_V5_URL, params=params, headers=headers)

                    # Bounded response size check
                    content_length = len(resp.content)
                    if content_length > MAX_RESPONSE_BYTES:
                        logger.warning("Provider response exceeded byte limit (bytes=%d)", content_length)
                        return UrlReputationResponse(
                            status="unavailable",
                            checked_url=checked_url,
                            checked_at=now_iso,
                            summary="Google Safe Browsing returned a response that exceeded safe size limits.",
                            error_code="RESPONSE_TOO_LARGE",
                            error_message="The provider response was larger than expected.",
                            error_action="Retry the check or inspect the URL structure locally.",
                        )

                    logger.warning(
                        "Safe Browsing response: status=%s bytes=%s content_type=%r content_encoding=%r",
                        resp.status_code,
                        content_length,
                        resp.headers.get("content-type", "(missing)"),
                        resp.headers.get("content-encoding", "(missing)"),
                    )

                    # Handle HTTP status codes
                    if resp.status_code == 200:
                        content_type_header = resp.headers.get("content-type", "")
                        content_type = content_type_header if isinstance(content_type_header, str) else ""
                        media_type = content_type.split(";")[0].strip().lower()

                        # Without an authoritative, published wire schema for v5 urls:search,
                        # binary protobuf payloads cannot be safely decoded and must fail closed.
                        if media_type in ("application/x-protobuf", "application/protobuf", "application/octet-stream"):
                            logger.warning(
                                "Safe Browsing binary response rejected: unverified_wire_schema status=200 bytes=%d content_type=%r",
                                content_length,
                                content_type,
                            )
                            return UrlReputationResponse(
                                status="unavailable",
                                checked_url=checked_url,
                                checked_at=now_iso,
                                summary="Google Safe Browsing returned a binary protobuf response for which no verified wire schema is published.",
                                error_code="MALFORMED_PROVIDER_RESPONSE",
                                error_reason="unverified_binary_schema",
                                error_message="The provider returned binary data (application/x-protobuf) which cannot be decoded without a verified protobuf schema.",
                                error_action="Inspect sanitized server diagnostics; use local inspection meanwhile.",
                            )

                        try:
                            data = resp.json()
                        except (json.JSONDecodeError, UnicodeDecodeError):
                            logger.warning(
                                "Safe Browsing response rejected: reason=invalid_json status=200 bytes=%d",
                                content_length,
                            )
                            return UrlReputationResponse(
                                status="unavailable",
                                checked_url=checked_url,
                                checked_at=now_iso,
                                summary="Google Safe Browsing returned an unparseable response.",
                                error_code="MALFORMED_PROVIDER_RESPONSE",
                                error_reason="invalid_json",
                                error_message="The provider response was not valid JSON.",
                                error_action="Inspect sanitized server diagnostics; use local inspection meanwhile.",
                            )
                        try:
                            if version == "v4":
                                threat_types, duration_secs = _parse_v4_provider_response(data)
                            else:
                                threat_types, duration_secs = _parse_provider_response(data)
                        except MalformedProviderResponse as exc:
                            logger.warning(
                                "Safe Browsing response rejected: reason=%s status=200 bytes=%d",
                                str(exc),
                                content_length,
                            )
                            return UrlReputationResponse(
                                status="unavailable",
                                checked_url=checked_url,
                                checked_at=now_iso,
                                summary="Google Safe Browsing returned an invalid response structure.",
                                error_code="MALFORMED_PROVIDER_RESPONSE",
                                error_reason=str(exc),
                                error_message="The provider JSON did not match the expected response structure.",
                                error_action="Inspect sanitized server diagnostics; use local inspection meanwhile.",
                            )

                        if threat_types:
                            # Threat match detected
                            unique_threats = sorted(set(threat_types))
                            # Cap match caching to 30 minutes to satisfy warning freshness requirements
                            if duration_secs > 0:
                                effective_duration = min(duration_secs, MAX_WARNING_FRESHNESS_SECONDS)
                                expires_at_dt = now + timedelta(seconds=effective_duration)
                                expires_at_iso = expires_at_dt.isoformat()
                            else:
                                effective_duration = 0.0
                                expires_at_dt = None
                                expires_at_iso = None

                            result = UrlReputationResponse(
                                status="threat_match",
                                checked_url=checked_url,
                                checked_at=now_iso,
                                expires_at=expires_at_iso,
                                is_cached=False,
                                is_stale=False,
                                threat_types=unique_threats,
                                summary=f"Google Safe Browsing reported this URL matches known threat categories: {', '.join(unique_threats)}. Google Safe Browsing does not guarantee that all threats are detected or that findings are error-free.",
                            )
                            if effective_duration > 0 and expires_at_dt is not None:
                                await self._store_cache(cache_key, result, now, expires_at_dt)
                            return result
                        else:
                            # No threat match found
                            if duration_secs > 0:
                                effective_duration = min(duration_secs, MAX_NEGATIVE_CACHE_SECONDS)
                                expires_at_dt = now + timedelta(seconds=effective_duration)
                                expires_at_iso = expires_at_dt.isoformat()
                            else:
                                effective_duration = 0.0
                                expires_at_dt = None
                                expires_at_iso = None

                            result = UrlReputationResponse(
                                status="no_known_match",
                                checked_url=checked_url,
                                checked_at=now_iso,
                                expires_at=expires_at_iso,
                                is_cached=False,
                                is_stale=False,
                                threat_types=[],
                                summary="No known threat match was returned. This does not prove the URL is safe.",
                            )
                            if effective_duration > 0 and expires_at_dt is not None:
                                await self._store_cache(cache_key, result, now, expires_at_dt)
                            return result

                    elif resp.status_code == 400:
                        return UrlReputationResponse(
                            status="unavailable",
                            checked_url=checked_url,
                            checked_at=now_iso,
                            summary="Google Safe Browsing rejected the request parameters.",
                            error_code="PROVIDER_REQUEST_ERROR",
                            error_message="The request could not be processed by Google Safe Browsing.",
                            error_action="Verify URL format and retry.",
                        )
                    elif resp.status_code == 403:
                        return UrlReputationResponse(
                            status="unavailable",
                            checked_url=checked_url,
                            checked_at=now_iso,
                            summary="Google Safe Browsing authentication failed.",
                            error_code="PROVIDER_AUTHENTICATION_FAILED",
                            error_message="Google Safe Browsing rejected the API key or authorization.",
                            error_action="Check server SAFE_BROWSING_API_KEY configuration.",
                        )
                    elif resp.status_code == 429:
                        return UrlReputationResponse(
                            status="unavailable",
                            checked_url=checked_url,
                            checked_at=now_iso,
                            summary="Google Safe Browsing rate limit or quota exceeded.",
                            error_code="PROVIDER_QUOTA_EXCEEDED",
                            error_message="The Safe Browsing request quota has been exhausted.",
                            error_action="Wait a few minutes before checking reputation again.",
                        )
                    else:
                        return UrlReputationResponse(
                            status="unavailable",
                            checked_url=checked_url,
                            checked_at=now_iso,
                            summary=f"Google Safe Browsing returned HTTP status {resp.status_code}.",
                            error_code="PROVIDER_SERVER_ERROR",
                            error_message="The provider service encountered an error.",
                            error_action="Retry the check later.",
                        )

        except httpx.TimeoutException:
            logger.warning("Safe Browsing request timed out for hash=%s", cache_key[:12])
            return UrlReputationResponse(
                status="unavailable",
                checked_url=checked_url,
                checked_at=now_iso,
                summary="Google Safe Browsing request timed out after 10 seconds.",
                error_code="PROVIDER_TIMEOUT",
                error_message="The reputation check timed out while contacting Google Safe Browsing.",
                error_action="Check your network connection and retry.",
            )
        except httpx.RequestError:
            logger.warning("Safe Browsing network error for hash=%s", cache_key[:12])
            return UrlReputationResponse(
                status="unavailable",
                checked_url=checked_url,
                checked_at=now_iso,
                summary="Could not establish connection to Google Safe Browsing endpoint.",
                error_code="PROVIDER_NETWORK_ERROR",
                error_message="Network connectivity error while contacting Google Safe Browsing.",
                error_action="Verify outbound internet connectivity and retry.",
            )
        # Local programming errors propagate to the route's sanitized HTTP 500 handler.
