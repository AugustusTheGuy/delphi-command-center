"""Nextcloud client must use verified HTTPS only."""

from __future__ import annotations

import ssl

from cumulous.nextcloud_client import (
    DEFAULT_HTTPS_URL,
    normalize_https_url,
    ssl_context,
    default_config,
)


def test_normalize_upgrades_http_8080_to_https_8443():
    assert normalize_https_url("http://127.0.0.1:8080") == "https://127.0.0.1:8443"
    assert normalize_https_url("http://192.168.1.100:8080") == "https://192.168.1.100:8443"
    assert normalize_https_url("https://127.0.0.1:8443") == "https://127.0.0.1:8443"


def test_default_config_is_https():
    d = default_config()
    assert d["base_url"].startswith("https://")
    assert d["require_https"] is True
    assert d["tls_insecure"] is False
    assert DEFAULT_HTTPS_URL.startswith("https://")


def test_ssl_context_min_tls12(cumulous_home):
    ctx = ssl_context({"tls_insecure": False, "ca_cert_path": "", "require_https": True})
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


def test_ssl_insecure_only_when_flagged(cumulous_home):
    ctx = ssl_context({"tls_insecure": True})
    assert ctx.verify_mode == ssl.CERT_NONE
