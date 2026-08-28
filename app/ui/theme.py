"""Theme — palette (derived from the locked key art), QSS, asset + font helpers.

The Phase-5 palette is derived from `assets/art/keyart.svg` (ink / amber /
misregister-red / cream), superseding the design-handoff HTML's violet/gold
tokens. Fonts are deferred: type ROLES map to system fallbacks here, in ONE place,
so the four OFL fonts (Space Grotesk / IBM Plex Mono / Special Elite / Saira
Stencil One) can be registered and re-pointed later without touching widgets.
"""
from PySide6.QtGui import QFont, QFontDatabase

from app._bootstrap import resource_root

ASSETS = resource_root() / "assets"     # repo root on dev, Contents/Resources when frozen

# Bundled OFL/Apache fonts (registered at startup; system fallback if unavailable,
# e.g. under the offscreen test platform which cannot register app fonts).
FONT_FILES = ("SpaceGrotesk.ttf", "IBMPlexMono-Regular.ttf",
              "SpecialElite-Regular.ttf", "SairaStencilOne-Regular.ttf")


def asset_path(*parts):
    """Absolute path to a bundled asset (resolved from the package, not cwd)."""
    return ASSETS.joinpath(*parts)


# --- palettes ---------------------------------------------------------------
DARK = {
    "bg": "#0d0b07", "panel": "#16130d", "panel2": "#211c14",
    "fg": "#e8e2d2", "muted": "#928e86",
    "accent": "#e2b84a", "on_accent": "#0d0b07",
    "alert": "#c42b1e", "ok": "#46c06a",
    "line": "rgba(232,226,210,0.12)",
}
LIGHT = {
    "bg": "#e8e2d2", "panel": "#ddd6c3", "panel2": "#cfc6b0",
    "fg": "#0d0b07", "muted": "#6b665c",
    "accent": "#c8902a", "on_accent": "#0d0b07",
    "alert": "#c42b1e", "ok": "#2f9a52",
    "line": "rgba(13,11,7,0.14)",
}
PALETTE = {"dark": DARK, "light": LIGHT}

# --- type roles (system fallback now; OFL fonts drop in later) ---------------
ROLE_FAMILIES = {
    "display": ["Saira Stencil One", "Impact", "Arial Black", "sans-serif"],
    "ui": ["Space Grotesk", "Helvetica Neue", "Arial", "sans-serif"],
    "mono": ["IBM Plex Mono", "Special Elite", "Menlo", "monospace"],
}


def font_role(name, size=13, *, bold=False):
    families = ROLE_FAMILIES.get(name, ROLE_FAMILIES["ui"])
    f = QFont(families[0], size)
    f.setFamilies(families)
    f.setBold(bold)
    return f


def register_fonts():
    """Register the bundled fonts with Qt. Returns the loaded family names
    (empty under platforms that cannot register app fonts, e.g. offscreen)."""
    loaded = []
    for fn in FONT_FILES:
        path = asset_path("fonts", fn)
        if path.exists():
            fid = QFontDatabase.addApplicationFont(str(path))
            if fid != -1:
                loaded.extend(QFontDatabase.applicationFontFamilies(fid))
    return loaded


def _build_qss(p, grit=None):
    grit_rule = ""
    if grit and grit.exists():
        grit_rule = (f'QWidget#generateRoot {{ background-image: '
                     f'url("{grit.as_posix()}"); background-repeat: repeat; }}')
    return f"""
    QWidget {{ background: {p['bg']}; color: {p['fg']}; }}
    {grit_rule}
    QFrame#panel, QListWidget {{ background: {p['panel']};
        border: 1px solid {p['line']}; border-radius: 8px; }}
    QLabel#title {{ color: {p['accent']}; font-weight: 700; }}
    QLabel#muted {{ color: {p['muted']}; }}
    QLabel#mixWarning {{ color: {p['alert']}; padding: 2px 4px; }}
    QListWidget::item {{ padding: 6px 8px; }}
    QListWidget::item:selected {{ background: {p['accent']}; color: {p['on_accent']}; }}
    QPushButton {{ background: {p['panel2']}; color: {p['fg']};
        border: 1px solid {p['line']}; border-radius: 6px; padding: 6px 12px; }}
    QPushButton:hover {{ border-color: {p['accent']}; }}
    QPushButton:disabled {{ color: {p['muted']}; border-color: {p['line']}; }}
    QPushButton#primary {{ background: {p['accent']}; color: {p['on_accent']};
        border: none; font-weight: 700; }}
    QPushButton#danger {{ border-color: {p['alert']}; color: {p['alert']}; }}
    QSpinBox, QComboBox {{ background: {p['panel2']}; color: {p['fg']};
        border: 1px solid {p['line']}; border-radius: 6px; padding: 4px 6px; }}
    QStatusBar {{ background: {p['panel']}; color: {p['muted']}; }}
    """


def apply(app, mode="dark"):
    """Register fonts and apply the theme stylesheet; return the QSS string."""
    register_fonts()
    qss = _build_qss(PALETTE.get(mode, DARK), grit=asset_path("textures", "grit.png"))
    app.setStyleSheet(qss)
    app.setFont(font_role("ui"))
    return qss
