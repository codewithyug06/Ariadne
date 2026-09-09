# Copyright 2026 The Ariadne Authors
# SPDX-License-Identifier: Apache-2.0
"""ariadne/gateway/url_safety.py: SSRF guard for connect.py's upstream test."""

from __future__ import annotations

import pytest

from ariadne.gateway.url_safety import UnsafeUpstreamURLError, validate_public_upstream_url


class TestRejectsDisallowedAddresses:
    async def test_loopback_ip_literal_rejected(self) -> None:
        with pytest.raises(UnsafeUpstreamURLError, match="disallowed address"):
            await validate_public_upstream_url("http://127.0.0.1/mcp")

    async def test_ipv6_loopback_rejected(self) -> None:
        with pytest.raises(UnsafeUpstreamURLError, match="disallowed address"):
            await validate_public_upstream_url("http://[::1]/mcp")

    async def test_rfc1918_private_ip_rejected(self) -> None:
        with pytest.raises(UnsafeUpstreamURLError, match="disallowed address"):
            await validate_public_upstream_url("http://10.0.0.5/mcp")

    async def test_link_local_metadata_ip_rejected(self) -> None:
        # 169.254.169.254 -- the cloud-metadata address every major provider uses.
        with pytest.raises(UnsafeUpstreamURLError, match="disallowed address"):
            await validate_public_upstream_url("http://169.254.169.254/mcp")

    async def test_unspecified_address_rejected(self) -> None:
        with pytest.raises(UnsafeUpstreamURLError, match="disallowed address"):
            await validate_public_upstream_url("http://0.0.0.0/mcp")  # noqa: S104


class TestSchemeAndHostValidation:
    async def test_non_http_scheme_rejected(self) -> None:
        with pytest.raises(UnsafeUpstreamURLError, match="scheme"):
            await validate_public_upstream_url("ftp://example.com/mcp")

    async def test_unresolvable_host_rejected(self) -> None:
        with pytest.raises(UnsafeUpstreamURLError, match="could not resolve"):
            await validate_public_upstream_url("http://this-should-never-resolve.invalid/mcp")


class TestAllowsPublicAddresses:
    async def test_public_ip_literal_is_allowed(self) -> None:
        # A literal public IP -- no real DNS query happens for a literal
        # address, so this is deterministic without any network access.
        await validate_public_upstream_url("http://8.8.8.8/mcp")
