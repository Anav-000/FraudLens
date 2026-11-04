import ipaddress
import urllib.parse
from typing import Optional

import idna
import tldextract

from app.schemas.url_inspection import (
    MAX_URL_LENGTH,
    UrlInspectionResponse,
    UrlObservation,
    UrlObservationLevel,
)


class UrlInspectionError(Exception):
    """
    Sanitized domain exception for URL structure inspection failures.
    Carries safe, structured diagnostic metadata without exposing sensitive credentials.
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


# Threshold for unusually deep subdomain hierarchy
DEEP_SUBDOMAIN_THRESHOLD = 3

# RFC 2606 and RFC 6761 reserved TLDs for testing and invalid targets
RESERVED_TLDS = ("invalid", "test", "example", "localhost")


def _parse_ipv4_number(part: str) -> Optional[int]:
    """
    Parses a single numeric label according to the WHATWG IPv4 parser specification.
    Supports decimal, hexadecimal (0x prefix), and octal (0 prefix with >1 chars).
    Returns integer value or None if parsing fails or invalid digits are present.
    """
    part = part.strip()
    if not part:
        return None
    if part.lower().startswith("0x"):
        hex_digits = part[2:]
        if not hex_digits or not all(c in "0123456789abcdefABCDEF" for c in hex_digits):
            return None
        return int(hex_digits, 16)
    elif len(part) > 1 and part.startswith("0"):
        oct_digits = part[1:]
        if not oct_digits or not all(c in "01234567" for c in oct_digits):
            return None
        return int(oct_digits, 8)
    else:
        if not all(c in "0123456789" for c in part):
            return None
        return int(part, 10)


def _canonicalize_ipv4(host: str) -> Optional[str]:
    """
    Canonicalizes an IPv4 host according to the WHATWG URL Standard IPv4 parser.
    Handles 1 to 4 parts with decimal, octal, or hexadecimal notation.
    Returns standard canonical dotted-decimal string (e.g. '127.0.0.1') or None.
    """
    parts = host.split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    if not (1 <= len(parts) <= 4):
        return None
    numbers = []
    for p in parts:
        n = _parse_ipv4_number(p)
        if n is None:
            return None
        numbers.append(n)

    if len(numbers) == 1:
        if numbers[0] >= 2**32:
            return None
        val = numbers[0]
    elif len(numbers) == 2:
        if numbers[0] >= 256 or numbers[1] >= 2**24:
            return None
        val = (numbers[0] << 24) | numbers[1]
    elif len(numbers) == 3:
        if numbers[0] >= 256 or numbers[1] >= 256 or numbers[2] >= 2**16:
            return None
        val = (numbers[0] << 24) | (numbers[1] << 16) | numbers[2]
    elif len(numbers) == 4:
        if any(n >= 256 for n in numbers):
            return None
        val = (numbers[0] << 24) | (numbers[1] << 16) | (numbers[2] << 8) | numbers[3]
    else:
        return None

    return f"{(val >> 24) & 0xFF}.{(val >> 16) & 0xFF}.{(val >> 8) & 0xFF}.{val & 0xFF}"


def _host_ends_in_number(host: str) -> bool:
    """
    Determines if a hostname ends in a number (decimal or hex) per WHATWG URL Standard.
    If true, the entire host must be parsed as an IPv4 address; failure to parse as
    IPv4 is a fatal validation failure rather than domain fallback.
    """
    parts = host.split(".")
    if len(parts) > 1 and parts[-1] == "":
        parts.pop()
    if not parts:
        return False
    last = parts[-1].strip()
    if last.lower().startswith("0x"):
        return len(last) > 2 and all(c in "0123456789abcdefABCDEF" for c in last[2:])
    return bool(last) and all(c in "0123456789" for c in last)


class UrlInspectorService:
    """
    Performs purely local, offline URL structure inspection.
    Strictly zero network calls, zero DNS resolution, zero HTTP/HTTPS requests,
    zero WHOIS queries, and zero external reputation lookups.
    Uses Python standard library urllib.parse + idna + offline tldextract snapshot.
    """

    def __init__(self) -> None:
        # Strictly configure tldextract for offline operation:
        # cache_dir=None, suffix_list_urls=() disables runtime downloads completely.
        # extra_suffixes includes RFC 2606 reserved testing TLDs so example.invalid domains
        # are reliably parsed without falling back to two-label heuristics.
        self._tld_extractor = tldextract.TLDExtract(
            cache_dir=None,
            suffix_list_urls=(),
            extra_suffixes=list(RESERVED_TLDS),
        )

    def inspect_url(self, raw_url: str) -> UrlInspectionResponse:
        """
        Inspects the structure of a single untrusted URL string.
        Validates scheme, hostname, port, userinfo, IP addresses, IDNA punycode,
        and derives registrable domain using an offline Public Suffix List snapshot.
        """
        # 1. Basic length and emptiness validation
        if not raw_url or not raw_url.strip():
            raise UrlInspectionError(
                code="INVALID_URL",
                message="Submitted URL is empty or contains only whitespace.",
                action="Enter a valid URL starting with 'https://' or 'http://'.",
            )

        if len(raw_url) > MAX_URL_LENGTH:
            raise UrlInspectionError(
                code="URL_TOO_LONG",
                message=f"URL length ({len(raw_url)} characters) exceeds the maximum allowed limit of {MAX_URL_LENGTH} characters.",
                action=f"Shorten the URL to {MAX_URL_LENGTH} characters or fewer.",
            )

        # 2. Control characters and unprintable bytes check
        # We check ord(c) before urllib.parse to prevent silent stripping or normalization
        if any(ord(c) < 32 or ord(c) == 127 for c in raw_url):
            raise UrlInspectionError(
                code="CONTROL_CHARACTERS",
                message="URL contains invalid control characters or unprintable byte sequences.",
                action="Remove line breaks, null bytes, and non-printable control characters from the URL.",
            )

        if any(c.isspace() for c in raw_url):
            raise UrlInspectionError(
                code="MALFORMED_URL",
                message="URL contains embedded whitespace or space characters.",
                action="Remove all whitespace characters from the URL string.",
            )

        # Reject ambiguous backslash characters anywhere in the URL string
        if "\\" in raw_url:
            raise UrlInspectionError(
                code="MALFORMED_URL",
                message="URL contains ambiguous backslash characters ('\\'). FraudLens rejects URLs with backslashes to prevent parser differential discrepancies across browsers.",
                action="Replace backslashes with standard forward slashes '/' or remove them.",
            )

        # 3. Explicit Scheme Validation
        # Require explicit scheme delimiter '://'
        if "://" not in raw_url:
            raise UrlInspectionError(
                code="UNSUPPORTED_SCHEME",
                message="URL is missing an explicit scheme delimiter '://'. FraudLens does not guess or silently repair schemes.",
                action="Add an explicit 'https://' or 'http://' prefix to the URL.",
            )

        try:
            parsed = urllib.parse.urlsplit(raw_url)
        except Exception as split_err:
            raise UrlInspectionError(
                code="MALFORMED_URL",
                message=f"URL failed syntactic parsing: {str(split_err)}.",
                action="Verify that the URL adheres to standard URI syntax (RFC 3986).",
            )

        scheme = parsed.scheme.lower()
        if scheme not in ("http", "https"):
            raise UrlInspectionError(
                code="UNSUPPORTED_SCHEME",
                message=f"URL scheme '{parsed.scheme}' is unsupported. Only explicit 'http' and 'https' schemes are supported.",
                action="Provide a URL that uses 'https://' or 'http://'. Other schemes (ftp, javascript, data, file) are not inspected.",
            )

        # 4. Netloc and Destination Host Validation
        netloc = parsed.netloc
        if not netloc or not netloc.strip():
            raise UrlInspectionError(
                code="MISSING_HOSTNAME",
                message="The URL does not contain a destination host or network location.",
                action="Ensure the URL specifies a valid host (e.g., https://example.com/path).",
            )

        # Extract userinfo (credentials) if present before '@'
        if "@" in netloc:
            userinfo, host_port = netloc.rsplit("@", 1)
            has_userinfo = True
        else:
            userinfo = None
            host_port = netloc
            has_userinfo = False

        if not host_port or not host_port.strip():
            raise UrlInspectionError(
                code="MISSING_HOSTNAME",
                message="The URL netloc contains userinfo but is missing a destination host following the '@' sign.",
                action="Specify the destination host after the '@' sign (e.g., https://user@destination.invalid).",
            )

        # Port extraction and validation
        try:
            port = parsed.port
        except ValueError as port_val_err:
            raise UrlInspectionError(
                code="INVALID_PORT",
                message=f"The URL specifies an invalid non-numeric port: {str(port_val_err)}.",
                action="Provide a valid integer port between 1 and 65535, or omit the port delimiter.",
            )

        if port is not None:
            if port < 1 or port > 65535:
                raise UrlInspectionError(
                    code="INVALID_PORT",
                    message=f"Port number {port} is out of the valid range (1-65535).",
                    action="Ensure the port number is between 1 and 65535.",
                )

        if port is None:
            is_default_port = True
        elif scheme == "http" and port == 80:
            is_default_port = True
        elif scheme == "https" and port == 443:
            is_default_port = True
        else:
            is_default_port = False

        # Hostname extraction
        raw_hostname = parsed.hostname
        if not raw_hostname or not raw_hostname.strip():
            raise UrlInspectionError(
                code="MISSING_HOSTNAME",
                message="The URL destination host is missing or invalid.",
                action="Ensure the URL contains a valid destination hostname or IP address.",
            )

        raw_hostname = raw_hostname.lower().strip()

        # Check for IPv6 literal address
        is_ipv6 = False
        try:
            ip_check = ipaddress.ip_address(raw_hostname)
            if ip_check.version == 6:
                is_ipv6 = True
        except ValueError:
            pass

        # If not IPv6, handle IPv4 address canonicalization per WHATWG URL Standard
        is_non_standard_numeric_ip = False
        original_numeric_host: Optional[str] = None

        if not is_ipv6 and _host_ends_in_number(raw_hostname):
            canonical_ip = _canonicalize_ipv4(raw_hostname)
            if canonical_ip is None:
                raise UrlInspectionError(
                    code="INVALID_HOSTNAME",
                    message=f"Hostname '{raw_hostname}' ends in a number but is not a valid IPv4 address.",
                    action="Specify a valid domain name or standard dotted-decimal IPv4 address (e.g., 127.0.0.1).",
                )
            if raw_hostname != canonical_ip:
                is_non_standard_numeric_ip = True
                original_numeric_host = raw_hostname
                raw_hostname = canonical_ip

        # 5. IP Address Classification
        is_ip_address = False
        ip_version: Optional[int] = None
        ip_scope: Optional[str] = None

        try:
            ip_obj = ipaddress.ip_address(raw_hostname)
            is_ip_address = True
            ip_version = ip_obj.version
            if ip_obj.is_loopback:
                ip_scope = "loopback"
            elif ip_obj.is_private:
                ip_scope = "private"
            elif ip_obj.is_link_local:
                ip_scope = "link_local"
            elif ip_obj.is_multicast:
                ip_scope = "multicast"
            elif ip_obj.is_reserved:
                ip_scope = "reserved"
            else:
                ip_scope = "public"
        except ValueError:
            is_ip_address = False

        # 6. Domain Name Validation & IDNA / Punycode Handling
        if is_ip_address:
            hostname_ascii = raw_hostname
            hostname_unicode = raw_hostname
            is_punycode = False
            registrable_domain = None
            subdomains: list[str] = []
            subdomain_count = 0
        else:
            # Check for invalid characters in domain hostname
            if any(c in raw_hostname for c in ("/", "\\", "?", "#", "@", ":", " ")):
                raise UrlInspectionError(
                    code="INVALID_HOSTNAME",
                    message="Hostname contains invalid path, query, or delimiter characters.",
                    action="Check the destination hostname syntax.",
                )

            # Check for empty labels (consecutive dots)
            labels = raw_hostname.split(".")
            if any(len(label) == 0 for label in labels):
                raise UrlInspectionError(
                    code="INVALID_HOSTNAME",
                    message="Hostname contains empty labels or consecutive dots.",
                    action="Remove consecutive dots from the domain name.",
                )

            # Perform IDNA conversion and validation
            try:
                hostname_ascii = idna.encode(raw_hostname).decode("ascii").lower()
                hostname_unicode = idna.decode(hostname_ascii)
            except idna.IDNAError as idna_err:
                raise UrlInspectionError(
                    code="INVALID_HOSTNAME",
                    message=f"Hostname '{raw_hostname}' failed IDNA domain validation: {str(idna_err)}.",
                    action="Verify that domain labels contain valid Unicode or punycode characters.",
                )

            # Validate DNS label lengths (max 63 octets per label, max 253 total)
            ascii_labels = hostname_ascii.split(".")
            if any(len(label) > 63 for label in ascii_labels):
                raise UrlInspectionError(
                    code="INVALID_HOSTNAME",
                    message="One or more hostname labels exceed the standard DNS limit of 63 characters.",
                    action="Ensure each domain label is 63 characters or fewer.",
                )

            if len(hostname_ascii) > 253:
                raise UrlInspectionError(
                    code="INVALID_HOSTNAME",
                    message=f"Total hostname length ({len(hostname_ascii)} characters) exceeds the DNS limit of 253 characters.",
                    action="Ensure the overall domain name is 253 characters or fewer.",
                )

            is_punycode = any(label.startswith("xn--") for label in ascii_labels)

            # Derive registrable domain using offline Public Suffix List
            ext = self._tld_extractor(hostname_ascii)
            if ext.domain and ext.suffix:
                registrable_domain = f"{ext.domain}.{ext.suffix}"
                subdomains = ext.subdomain.split(".") if ext.subdomain else []
                subdomain_count = len(subdomains)
            else:
                registrable_domain = None
                subdomains = []
                subdomain_count = 0

        # 7. Generate Deterministic Observations
        observations: list[UrlObservation] = []

        # Observation: Plain HTTP
        if scheme == "http":
            observations.append(
                UrlObservation(
                    id="unencrypted_http",
                    title="Unencrypted Connection (HTTP)",
                    level=UrlObservationLevel.INFORMATIONAL,
                    description=(
                        "The URL uses unencrypted HTTP rather than HTTPS. Communication over HTTP is not encrypted in transit. "
                        "Note that using HTTP alone does not prove fraud or malicious intent."
                    ),
                )
            )

        # Observation: Userinfo present
        if has_userinfo:
            observations.append(
                UrlObservation(
                    id="userinfo_present",
                    title="Embedded Authentication / Userinfo in Netloc",
                    level=UrlObservationLevel.CAUTION,
                    description=(
                        f"The URL includes userinfo credentials ('{userinfo}') before an '@' delimiter. "
                        f"In standard web browsers, text preceding '@' is authentication userinfo, NOT the destination website. "
                        f"The actual destination host is '{raw_hostname}'."
                    ),
                )
            )

        # Observation: IP-literal host
        if is_ip_address:
            observations.append(
                UrlObservation(
                    id="ip_literal_host",
                    title="IP Address Hostname",
                    level=UrlObservationLevel.CAUTION,
                    description=(
                        f"The destination host is specified as a direct IP address ('{raw_hostname}') rather than a domain name. "
                        f"Scope: {ip_scope or 'unspecified'}. Direct IP addresses are sometimes used in local network administration "
                        f"or testing, but are uncommon for standard public websites; an IP address is not inherently malicious."
                    ),
                )
            )

            # Observation: Special-use address scope
            if ip_scope in ("private", "loopback", "link_local", "reserved"):
                observations.append(
                    UrlObservation(
                        id="special_use_address",
                        title="Special-Use / Local Address Scope",
                        level=UrlObservationLevel.INFORMATIONAL,
                        description=(
                            f"The destination host belongs to a {ip_scope} address range (per RFC standards). "
                            "This describes the network address classification only; it does not indicate whether "
                            "the host is reachable, online, or active."
                        ),
                    )
                )

            # Observation: Non-standard / obfuscated numeric IP notation
            if is_non_standard_numeric_ip and original_numeric_host:
                observations.append(
                    UrlObservation(
                        id="non_standard_ip_representation",
                        title="Non-Standard / Obfuscated Numeric IP Format",
                        level=UrlObservationLevel.CAUTION,
                        description=(
                            f"The destination host was submitted in non-standard numeric format ('{original_numeric_host}') "
                            f"and was canonicalized to standard IPv4 address '{raw_hostname}', matching modern web browser interpretation. "
                            "Non-standard or obfuscated IP representations (such as integer, octal, hex, or abbreviated notation) "
                            "are frequently used to obscure destination IP addresses."
                        ),
                    )
                )

        # Observation: Punycode / IDNA hostname
        if is_punycode:
            observations.append(
                UrlObservation(
                    id="punycode_hostname",
                    title="Internationalized Domain Name (Punycode)",
                    level=UrlObservationLevel.INFORMATIONAL,
                    description=(
                        f"The domain uses Internationalized Domain Name (IDNA) encoding: Unicode '{hostname_unicode}', "
                        f"ASCII '{hostname_ascii}'. Internationalized domains are legitimate and support non-Latin scripts worldwide, "
                        "but visually similar characters can sometimes be used to mimic other brand names."
                    ),
                )
            )

        # Observation: Explicit non-default port
        if not is_default_port and port is not None:
            observations.append(
                UrlObservation(
                    id="non_default_port",
                    title="Non-Default Network Port",
                    level=UrlObservationLevel.INFORMATIONAL,
                    description=(
                        f"The URL specifies non-default port {port} (standard web ports are 80 for HTTP and 443 for HTTPS). "
                        "Non-default ports are commonly used in development, testing, or administration, and are not inherently malicious."
                    ),
                )
            )

        # Observation: Deep subdomain hierarchy
        if subdomain_count >= DEEP_SUBDOMAIN_THRESHOLD:
            subdomains_str = ", ".join(f"'{s}'" for s in subdomains)
            observations.append(
                UrlObservation(
                    id="deep_subdomain_hierarchy",
                    title="Deep Subdomain Hierarchy",
                    level=UrlObservationLevel.CAUTION,
                    description=(
                        f"The domain contains {subdomain_count} subdomain levels ({subdomains_str}). "
                        "Unusually deep subdomain structures are sometimes used to place familiar brand keywords "
                        "into subdomain labels before an unrelated destination domain."
                    ),
                )
            )

        # 8. Calibrated Summary
        if not observations:
            summary = (
                f"Valid {scheme.upper()} URL pointing to destination host '{raw_hostname}'. "
                "No unusual structural characteristics detected."
            )
        else:
            caution_count = sum(1 for o in observations if o.level == UrlObservationLevel.CAUTION)
            if caution_count > 0:
                summary = (
                    f"URL parsed with destination host '{raw_hostname}'. "
                    f"{len(observations)} structural characteristic(s) noted ({caution_count} caution item(s)). "
                    "Review destination host carefully."
                )
            else:
                summary = (
                    f"URL parsed with destination host '{raw_hostname}'. "
                    f"{len(observations)} informational characteristic(s) noted."
                )

        # Normalize path
        normalized_path = parsed.path if parsed.path else "/"
        query = parsed.query if parsed.query else None
        fragment = parsed.fragment if parsed.fragment else None

        notice = (
            "URL Structure Inspection Only — No external reputation checks, "
            "domain registration lookups, or live network connections performed."
        )

        limitation = (
            "This assessment is based solely on local structural analysis of the submitted URL string. "
            "No network connections, DNS resolutions, external reputation queries, domain ownership checks, "
            "or threat intelligence lookups were performed. Structural inspection cannot determine whether "
            "a destination is safe, benign, or malicious."
        )

        return UrlInspectionResponse(
            submitted_url=raw_url,
            scheme=scheme,
            hostname=raw_hostname,
            hostname_ascii=hostname_ascii,
            hostname_unicode=hostname_unicode,
            port=port,
            is_default_port=is_default_port,
            path=normalized_path,
            query=query,
            fragment=fragment,
            has_userinfo=has_userinfo,
            userinfo=userinfo,
            is_ip_address=is_ip_address,
            ip_version=ip_version,
            ip_scope=ip_scope,
            is_punycode=is_punycode,
            registrable_domain=registrable_domain,
            subdomain_count=subdomain_count,
            subdomains=subdomains,
            observations=observations,
            summary=summary,
            inspection_basis="url_structure_only",
            external_checks_performed=False,
            notice=notice,
            limitation=limitation,
        )
