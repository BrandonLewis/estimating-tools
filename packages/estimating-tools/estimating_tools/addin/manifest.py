"""The Office XML add-in-only manifest for one Estimate Navigator brand.

Deterministic: the same brand, app URL, slug and version always render the
same bytes, so the committed generic manifest is drift-guarded like the MCP
snippets. There is no separate --brand-url: the brand folder (where
brand.json, assets/ and the manifest's icon/pane URLs point) is derived from
app_url, two levels above it -- the same place the pane's own `brandPath`
resolves to, three levels up from `panes/taskpane.html`. Deriving it keeps
the manifest and the pane from ever disagreeing about where the brand lives.
The add-in id is a UUID5 of that normalised brand folder URL (host
lower-cased, default port dropped), so each deployment keeps one id across
versions and two deployments never share one.
"""
from __future__ import annotations

import re
import uuid
from importlib.resources import files
from string import Template
from urllib.parse import urljoin, urlsplit, urlunsplit
from xml.sax.saxutils import escape

from estimating_tools.addin.brand import ICON_SIZES, SHORT_NAME_MAX

_VERSION = re.compile(r"^\d+\.\d+\.\d+\.\d+$")
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0B\x0C\x0E-\x1F]")
_NAME_MAX = 125
_DESCRIPTION_MAX = 250
#: (field, max length or None) for every brand.json field the manifest reads as text.
_REQUIRED_STRINGS = (
    ("name", _NAME_MAX), ("short_name", SHORT_NAME_MAX), ("provider", None),
    ("description", _DESCRIPTION_MAX), ("support_url", None), ("logo", None),
)


class ManifestError(ValueError):
    """Arguments a manifest cannot be built from."""


def _url(name: str, value: str) -> str:
    if not value.startswith("https://"):
        raise ManifestError(f"--{name} must be an https:// URL (Office requires https)")
    if not value.endswith("/"):
        raise ManifestError(f"--{name} must end with / (it is a folder)")
    return value


def _check_brand(brand: dict) -> None:
    """A brand.json that reached us as raw JSON, not through brand_from_profile's
    own schema-backed checks, might be hand-edited or stale; refuse one that
    would render invalid or dangerous XML, naming the offending field."""
    for field, limit in _REQUIRED_STRINGS:
        value = brand.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ManifestError(f"brand.{field} must be a non-empty string")
        if _CONTROL_CHARS.search(value):
            raise ManifestError(f"brand.{field} contains an XML control character")
        if limit is not None and len(value) > limit:
            raise ManifestError(f"brand.{field} is longer than {limit} characters")
    if not brand["support_url"].startswith("https://"):
        raise ManifestError("brand.support_url must be an https:// URL")


def _host_port(url: str, label: str) -> tuple[str, int | None]:
    parts = urlsplit(url)
    if parts.username or parts.password:
        raise ManifestError(f"{label} must not contain user info")
    host = parts.hostname
    if not host:
        raise ManifestError(f"{label} must have a host")
    return host, parts.port


def _origin(url: str, label: str) -> str:
    host, port = _host_port(url, label)
    return f"https://{host}:{port}" if port and port != 443 else f"https://{host}"


def _brand_id(brand_url: str) -> str:
    host, port = _host_port(brand_url, "app-url")
    netloc = f"{host}:{port}" if port and port != 443 else host
    normalised = urlunsplit(("https", netloc, urlsplit(brand_url).path, "", ""))
    return str(uuid.uuid5(uuid.NAMESPACE_URL, normalised))


def render_manifest(brand: dict, *, app_url: str, version: str, slug: str | None = None) -> str:
    app_url = _url("app-url", app_url)
    if not _VERSION.match(version):
        raise ManifestError(f"--version {version!r} must be four numbers, e.g. 1.0.0.0")
    if slug is not None and not _SLUG.match(slug):
        raise ManifestError(f"--slug {slug!r}: lower-case letters, digits and hyphens only")
    _check_brand(brand)
    # Two levels above app_url: three above panes/taskpane.html, where the
    # pane's own brandPath climbs to resolve the same brand folder.
    brand_url = urljoin(app_url, "../../" + (f"{slug}/" if slug else ""))
    pane = app_url + "panes/taskpane.html" + (f"?brand={slug}" if slug else "")
    values = {
        "id": _brand_id(brand_url),
        "version": version,
        "provider": brand["provider"],
        "name": brand["name"],
        "short_name": brand["short_name"],
        "description": brand["description"],
        "support_url": brand["support_url"],
        "origin": _origin(app_url, "app-url"),
        "pane_url": pane,
        **{f"icon_{n}": brand_url + brand["icons"][str(n)] for n in ICON_SIZES},
    }
    text = files("estimating_tools.addin").joinpath("manifest.xml.tmpl").read_text(encoding="utf-8")
    return Template(text).substitute({k: escape(v, {'"': "&quot;"}) for k, v in values.items()})
