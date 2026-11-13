import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from app.services.safe_browsing import (
    SafeBrowsingService,
    _parse_cache_duration,
    _parse_provider_response,
    _parse_v4_provider_response,
    MalformedProviderResponse,
    SAFE_BROWSING_V4_URL,
    DEFAULT_CACHE_DURATION_SECONDS,
    MAX_WARNING_FRESHNESS_SECONDS,
    MAX_NEGATIVE_CACHE_SECONDS,
)


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Network access forbidden in offline tests")

    async def blocked_async(*args, **kwargs):
        raise AssertionError("Network access forbidden in offline tests")

    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", blocked)
    monkeypatch.setattr(
        httpx.AsyncHTTPTransport, "handle_async_request", blocked_async
    )

@pytest.fixture
def service():
    instance = SafeBrowsingService(inspector=object())
    instance._strip_fragment_and_canonicalize = lambda url: (url, None)
    return instance


@pytest.fixture
def settings():
    return SimpleNamespace(
        is_safe_browsing_configured=lambda: True,
        safe_browsing_api_key=SimpleNamespace(get_secret_value=lambda: 'offline-dummy'),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body,status,reason', [
    (200, b'', 'unavailable', 'invalid_json'),
    (200, b'  \n', 'unavailable', 'invalid_json'),
    (200, b'<html>not json</html>', 'unavailable', 'invalid_json'),
    (200, b'[]', 'unavailable', 'non_object_json'),
    (200, b'null', 'unavailable', 'non_object_json'),
    (200, b'{"threats":false}', 'unavailable', 'invalid_threats_type'),
    (200, b'{"threats":{}}', 'unavailable', 'invalid_threats_type'),
    (200, b'{"threats":[null]}', 'unavailable', 'invalid_threat_entry'),
    (200, b'{"threats":[{"url":"https://example.com/","threatTypes":[]}]}', 'unavailable', 'invalid_threat_types'),
    (200, b'{"threats":[{"url":"https://example.com/","threatTypes":[123]}]}', 'unavailable', 'invalid_threat_types'),
    (200, b'{"error":{}}', 'unavailable', 'error_in_success_response'),
    (200, b'{"cacheDuration":120}', 'unavailable', 'invalid_cache_duration'),
    (200, b'{"cacheDuration":"bad"}', 'unavailable', 'invalid_cache_duration'),
    (200, b'{"cacheDuration":"3.5s"}', 'no_known_match', None),
    (200, b'{"threats":[],"cacheDuration":"300s"}', 'no_known_match', None),
    (200, b'{}', 'no_known_match', None),
    (200, b'{"threats":[{"url":"https://example.com/","threatTypes":["MALWARE"]}],"cacheDuration":"3.5s"}', 'threat_match', None),
    (204, b'', 'unavailable', None),
    (400, b'<html>error</html>', 'unavailable', None),
    (403, b'<html>error</html>', 'unavailable', None),
    (429, b'<html>error</html>', 'unavailable', None),
    (500, b'<html>error</html>', 'unavailable', None),
])
async def test_wire_response(service, settings, monkeypatch, code, body, status, reason):
    response = httpx.Response(code, content=body)
    get = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, 'get', get)
    result = await service.check_reputation('https://example.com/', True, settings)
    assert result.status == status
    assert result.error_reason == reason
    assert get.await_count == 1
    if status == 'unavailable' or body == b'{}':
        assert not service._cache
    if body == b'{}':
        assert result.expires_at is None


@pytest.mark.parametrize('value,expected', [('3.5s',3.5),('0s',0),('0.5s',0.5),('0.000000001s',0), (None,0)])
def test_duration(value,expected):
    assert _parse_cache_duration(value) == expected


@pytest.mark.parametrize('value', [True, 120, '3', '-1s', 'NaNs', '1.1234567890s'])
def test_invalid_duration(value):
    with pytest.raises(MalformedProviderResponse):
        _parse_cache_duration(value)


@pytest.mark.asyncio
async def test_programming_error_not_provider_failure(service, settings, monkeypatch):
    monkeypatch.setattr(httpx.AsyncClient, 'get', AsyncMock(side_effect=TypeError('local error')))
    with pytest.raises(TypeError):
        await service.check_reputation('https://example.com/', True, settings)


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", [
    "application/x-protobuf",
    "application/x-protobuf; charset=UTF-8",
    "application/protobuf",
    "application/octet-stream",
])
@pytest.mark.parametrize("payload", [
    b"",
    b"\x0a\x19\x0a\x14https://example.com/\x12\x01\x01\x12\x03\x08\xac\x02",
    b"\x12\x03\x08\xac\x02",
    b"\xff\xff\xff",
    b"\x0a\x10abc",
])
async def test_binary_response_fails_closed_service_unavailable(service, settings, monkeypatch, media_type, payload):
    headers = {"Content-Type": media_type}
    response = httpx.Response(200, content=payload, headers=headers)
    get = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    result = await service.check_reputation("https://example.com/", True, settings)
    assert result.status == "unavailable"
    assert result.error_code == "MALFORMED_PROVIDER_RESPONSE"
    assert result.error_reason == "unverified_binary_schema"
    assert not service._cache


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 403, 429, 500])
async def test_binary_provider_errors_service_unavailable(service, settings, monkeypatch, status_code):
    headers = {"Content-Type": "application/x-protobuf"}
    response = httpx.Response(status_code, content=b"error", headers=headers)
    get = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "get", get)

    result = await service.check_reputation("https://example.com/", True, settings)
    assert result.status == "unavailable"
    assert not service._cache


# =============================================================================
# Google Safe Browsing v4 Lookup Contract Tests
# =============================================================================

@pytest.fixture
def settings_v4():
    return SimpleNamespace(
        is_safe_browsing_configured=lambda: True,
        safe_browsing_api_key=SimpleNamespace(get_secret_value=lambda: 'offline-dummy-v4-key'),
        safe_browsing_version='v4',
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('code,body,status,reason', [
    # Malformed & invalid JSON
    (200, b'', 'unavailable', 'invalid_json'),
    (200, b'  \n', 'unavailable', 'invalid_json'),
    (200, b'<html>not json</html>', 'unavailable', 'invalid_json'),
    (200, b'[]', 'unavailable', 'non_object_json'),
    (200, b'null', 'unavailable', 'non_object_json'),
    (200, b'{"matches":false}', 'unavailable', 'invalid_matches_type'),
    (200, b'{"matches":{}}', 'unavailable', 'invalid_matches_type'),
    (200, b'{"matches":"bad"}', 'unavailable', 'invalid_matches_type'),
    (200, b'{"matches":[null]}', 'unavailable', 'invalid_threat_entry'),
    (200, b'{"matches":["MALWARE"]}', 'unavailable', 'invalid_threat_entry'),
    (200, b'{"matches":[{}]}', 'unavailable', 'invalid_threat_types'),
    (200, b'{"matches":[{"threatType":""}]}', 'unavailable', 'invalid_threat_types'),
    (200, b'{"matches":[{"threatType":123}]}', 'unavailable', 'invalid_threat_types'),
    (200, b'{"matches":[{"threatType":"THREAT_TYPE_UNSPECIFIED"}]}', 'unavailable', 'invalid_threat_types'),
    (200, b'{"matches":[{"threatType":"MALWARE","threat":"bad"}]}', 'unavailable', 'invalid_threat_entry'),
    (200, b'{"matches":[{"threatType":"MALWARE","threat":{"url":""}}]}', 'unavailable', 'invalid_threat_url'),
    (200, b'{"matches":[{"threatType":"MALWARE","threat":{"url":123}}]}', 'unavailable', 'invalid_threat_url'),
    (200, b'{"error":{}}', 'unavailable', 'error_in_success_response'),
    (200, b'{"cacheDuration":120}', 'unavailable', 'invalid_cache_duration'),
    (200, b'{"cacheDuration":"bad"}', 'unavailable', 'invalid_cache_duration'),
    (200, b'{"matches":[{"threatType":"MALWARE","cacheDuration":120}]}', 'unavailable', 'invalid_cache_duration'),
    (200, b'{"matches":[{"threatType":"MALWARE","cacheDuration":"bad"}]}', 'unavailable', 'invalid_cache_duration'),
    # Valid no-match responses
    (200, b'{}', 'no_known_match', None),
    (200, b'{"matches":[]}', 'no_known_match', None),
    (200, b'{"matches":[],"cacheDuration":"120s"}', 'no_known_match', None),
    (200, b'{"cacheDuration":"3.5s"}', 'no_known_match', None),
    # Valid match responses
    (200, b'{"matches":[{"threatType":"MALWARE"}]}', 'threat_match', None),
    (200, b'{"matches":[{"threatType":"MALWARE","platformType":"ANY_PLATFORM","threatEntryType":"URL","threat":{"url":"https://example.com/"},"cacheDuration":"300s"}]}', 'threat_match', None),
    (200, b'{"matches":[{"threatType":"SOCIAL_ENGINEERING","cacheDuration":"60s"}]}', 'threat_match', None),
    (200, b'{"matches":[{"threatType":"UNWANTED_SOFTWARE"},{"threatType":"MALWARE"}]}', 'threat_match', None),
    # HTTP non-200 responses
    (204, b'', 'unavailable', None),
    (400, b'<html>error</html>', 'unavailable', None),
    (403, b'<html>error</html>', 'unavailable', None),
    (429, b'<html>error</html>', 'unavailable', None),
    (500, b'<html>error</html>', 'unavailable', None),
    (503, b'<html>error</html>', 'unavailable', None),
])
async def test_v4_wire_response(service, settings_v4, monkeypatch, code, body, status, reason):
    response = httpx.Response(code, content=body)
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = await service.check_reputation('https://example.com/', True, settings_v4)
    assert result.status == status
    assert result.error_reason == reason
    assert post.await_count == 1
    # Confirm that errors NEVER return "No known match"
    if status == 'unavailable':
        assert result.status != 'no_known_match'
        assert not service._cache
        assert result.expires_at is None
    elif b'cacheDuration' in body and (status == 'threat_match' or status == 'no_known_match'):
        assert len(service._cache) == 1
        assert result.expires_at is not None
    else:
        # Documented empty JSON object {} and omitted cacheDuration do not cache using an invented default
        assert not service._cache
        assert result.expires_at is None


@pytest.mark.asyncio
async def test_v4_request_contract_payload_and_headers(service, settings_v4, monkeypatch):
    """Verifies that v4 Lookup sends the exact Google documented POST request structure."""
    post = AsyncMock(return_value=httpx.Response(200, json={}))
    monkeypatch.setattr(httpx.AsyncClient, 'post', post)
    result = await service.check_reputation('https://example.com/test?q=1', True, settings_v4)

    assert result.status == 'no_known_match'
    assert post.await_count == 1
    call_args, call_kwargs = post.call_args
    assert call_args[0] == SAFE_BROWSING_V4_URL
    assert call_kwargs['headers']['x-goog-api-key'] == 'offline-dummy-v4-key'
    assert call_kwargs['headers']['Content-Type'] == 'application/json'
    assert call_kwargs['headers']['Accept'] == 'application/json'
    assert call_kwargs['headers']['User-Agent'] == 'FraudLens/1.0'

    # Check documented v4 request payload
    captured_json = call_kwargs['json']
    assert captured_json is not None
    assert captured_json['client']['clientId'] == 'fraudlens'
    assert captured_json['client']['clientVersion'] == '1.0.0'
    threat_info = captured_json['threatInfo']
    assert 'MALWARE' in threat_info['threatTypes']
    assert 'SOCIAL_ENGINEERING' in threat_info['threatTypes']
    assert threat_info['platformTypes'] == ['ANY_PLATFORM']
    assert threat_info['threatEntryTypes'] == ['URL']
    assert threat_info['threatEntries'] == [{'url': 'https://example.com/test?q=1'}]


@pytest.mark.asyncio
@pytest.mark.parametrize("media_type", [
    "application/x-protobuf",
    "application/x-protobuf; charset=UTF-8",
    "application/protobuf",
    "application/octet-stream",
])
@pytest.mark.parametrize("payload", [
    b"",
    b"\x0a\x19\x0a\x14https://example.com/\x12\x01\x01\x12\x03\x08\xac\x02",
    b"\xff\xff\xff",
])
async def test_v4_binary_response_fails_closed_service_unavailable(service, settings_v4, monkeypatch, media_type, payload):
    headers = {"Content-Type": media_type}
    response = httpx.Response(200, content=payload, headers=headers)
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient, "post", post)

    result = await service.check_reputation("https://example.com/", True, settings_v4)
    assert result.status == "unavailable"
    assert result.error_code == "MALFORMED_PROVIDER_RESPONSE"
    assert result.error_reason == "unverified_binary_schema"
    assert result.status != "no_known_match"
    assert not service._cache


@pytest.mark.asyncio
async def test_v4_cache_duration_rules(service, settings_v4, monkeypatch):
    """
    Verifies v4 provider-specific cache rules:
    - Positive match duration capped at MAX_WARNING_FRESHNESS_SECONDS (1800s).
    - If multiple matches are combined, does not keep the combined result past the earliest match expiry.
    - If any match omits cacheDuration, combined result has duration 0.0 and is not cached.
    - Documented empty JSON object {} returns no_known_match and is NOT cached using an invented default.
    - Explicit top-level cacheDuration in no-match is respected.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    # 1. Match with 3600s cacheDuration capped at 1800s
    match_payload = {
        "matches": [{
            "threatType": "MALWARE",
            "cacheDuration": "3600s",
        }]
    }
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(200, json=match_payload)))
    res_match = await service.check_reputation("https://capped-match.com", True, settings_v4)
    assert res_match.status == "threat_match"
    exp = datetime.fromisoformat(res_match.expires_at)
    diff = (exp - now).total_seconds()
    assert 1700 <= diff <= 1805
    assert len(service._cache) == 1

    await service.clear_cache()

    # 2. Multiple matches combined into one result: earliest match expiry wins (min)
    multi_payload = {
        "matches": [
            {"threatType": "MALWARE", "cacheDuration": "300s"},
            {"threatType": "SOCIAL_ENGINEERING", "cacheDuration": "45s"},
            {"threatType": "UNWANTED_SOFTWARE", "cacheDuration": "120s"},
        ]
    }
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(200, json=multi_payload)))
    res_multi = await service.check_reputation("https://multi-threats.com", True, settings_v4)
    assert res_multi.status == "threat_match"
    assert res_multi.threat_types == ["MALWARE", "SOCIAL_ENGINEERING", "UNWANTED_SOFTWARE"]
    exp_multi = datetime.fromisoformat(res_multi.expires_at)
    diff_multi = (exp_multi - now).total_seconds()
    # Earliest match expiry is 45s, not 300s or 120s
    assert 40 <= diff_multi <= 50
    assert len(service._cache) == 1

    await service.clear_cache()

    # 3. Multiple matches where one match omits cacheDuration: earliest expiry is 0s (not cached)
    mixed_payload = {
        "matches": [
            {"threatType": "MALWARE", "cacheDuration": "300s"},
            {"threatType": "UNWANTED_SOFTWARE"},  # omitted cacheDuration
        ]
    }
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(200, json=mixed_payload)))
    res_mixed = await service.check_reputation("https://mixed-threats.com", True, settings_v4)
    assert res_mixed.status == "threat_match"
    assert res_mixed.expires_at is None
    assert not service._cache  # Not kept past earliest match expiry of 0s

    await service.clear_cache()

    # 4. Documented empty dict {} returns no_known_match but is NOT cached with an invented 300s default
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(200, json={})))
    res_nomatch = await service.check_reputation("https://clean-site.com", True, settings_v4)
    assert res_nomatch.status == "no_known_match"
    assert res_nomatch.threat_types == []
    assert res_nomatch.expires_at is None  # Successful no-match with no provider expiry returns expires_at=null
    assert not service._cache  # Never invent a 300-second TTL

    # 5. No-match with explicit provider cacheDuration IS cached
    monkeypatch.setattr(httpx.AsyncClient, 'post', AsyncMock(return_value=httpx.Response(200, json={"cacheDuration": "120s"})))
    res_nomatch_exp = await service.check_reputation("https://clean-site-explicit.com", True, settings_v4)
    assert res_nomatch_exp.status == "no_known_match"
    exp_explicit = datetime.fromisoformat(res_nomatch_exp.expires_at)
    diff_explicit = (exp_explicit - now).total_seconds()
    assert 115 <= diff_explicit <= 125
    assert len(service._cache) == 1


@pytest.mark.asyncio
async def test_v4_and_v5_cannot_reuse_cached_results(service, monkeypatch):
    """Verifies that v4 and v5 cannot reuse each other's cached results."""
    settings_v4 = SimpleNamespace(
        is_safe_browsing_configured=lambda: True,
        safe_browsing_api_key=SimpleNamespace(get_secret_value=lambda: 'dummy-v4'),
        safe_browsing_version='v4',
    )
    settings_v5 = SimpleNamespace(
        is_safe_browsing_configured=lambda: True,
        safe_browsing_api_key=SimpleNamespace(get_secret_value=lambda: 'dummy-v5'),
        safe_browsing_version='v5',
    )

    url = "https://cross-version-isolation.com/test"

    v4_resp = httpx.Response(200, json={
        "matches": [{"threatType": "MALWARE", "cacheDuration": "300s"}]
    })
    post_mock = AsyncMock(return_value=v4_resp)
    monkeypatch.setattr(httpx.AsyncClient, "post", post_mock)

    # 1. Query under v4 -> populates v4 cache
    res_v4 = await service.check_reputation(url, True, settings_v4)
    assert res_v4.status == "threat_match"
    assert res_v4.threat_types == ["MALWARE"]
    assert res_v4.is_cached is False
    assert post_mock.await_count == 1

    # 2. Query SAME URL under v5 -> MUST NOT reuse v4 cache
    v5_resp = httpx.Response(200, json={
        "threats": [{"url": url, "threatTypes": ["SOCIAL_ENGINEERING"]}],
        "cacheDuration": "300s"
    })
    get_mock = AsyncMock(return_value=v5_resp)
    monkeypatch.setattr(httpx.AsyncClient, "get", get_mock)

    res_v5 = await service.check_reputation(url, True, settings_v5)
    assert res_v5.status == "threat_match"
    assert res_v5.threat_types == ["SOCIAL_ENGINEERING"]
    assert res_v5.is_cached is False  # Must NOT be cached from v4
    assert get_mock.await_count == 1  # Outbound GET call must have occurred

    # 3. Query under v4 again -> served from v4 cache
    res_v4_2 = await service.check_reputation(url, True, settings_v4)
    assert res_v4_2.is_cached is True
    assert res_v4_2.threat_types == ["MALWARE"]
    assert post_mock.await_count == 1

    # 4. Query under v5 again -> served from v5 cache
    res_v5_2 = await service.check_reputation(url, True, settings_v5)
    assert res_v5_2.is_cached is True
    assert res_v5_2.threat_types == ["SOCIAL_ENGINEERING"]
    assert get_mock.await_count == 1


def test_parse_v4_provider_response_unit():
    """Unit tests for _parse_v4_provider_response function."""
    # Valid match with earliest match expiry
    threats, dur = _parse_v4_provider_response({
        "matches": [
            {"threatType": "MALWARE", "cacheDuration": "100s"},
            {"threatType": "SOCIAL_ENGINEERING", "cacheDuration": "50s"},
        ]
    })
    assert threats == ["MALWARE", "SOCIAL_ENGINEERING"]
    assert dur == 50.0  # earliest expiry

    # Valid match with omitted cacheDuration on one match -> earliest expiry is 0.0
    threats, dur = _parse_v4_provider_response({
        "matches": [
            {"threatType": "MALWARE", "cacheDuration": "100s"},
            {"threatType": "SOCIAL_ENGINEERING"},
        ]
    })
    assert threats == ["MALWARE", "SOCIAL_ENGINEERING"]
    assert dur == 0.0

    # Valid no-match empty object: no invented 300s default, returns 0.0
    threats, dur = _parse_v4_provider_response({})
    assert threats == []
    assert dur == 0.0

    # Valid no-match empty matches: returns 0.0
    threats, dur = _parse_v4_provider_response({"matches": []})
    assert threats == []
    assert dur == 0.0

    # Valid no-match with explicit top-level duration
    threats, dur = _parse_v4_provider_response({"matches": [], "cacheDuration": "60s"})
    assert threats == []
    assert dur == 60.0

    # Malformed cases
    with pytest.raises(MalformedProviderResponse, match="non_object_json"):
        _parse_v4_provider_response([])

    with pytest.raises(MalformedProviderResponse, match="error_in_success_response"):
        _parse_v4_provider_response({"error": {}})

    with pytest.raises(MalformedProviderResponse, match="invalid_matches_type"):
        _parse_v4_provider_response({"matches": "not_list"})

    with pytest.raises(MalformedProviderResponse, match="invalid_threat_entry"):
        _parse_v4_provider_response({"matches": ["not_dict"]})

    with pytest.raises(MalformedProviderResponse, match="invalid_threat_types"):
        _parse_v4_provider_response({"matches": [{"threatType": ""}]})

    with pytest.raises(MalformedProviderResponse, match="invalid_threat_types"):
        _parse_v4_provider_response({"matches": [{}]})

    with pytest.raises(MalformedProviderResponse, match="invalid_threat_types"):
        _parse_v4_provider_response({"matches": [{"threatType": "THREAT_TYPE_UNSPECIFIED"}]})

    with pytest.raises(MalformedProviderResponse, match="invalid_threat_url"):
        _parse_v4_provider_response({"matches": [{"threatType": "MALWARE", "threat": {"url": ""}}]})

    with pytest.raises(MalformedProviderResponse, match="invalid_cache_duration"):
        _parse_v4_provider_response({"matches": [{"threatType": "MALWARE", "cacheDuration": "bad"}]})
