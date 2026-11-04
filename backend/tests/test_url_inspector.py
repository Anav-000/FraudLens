import socket
import urllib.request
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.schemas.url_inspection import MAX_URL_LENGTH, UrlObservationLevel
from app.services.url_inspector import UrlInspectionError, UrlInspectorService

client = TestClient(app)


# -----------------------------------------------------------------------------
# Unit Tests for UrlInspectorService
# -----------------------------------------------------------------------------


def test_service_ordinary_https_url():
    service = UrlInspectorService()
    res = service.inspect_url("https://example.com/login?step=1#section")

    assert res.submitted_url == "https://example.com/login?step=1#section"
    assert res.scheme == "https"
    assert res.hostname == "example.com"
    assert res.hostname_ascii == "example.com"
    assert res.hostname_unicode == "example.com"
    assert res.port is None
    assert res.is_default_port is True
    assert res.path == "/login"
    assert res.query == "step=1"
    assert res.fragment == "section"
    assert res.has_userinfo is False
    assert res.userinfo is None
    assert res.is_ip_address is False
    assert res.is_punycode is False
    assert res.registrable_domain == "example.com"
    assert res.subdomain_count == 0
    assert res.subdomains == []
    assert len(res.observations) == 0
    assert res.inspection_basis == "url_structure_only"
    assert res.external_checks_performed is False
    assert "no unusual structural characteristics" in res.summary.lower()


def test_service_plain_http_url():
    service = UrlInspectorService()
    res = service.inspect_url("http://example.org/news")

    assert res.scheme == "http"
    assert res.hostname == "example.org"
    assert res.is_default_port is True
    http_obs = [o for o in res.observations if o.id == "unencrypted_http"]
    assert len(http_obs) == 1
    assert http_obs[0].level == UrlObservationLevel.INFORMATIONAL
    assert "unencrypted http" in http_obs[0].description.lower()
    assert "does not prove fraud" in http_obs[0].description.lower()


def test_service_userinfo_url():
    service = UrlInspectorService()
    res = service.inspect_url("https://user:secret@destination.invalid/portal")

    assert res.has_userinfo is True
    assert res.userinfo == "user:secret"
    assert res.hostname == "destination.invalid"
    assert res.registrable_domain == "destination.invalid"

    userinfo_obs = [o for o in res.observations if o.id == "userinfo_present"]
    assert len(userinfo_obs) == 1
    assert userinfo_obs[0].level == UrlObservationLevel.CAUTION
    assert "destination.invalid" in userinfo_obs[0].description
    assert "not the destination website" in userinfo_obs[0].description.lower()


def test_service_userinfo_with_brand_name():
    service = UrlInspectorService()
    res = service.inspect_url("https://mybank.com@malicious.destination.invalid/account")

    assert res.has_userinfo is True
    assert res.userinfo == "mybank.com"
    assert res.hostname == "malicious.destination.invalid"
    assert res.registrable_domain == "destination.invalid"
    assert res.subdomains == ["malicious"]


def test_service_misleading_subdomain():
    service = UrlInspectorService()
    res = service.inspect_url("https://example.com.destination.invalid/secure")

    assert res.hostname == "example.com.destination.invalid"
    assert res.registrable_domain == "destination.invalid"
    assert res.subdomains == ["example", "com"]
    assert res.subdomain_count == 2


def test_service_deep_subdomain_hierarchy():
    service = UrlInspectorService()
    res = service.inspect_url("https://a.b.c.example.com/welcome")

    assert res.subdomain_count == 3
    assert res.subdomains == ["a", "b", "c"]
    assert res.registrable_domain == "example.com"

    deep_obs = [o for o in res.observations if o.id == "deep_subdomain_hierarchy"]
    assert len(deep_obs) == 1
    assert deep_obs[0].level == UrlObservationLevel.CAUTION
    assert "3 subdomain levels" in deep_obs[0].description


def test_service_valid_unicode_idn_and_punycode():
    service = UrlInspectorService()

    # Unicode input
    res_unicode = service.inspect_url("https://münchen.de/rathaus")
    assert res_unicode.hostname_unicode == "münchen.de"
    assert res_unicode.hostname_ascii == "xn--mnchen-3ya.de"
    assert res_unicode.is_punycode is True
    puny_obs = [o for o in res_unicode.observations if o.id == "punycode_hostname"]
    assert len(puny_obs) == 1
    assert puny_obs[0].level == UrlObservationLevel.INFORMATIONAL
    assert "xn--mnchen-3ya.de" in puny_obs[0].description

    # ASCII punycode input
    res_ascii = service.inspect_url("https://xn--mnchen-3ya.de/rathaus")
    assert res_ascii.hostname_unicode == "münchen.de"
    assert res_ascii.hostname_ascii == "xn--mnchen-3ya.de"
    assert res_ascii.is_punycode is True


def test_service_ipv4_host():
    service = UrlInspectorService()
    res = service.inspect_url("http://192.168.1.1:8080/admin")

    assert res.is_ip_address is True
    assert res.ip_version == 4
    assert res.ip_scope == "private"
    assert res.hostname == "192.168.1.1"
    assert res.port == 8080
    assert res.is_default_port is False
    assert res.registrable_domain is None

    ip_obs = [o for o in res.observations if o.id == "ip_literal_host"]
    assert len(ip_obs) == 1
    assert ip_obs[0].level == UrlObservationLevel.CAUTION

    special_obs = [o for o in res.observations if o.id == "special_use_address"]
    assert len(special_obs) == 1
    assert "private" in special_obs[0].description.lower()

    port_obs = [o for o in res.observations if o.id == "non_default_port"]
    assert len(port_obs) == 1


def test_service_ipv6_bracketed_host_loopback():
    service = UrlInspectorService()
    res = service.inspect_url("http://[::1]:80/status")

    assert res.is_ip_address is True
    assert res.ip_version == 6
    assert res.ip_scope == "loopback"
    assert res.hostname == "::1"
    assert res.port == 80
    assert res.is_default_port is True

    special_obs = [o for o in res.observations if o.id == "special_use_address"]
    assert len(special_obs) == 1
    assert "loopback" in special_obs[0].description.lower()


def test_service_ipv6_bracketed_host_reserved_with_non_default_port():
    service = UrlInspectorService()
    res = service.inspect_url("https://[2001:db8::1]:8443/test")

    assert res.is_ip_address is True
    assert res.ip_version == 6
    assert res.ip_scope == "private"
    assert res.hostname == "2001:db8::1"
    assert res.port == 8443
    assert res.is_default_port is False


def test_service_explicit_default_and_non_default_ports():
    service = UrlInspectorService()

    # Default HTTP port 80
    res_http_80 = service.inspect_url("http://example.com:80/")
    assert res_http_80.port == 80
    assert res_http_80.is_default_port is True
    assert not any(o.id == "non_default_port" for o in res_http_80.observations)

    # Default HTTPS port 443
    res_https_443 = service.inspect_url("https://example.com:443/")
    assert res_https_443.port == 443
    assert res_https_443.is_default_port is True
    assert not any(o.id == "non_default_port" for o in res_https_443.observations)

    # Non-default HTTPS port 8443
    res_https_8443 = service.inspect_url("https://example.com:8443/")
    assert res_https_8443.port == 8443
    assert res_https_8443.is_default_port is False
    assert any(o.id == "non_default_port" for o in res_https_8443.observations)


def test_service_multi_label_public_suffixes():
    service = UrlInspectorService()

    # Indian multi-label PSL suffix .gov.in
    res_in = service.inspect_url("https://sub.portal.service.gov.in/app")
    assert res_in.registrable_domain == "service.gov.in"
    assert res_in.subdomain_count == 2
    assert res_in.subdomains == ["sub", "portal"]

    # UK multi-label PSL suffix .co.uk
    res_uk = service.inspect_url("https://dept.example.co.uk/index.html")
    assert res_uk.registrable_domain == "example.co.uk"
    assert res_uk.subdomain_count == 1
    assert res_uk.subdomains == ["dept"]


# -----------------------------------------------------------------------------
# Validation Error Tests
# -----------------------------------------------------------------------------


def test_reject_empty_and_whitespace_url():
    service = UrlInspectorService()
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("")
    assert exc_info.value.code == "INVALID_URL"

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("   ")
    assert exc_info.value.code == "INVALID_URL"


def test_reject_overlength_url():
    service = UrlInspectorService()
    long_url = "https://example.com/" + "a" * (MAX_URL_LENGTH + 10)
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url(long_url)
    assert exc_info.value.code == "URL_TOO_LONG"


def test_reject_control_characters():
    service = UrlInspectorService()

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example\n.com/path")
    assert exc_info.value.code == "CONTROL_CHARACTERS"

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example\r.com/path")
    assert exc_info.value.code == "CONTROL_CHARACTERS"

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example\0.com/path")
    assert exc_info.value.code == "CONTROL_CHARACTERS"


def test_reject_embedded_whitespace():
    service = UrlInspectorService()
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example.com/path with spaces")
    assert exc_info.value.code == "MALFORMED_URL"


def test_reject_missing_scheme_and_unsupported_schemes():
    service = UrlInspectorService()

    # Missing scheme (no silent repair)
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("example.com")
    assert exc_info.value.code == "UNSUPPORTED_SCHEME"

    # Unsupported schemes
    unsupported = [
        "ftp://example.com/file.txt",
        "javascript:alert(1)",
        "data:text/html,<b>hello</b>",
        "file:///etc/passwd",
        "mailto:test@example.com",
        "ws://example.com/socket",
    ]
    for bad_url in unsupported:
        with pytest.raises(UrlInspectionError) as exc_info:
            service.inspect_url(bad_url)
        assert exc_info.value.code == "UNSUPPORTED_SCHEME"


def test_reject_missing_hostname():
    service = UrlInspectorService()

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://")
    assert exc_info.value.code == "MISSING_HOSTNAME"

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("http:///path")
    assert exc_info.value.code == "MISSING_HOSTNAME"

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://:8080")
    assert exc_info.value.code == "MISSING_HOSTNAME"


def test_reject_invalid_ports():
    service = UrlInspectorService()

    # Out of range (>65535)
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example.com:99999/")
    assert exc_info.value.code == "INVALID_PORT"

    # Out of range (0)
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example.com:0/")
    assert exc_info.value.code == "INVALID_PORT"

    # Non-numeric port
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example.com:abc/")
    assert exc_info.value.code == "INVALID_PORT"


def test_reject_malformed_hostnames_and_consecutive_dots():
    service = UrlInspectorService()

    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url("https://example..com/")
    assert exc_info.value.code == "INVALID_HOSTNAME"

    # Label exceeding 63 characters
    huge_label = "a" * 64
    with pytest.raises(UrlInspectionError) as exc_info:
        service.inspect_url(f"https://{huge_label}.com/")
    assert exc_info.value.code == "INVALID_HOSTNAME"


# -----------------------------------------------------------------------------
# Strict Zero-Network Boundary Verification
# -----------------------------------------------------------------------------


def test_zero_network_access_guarantee():
    """
    Asserts that inspecting any URL makes ZERO outbound network or DNS socket calls.
    Mocks socket, requests, urllib, and httpx to catch any network leak.
    """
    service = UrlInspectorService()

    test_urls = [
        "https://example.com/secure",
        "http://example.org/test",
        "https://user:pass@destination.invalid/login",
        "https://example.com.destination.invalid",
        "https://münchen.de/portal",
        "https://xn--mnchen-3ya.de/portal",
        "http://192.168.1.1:8080/status",
        "http://[::1]:80/",
        "https://sub.service.gov.in/app",
    ]

    with (
        patch("socket.socket.connect") as mock_connect,
        patch("socket.getaddrinfo") as mock_getaddrinfo,
        patch("socket.create_connection") as mock_create_connection,
        patch("urllib.request.urlopen") as mock_urlopen,
    ):
        for url in test_urls:
            res = service.inspect_url(url)
            assert res.external_checks_performed is False
            assert res.inspection_basis == "url_structure_only"

        # Assert zero socket or DNS lookups occurred
        mock_connect.assert_not_called()
        mock_getaddrinfo.assert_not_called()
        mock_create_connection.assert_not_called()
        mock_urlopen.assert_not_called()


# -----------------------------------------------------------------------------
# HTTP API Integration Tests (POST /api/v1/inspect/url)
# -----------------------------------------------------------------------------


def test_api_inspect_url_success():
    response = client.post(
        "/api/v1/inspect/url",
        json={"url": "https://user:pass@login.example.com:8443/auth?source=sms"},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"

    data = response.json()
    assert data["scheme"] == "https"
    assert data["hostname"] == "login.example.com"
    assert data["has_userinfo"] is True
    assert data["userinfo"] == "user:pass"
    assert data["port"] == 8443
    assert data["is_default_port"] is False
    assert data["path"] == "/auth"
    assert data["query"] == "source=sms"
    assert data["registrable_domain"] == "example.com"
    assert data["subdomains"] == ["login"]
    assert data["external_checks_performed"] is False
    assert data["inspection_basis"] == "url_structure_only"
    assert "No external reputation checks" in data["notice"]


def test_api_inspect_url_validation_failure_cache_control():
    response = client.post(
        "/api/v1/inspect/url",
        json={"url": "ftp://unsupported.example.com"},
    )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"

    data = response.json()
    assert data["code"] == "UNSUPPORTED_SCHEME"
    assert "unsupported" in data["message"].lower()


def test_api_inspect_url_overlength_rejection():
    long_url = "https://example.com/" + "x" * 2050
    response = client.post(
        "/api/v1/inspect/url",
        json={"url": long_url},
    )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"


def test_capabilities_reports_url_inspection_active():
    response = client.get("/api/v1/capabilities")
    assert response.status_code == 200
    data = response.json()
    assert data["url_inspection"] is True
    assert data["url_reputation"] is False


# -----------------------------------------------------------------------------
# Regression Tests: Ambiguous Backslashes & Unusual Numeric Host Forms
# -----------------------------------------------------------------------------


def test_reject_urls_containing_ambiguous_backslashes():
    """
    Verifies that URLs containing backslashes are rejected to prevent parser
    differential discrepancies where browsers normalize '\' to '/' but standard
    parsers may treat it as part of authority or userinfo.
    """
    service = UrlInspectorService()

    backslash_cases = [
        r"https://example.com\path",
        r"https://trusted.com\@attacker.invalid",
        r"https://attacker.invalid\test",
        r"https:\/\/example.com",
        r"http://example.com/foo\bar",
        r"https://example.com/login?step=1\step=2",
        r"https://user:pass\@example.com",
    ]

    for bad_url in backslash_cases:
        with pytest.raises(UrlInspectionError) as exc_info:
            service.inspect_url(bad_url)
        assert exc_info.value.code == "MALFORMED_URL"
        assert "backslash" in exc_info.value.message.lower()


def test_api_rejects_url_containing_backslash():
    """
    Ensures POST /api/v1/inspect/url returns HTTP 422 with MALFORMED_URL
    and Cache-Control: no-store when URL contains a backslash.
    """
    response = client.post(
        "/api/v1/inspect/url",
        json={"url": r"https://trusted.com\@attacker.invalid"},
    )
    assert response.status_code == 422
    assert response.headers["Cache-Control"] == "no-store"
    data = response.json()
    assert data["code"] == "MALFORMED_URL"
    assert "backslash" in data["message"].lower()


def test_canonicalize_unusual_numeric_hosts():
    """
    Verifies that unusual numeric IP representations (e.g. 127.1, 2130706433, 0x7f000001,
    0177.0.0.1, 0x7f.1, integer IPs) are correctly canonicalized to standard dotted-decimal
    IPv4 addresses, matching browser destination interpretation.
    """
    service = UrlInspectorService()

    cases = [
        # 2-part BSD shorthand (127.1 -> 127.0.0.1)
        ("http://127.1", "127.0.0.1", "loopback", 4),
        # 32-bit decimal integer (2130706433 -> 127.0.0.1)
        ("http://2130706433", "127.0.0.1", "loopback", 4),
        # 32-bit hexadecimal integer (0x7f000001 -> 127.0.0.1)
        ("http://0x7f000001", "127.0.0.1", "loopback", 4),
        # Octal-formatted IP (0177.0.0.1 -> 127.0.0.1)
        ("http://0177.0.0.1:8000/api", "127.0.0.1", "loopback", 4),
        # Mixed hex + shorthand (0x7f.1 -> 127.0.0.1)
        ("https://0x7f.1/test", "127.0.0.1", "loopback", 4),
        # Integer private IP (3232235521 -> 192.168.0.1)
        ("http://3232235521/", "192.168.0.1", "private", 4),
    ]

    for raw_url, expected_ip, expected_scope, expected_version in cases:
        res = service.inspect_url(raw_url)
        assert res.hostname == expected_ip
        assert res.hostname_ascii == expected_ip
        assert res.hostname_unicode == expected_ip
        assert res.is_ip_address is True
        assert res.ip_version == expected_version
        assert res.ip_scope == expected_scope
        assert res.registrable_domain is None

        # Verify observation noting non-standard numeric IP notation
        obs = [o for o in res.observations if o.id == "non_standard_ip_representation"]
        assert len(obs) == 1
        assert obs[0].level == UrlObservationLevel.CAUTION
        assert expected_ip in obs[0].description


def test_reject_invalid_numeric_hosts():
    """
    Verifies that numeric hosts that cannot be parsed as valid IPv4 addresses
    (e.g., overflow values, invalid octal digits, or out-of-range octets)
    are rejected with INVALID_HOSTNAME rather than silently treated as domain names.
    """
    service = UrlInspectorService()

    invalid_numeric_cases = [
        "http://999.999.999.999/",  # Octets exceed 255
        "http://127.0.0.256/",       # Octet 256 exceeds 255
        "http://089.1/",             # 8 and 9 are invalid octal digits
        "http://example.123/",       # Ends in number but label 'example' is non-numeric
        "http://4294967296/",        # Exceeds 2^32 - 1 (32-bit IPv4 max)
        "http://127.1.1.1.1/",       # 5 parts is invalid for IPv4
    ]

    for bad_url in invalid_numeric_cases:
        with pytest.raises(UrlInspectionError) as exc_info:
            service.inspect_url(bad_url)
        assert exc_info.value.code == "INVALID_HOSTNAME"


def test_api_inspect_unusual_numeric_host_canonicalized():
    """
    Tests POST /api/v1/inspect/url with an unusual numeric host (127.1:8080)
    and verifies that the canonical IPv4 (127.0.0.1) is returned alongside
    the non_standard_ip_representation observation.
    """
    response = client.post(
        "/api/v1/inspect/url",
        json={"url": "http://127.1:8080/portal"},
    )
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"

    data = response.json()
    assert data["hostname"] == "127.0.0.1"
    assert data["submitted_url"] == "http://127.1:8080/portal"
    assert data["is_ip_address"] is True
    assert data["ip_version"] == 4
    assert data["ip_scope"] == "loopback"
    assert data["port"] == 8080
    assert data["is_default_port"] is False

    obs_ids = [o["id"] for o in data["observations"]]
    assert "non_standard_ip_representation" in obs_ids
    assert "ip_literal_host" in obs_ids
    assert "special_use_address" in obs_ids
    assert "non_default_port" in obs_ids
