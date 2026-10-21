"""Brand files for Estimate Navigator.

`brand_from_profile` writes the content of a deployment's brand.json from an
org profile's optional `brand:` section, falling back to the profile name, the
letterhead logo and the generic brand. `workbook_brand` is the much smaller
stamp `est-estimate build` writes into a workbook: name and colours only.
"""
from __future__ import annotations

import copy
import json
import re
import shutil
from importlib.resources import files
from pathlib import Path

ICON_SIZES = (16, 32, 64, 80, 128)
TOKENS = ("accent", "on_accent", "surface", "text", "muted", "line")
SHORT_NAME_MAX = 16
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_PNG_MAGIC = b"\x89PNG"

GENERIC = {
    "name": "Estimate Navigator",
    "short_name": "Est. Navigator",
    "provider": "Anvil Rock Road",
    "description": "Navigate, check and edit estimate workbooks built by est-estimate.",
    "support_url": "https://anvilrockroad.com/excel/addons/support.html",
    "logo": "assets/logo.svg",
    "icons": {str(n): f"assets/icon-{n}.png" for n in ICON_SIZES},
    "colors": {
        "light": {"accent": "#24507A", "on_accent": "#FFFFFF", "surface": "#FFFFFF",
                  "text": "#1F2328", "muted": "#5B616B", "line": "#D5D9DF"},
        "dark": {"accent": "#7FB0E0", "on_accent": "#0E1A26", "surface": "#1F1F1F",
                 "text": "#E8E8E8", "muted": "#B3B0AD", "line": "#3B3A39"},
    },
}


class BrandError(ValueError):
    """A brand that cannot be built."""


def _non_blank(value) -> str | None:
    """`value` stripped, or None if it is not a string or is blank."""
    if isinstance(value, str):
        stripped = value.strip()
        if stripped:
            return stripped
    return None


def _truncate_at_word_boundary(text: str, limit: int) -> str:
    """`text` cut to `limit` characters, backing up to the last space in range
    when there is one, so a short_name never ends mid-word."""
    cut = text[:limit]
    last_space = cut.rfind(" ")
    if last_space > 0:
        return cut[:last_space]
    return cut.rstrip()


def render_names(sect: dict, profile_name: str | None) -> dict:
    """name and short_name: the brand's own, else the profile's, else generic.

    A blank or whitespace-only name or short_name counts as missing. An
    over-length name is cut at a word boundary when one exists in range."""
    name = _non_blank(sect.get("name")) or _non_blank(profile_name) or GENERIC["name"]
    short = _non_blank(sect.get("short_name"))
    if short is None:
        short = name if len(name) <= SHORT_NAME_MAX else _truncate_at_word_boundary(name, SHORT_NAME_MAX)
    if len(short) > SHORT_NAME_MAX:
        raise BrandError(f"brand.short_name {short!r} is longer than {SHORT_NAME_MAX} characters")
    return {"name": name, "short_name": short}


def _copy(src: str, out_dir: Path, name: str) -> str:
    dest = Path(out_dir) / "assets" / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src, dest)
    return f"assets/{name}"


def _copy_generic(relative: str, out_dir: Path) -> None:
    dest = Path(out_dir) / relative
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(files("estimating_tools.addin").joinpath(relative).read_bytes())


def _copy_icon(field: str, src: str, out_dir: Path, name: str) -> str:
    try:
        head = Path(src).open("rb").read(len(_PNG_MAGIC))
    except OSError as exc:
        raise BrandError(f"brand.{field}: {src!r} could not be read: {exc}") from exc
    if not head.startswith(_PNG_MAGIC):
        raise BrandError(f"brand.{field}: {src!r} is not a PNG file (missing \\x89PNG magic bytes)")
    return _copy(src, out_dir, name)


def brand_from_profile(profile, out_dir) -> dict:
    """brand.json content for `profile`, copying its logo and icons into `out_dir/assets`.

    A profile with no `brand:` section is always the generic brand, even when
    it has a name: a branded build needs its own brand: section, and the
    profile name and letterhead logo are only consulted as fallbacks once one
    is present. A branded build must carry all of its own icons: a client's
    ribbon never shows the generic mark.
    """
    sect = profile.section("brand")
    b = copy.deepcopy(GENERIC)
    if not sect:
        for relative in (b["logo"], *b["icons"].values()):
            _copy_generic(relative, out_dir)
        return b
    b.update(render_names(sect, profile.data.get("name")))
    for key in ("provider", "description", "support_url"):
        if sect.get(key):
            b[key] = sect[key]
    logo = sect.get("logo") or profile.section("letterhead").get("logo")
    if logo:
        b["logo"] = _copy(logo, out_dir, "logo" + Path(logo).suffix.lower())
    else:
        _copy_generic(b["logo"], out_dir)
    missing = [f"icon_{n}" for n in ICON_SIZES if not sect.get(f"icon_{n}")]
    if missing:
        raise BrandError(f"a branded build needs its own icons; the profile's brand: "
                         f"section lacks {', '.join(missing)}")
    for n in ICON_SIZES:
        field = f"icon_{n}"
        b["icons"][str(n)] = _copy_icon(field, sect[field], out_dir, f"icon-{n}.png")
    for mode in ("light", "dark"):
        b["colors"][mode].update((sect.get("colors") or {}).get(mode) or {})
        for token, value in b["colors"][mode].items():
            if token not in TOKENS or not _HEX.match(value):
                raise BrandError(f"brand.colors.{mode}.{token}: {value!r} is not a #RRGGBB colour")
    if sect.get("heuristic"):
        b["heuristic"] = dict(sect["heuristic"])
    return b


def write_brand(brand: dict, out_dir) -> Path:
    path = Path(out_dir) / "brand.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(brand, indent=2) + "\n", encoding="utf-8", newline="\n")
    return path


def workbook_brand(profile):
    """The brand stamp for a workbook: the profile's brand name and colours, or None.

    Only what restyles Estimate Navigator's pane interior. Icons and the ribbon
    label come from the add-in's manifest, never from a workbook."""
    sect = profile.section("brand")
    if not sect:
        return None
    out = {}
    name = sect.get("name") or profile.data.get("name")
    if name:
        out["name"] = name
    colors = {m: dict(v) for m, v in (sect.get("colors") or {}).items() if v}
    if colors:
        out["colors"] = colors
    return out or None
