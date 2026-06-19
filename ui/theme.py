"""PokéStock design system — modern SaaS dashboard theme for Streamlit."""

from __future__ import annotations

import html as html_lib

# ---------------------------------------------------------------------------
# Navigation model
# ---------------------------------------------------------------------------

NAV_SECTIONS = (
    {
        "label": "Principal",
        "items": (
            ("Accueil", "Accueil", "🏠"),
            ("Vente", "Vente/Échange", "💰"),
            ("Lots", "Lots", "📦"),
        ),
    },
    {
        "label": "Gestion",
        "items": (
            ("Collection", "Collection", "🧾"),
            ("Estimations", "Estimations", "📉"),
            ("Annonces Vinted", "Annonces Vinted", "🛍️"),
            ("Historique", "Historique", "📋"),
            ("Archivés", "Archivés", "🗄️"),
        ),
    },
    {
        "label": "Analyse",
        "items": (
            ("Wrapped", "Wrapped", "🎁"),
            ("Statistiques", "Statistiques", "📊"),
            ("Compteurs", "Compteurs", "🎰"),
        ),
    },
)

KPI_ACCENTS = ("#3b82f6", "#8b5cf6", "#06b6d4", "#f59e0b", "#10b981")


def _delta_html(delta: str | None) -> str:
    if not delta or delta == "0.00€":
        return ""
    try:
        delta_val = float(str(delta).replace("€", "").replace(",", ".").strip())
    except ValueError:
        return ""
    if delta_val > 0:
        cls, arrow = "ps-delta-up", "↑"
    elif delta_val < 0:
        cls, arrow = "ps-delta-down", "↓"
    else:
        return ""
    return (
        f'<span class="ps-kpi-delta {cls}">{arrow} {html_lib.escape(str(delta))}</span>'
    )


def render_kpi_card(
    label: str,
    value: str,
    *,
    delta: str | None = None,
    accent: str = "#3b82f6",
    icon: str = "",
) -> str:
    icon_html = (
        f'<span class="ps-kpi-icon" style="background:{accent}15;color:{accent}">'
        f"{html_lib.escape(icon)}</span>"
        if icon
        else ""
    )
    return f"""
    <div class="ps-kpi-card" style="--ps-kpi-accent:{accent}">
        {icon_html}
        <div class="ps-kpi-label">{html_lib.escape(label)}</div>
        <div class="ps-kpi-value">{html_lib.escape(str(value))}</div>
        {_delta_html(delta)}
    </div>
    """


def render_page_header(title: str, subtitle: str = "", icon: str = "") -> str:
    icon_html = (
        f'<span class="ps-page-icon">{html_lib.escape(icon)}</span>' if icon else ""
    )
    subtitle_html = (
        f'<p class="ps-page-subtitle">{html_lib.escape(subtitle)}</p>' if subtitle else ""
    )
    return f"""
    <div class="ps-page-header">
        {icon_html}
        <div>
            <h2 class="ps-page-title">{html_lib.escape(title)}</h2>
            {subtitle_html}
        </div>
    </div>
    """


def render_app_header(logo_src: str, *, mobile: bool = False) -> str:
    tagline = "Gestion stock, ventes & lots Pokémon"
    compact = " ps-app-header--compact" if mobile else ""
    return f"""
    <header class="ps-app-header{compact}">
        <div class="ps-app-header-brand">
            <img src="{html_lib.escape(logo_src)}" alt="PokéStock" class="ps-app-logo">
            <div>
                <div class="ps-app-title">PokéStock</div>
                <div class="ps-app-tagline">{tagline}</div>
            </div>
        </div>
    </header>
    """


def render_sidebar_brand(logo_src: str, build: str) -> str:
    return f"""
    <div class="ps-sidebar-brand">
        <img src="{html_lib.escape(logo_src)}" alt="PokéStock">
        <div>
            <div class="ps-sidebar-title">PokéStock</div>
            <div class="ps-sidebar-build">{html_lib.escape(build)}</div>
        </div>
    </div>
    """


def render_sidebar_stat(label: str, value: str) -> str:
    return f"""
    <div class="ps-sidebar-stat">
        <span class="ps-sidebar-stat-label">{html_lib.escape(label)}</span>
        <span class="ps-sidebar-stat-value">{html_lib.escape(str(value))}</span>
    </div>
    """


def inject_theme(*, mobile: bool = False) -> str:
    """Return the full CSS block for PokéStock."""
    mobile_flag = "body.codex-mobile-mode" if mobile else ""
    return f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap');

:root {{
    --ps-bg: #f1f5f9;
    --ps-surface: #ffffff;
    --ps-surface-muted: #f8fafc;
    --ps-sidebar: #0f172a;
    --ps-sidebar-border: #1e293b;
    --ps-accent: #dc2626;
    --ps-accent-hover: #b91c1c;
    --ps-accent-soft: #fef2f2;
    --ps-blue: #2563eb;
    --ps-success: #059669;
    --ps-warning: #d97706;
    --ps-danger: #dc2626;
    --ps-text: #0f172a;
    --ps-text-secondary: #475569;
    --ps-text-muted: #94a3b8;
    --ps-border: #e2e8f0;
    --ps-border-strong: #cbd5e1;
    --ps-radius-sm: 8px;
    --ps-radius: 12px;
    --ps-radius-lg: 16px;
    --ps-shadow-sm: 0 1px 2px rgba(15, 23, 42, 0.05);
    --ps-shadow: 0 4px 6px -1px rgba(15, 23, 42, 0.07), 0 2px 4px -2px rgba(15, 23, 42, 0.05);
    --ps-shadow-lg: 0 10px 15px -3px rgba(15, 23, 42, 0.08), 0 4px 6px -4px rgba(15, 23, 42, 0.05);
    --ps-font: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --pokemon-red: var(--ps-accent);
    --pokemon-blue: var(--ps-blue);
    --pokemon-yellow: #fbbf24;
    --pokemon-green: var(--ps-success);
    --text-primary: var(--ps-text);
    --text-secondary: var(--ps-text-secondary);
    --border: var(--ps-border);
}}

/* ── Base layout ── */
h1 {{ display: none !important; }}
.stApp {{
    background: var(--ps-bg) !important;
    font-family: var(--ps-font) !important;
    color: var(--ps-text) !important;
}}
.stApp::before, .stApp::after {{
    content: none !important;
    display: none !important;
}}
.main .block-container {{
    max-width: 1280px !important;
    padding-top: 1.25rem !important;
    padding-bottom: 2.5rem !important;
}}
.stMarkdown, .stMarkdown p, label,
[data-testid="stCaptionContainer"], [data-testid="stText"] {{
    color: var(--ps-text) !important;
    font-family: var(--ps-font) !important;
}}

/* ── App header ── */
.ps-app-header {{
    background: var(--ps-surface);
    border: 1px solid var(--ps-border);
    border-radius: var(--ps-radius-lg);
    padding: 1.25rem 1.5rem;
    margin-bottom: 1.5rem;
    box-shadow: var(--ps-shadow-sm);
}}
.ps-app-header--compact {{
    padding: 0.85rem 1rem;
    margin-bottom: 1rem;
}}
.ps-app-header-brand {{
    display: flex;
    align-items: center;
    gap: 1rem;
}}
.ps-app-logo {{
    width: 52px;
    height: 52px;
    object-fit: contain;
    border-radius: var(--ps-radius);
    background: var(--ps-surface-muted);
    padding: 4px;
}}
.ps-app-header--compact .ps-app-logo {{
    width: 40px;
    height: 40px;
}}
.ps-app-title {{
    font-size: 1.35rem;
    font-weight: 800;
    color: var(--ps-text);
    letter-spacing: -0.02em;
    line-height: 1.2;
}}
.ps-app-tagline {{
    font-size: 0.875rem;
    color: var(--ps-text-secondary);
    font-weight: 500;
    margin-top: 0.15rem;
}}
.logo-header {{ display: none !important; }}

/* ── Page headers ── */
.ps-page-header {{
    display: flex;
    align-items: flex-start;
    gap: 0.85rem;
    margin-bottom: 1.5rem;
    padding-bottom: 1rem;
    border-bottom: 1px solid var(--ps-border);
}}
.ps-page-icon {{
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2.5rem;
    height: 2.5rem;
    border-radius: var(--ps-radius);
    background: var(--ps-accent-soft);
    font-size: 1.15rem;
    flex-shrink: 0;
}}
.ps-page-title, h2.ps-page-title {{
    font-size: 1.5rem !important;
    font-weight: 800 !important;
    color: var(--ps-text) !important;
    text-transform: none !important;
    letter-spacing: -0.02em !important;
    margin: 0 !important;
    padding: 0 !important;
    border: none !important;
    line-height: 1.25 !important;
}}
.ps-page-subtitle {{
    margin: 0.25rem 0 0 0;
    color: var(--ps-text-secondary);
    font-size: 0.9rem;
    font-weight: 500;
}}
h2 {{
    font-size: 1.35rem !important;
    font-weight: 800 !important;
    color: var(--ps-text) !important;
    text-transform: none !important;
    letter-spacing: -0.02em !important;
    margin-bottom: 1.25rem !important;
    padding-bottom: 0 !important;
    border-bottom: none !important;
}}

/* ── KPI cards ── */
.ps-kpi-card {{
    position: relative;
    background: var(--ps-surface);
    border: 1px solid var(--ps-border);
    border-radius: var(--ps-radius-lg);
    padding: 1.15rem 1.25rem;
    box-shadow: var(--ps-shadow-sm);
    transition: box-shadow 0.2s ease, transform 0.2s ease;
    overflow: hidden;
}}
.ps-kpi-card::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 3px;
    background: var(--ps-kpi-accent, var(--ps-blue));
    border-radius: 3px 0 0 3px;
}}
.ps-kpi-card:hover {{
    box-shadow: var(--ps-shadow);
    transform: translateY(-1px);
}}
.ps-kpi-icon {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    border-radius: var(--ps-radius-sm);
    font-size: 0.95rem;
    margin-bottom: 0.65rem;
}}
.ps-kpi-label {{
    font-size: 0.72rem;
    font-weight: 700;
    color: var(--ps-text-muted);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.35rem;
}}
.ps-kpi-value {{
    font-size: 1.65rem;
    font-weight: 800;
    color: var(--ps-text);
    letter-spacing: -0.02em;
    line-height: 1.1;
}}
.ps-kpi-delta {{
    display: inline-flex;
    align-items: center;
    gap: 0.2rem;
    margin-top: 0.5rem;
    padding: 0.2rem 0.55rem;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 700;
}}
.ps-delta-up {{ background: #d1fae5; color: #047857; }}
.ps-delta-down {{ background: #fee2e2; color: #b91c1c; }}

/* ── Sidebar ── */
[data-testid="stSidebar"] {{
    background: var(--ps-sidebar) !important;
    border-right: 1px solid var(--ps-sidebar-border) !important;
}}
[data-testid="stSidebar"]::before {{
    content: none !important;
    display: none !important;
}}
[data-testid="stSidebar"] > div {{
    padding-top: 0.5rem !important;
}}
[data-testid="stSidebar"] .stMarkdown,
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label,
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
    color: #cbd5e1 !important;
}}
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 {{
    color: #f8fafc !important;
}}
.ps-sidebar-brand {{
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.75rem 0.5rem 1rem;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid var(--ps-sidebar-border);
}}
.ps-sidebar-brand img {{
    width: 36px;
    height: 36px;
    border-radius: var(--ps-radius-sm);
    background: rgba(255,255,255,0.08);
    padding: 3px;
}}
.ps-sidebar-title {{
    font-size: 1rem;
    font-weight: 800;
    color: #f8fafc;
    letter-spacing: -0.02em;
}}
.ps-sidebar-build {{
    font-size: 0.68rem;
    color: #64748b;
    font-weight: 500;
    margin-top: 0.1rem;
}}
.ps-nav-section-label {{
    font-size: 0.65rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: #64748b !important;
    margin: 1rem 0 0.4rem 0;
    padding-left: 0.25rem;
}}
.ps-sidebar-stats {{
    display: grid;
    gap: 0.45rem;
    margin: 0.75rem 0 1rem;
    padding: 0.75rem;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: var(--ps-radius);
}}
.ps-sidebar-stat {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem;
}}
.ps-sidebar-stat-label {{
    font-size: 0.72rem;
    color: #94a3b8 !important;
    font-weight: 600;
}}
.ps-sidebar-stat-value {{
    font-size: 0.8rem;
    color: #f1f5f9 !important;
    font-weight: 700;
}}
[data-testid="stSidebar"] hr {{
    border: none !important;
    height: 1px !important;
    background: var(--ps-sidebar-border) !important;
    margin: 1rem 0 !important;
}}
[data-testid="stSidebar"] h2 {{
    display: none !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] {{
    background: rgba(255,255,255,0.04) !important;
    border: 1px solid rgba(255,255,255,0.08) !important;
    border-radius: var(--ps-radius) !important;
}}
[data-testid="stSidebar"] [data-testid="stExpander"] summary {{
    background: transparent !important;
    color: #e2e8f0 !important;
    font-weight: 600 !important;
    font-size: 0.8rem !important;
    padding: 0.65rem 0.85rem !important;
}}
[data-testid="stSidebar"] .stButton > button {{
    background: transparent !important;
    color: #cbd5e1 !important;
    border: 1px solid transparent !important;
    border-radius: var(--ps-radius-sm) !important;
    padding: 0.55rem 0.75rem !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
    text-transform: none !important;
    text-align: left !important;
    justify-content: flex-start !important;
    transition: all 0.15s ease !important;
    box-shadow: none !important;
}}
[data-testid="stSidebar"] .stButton > button:hover {{
    background: rgba(255,255,255,0.06) !important;
    color: #f8fafc !important;
    border-color: rgba(255,255,255,0.08) !important;
    transform: none !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"] {{
    background: rgba(220, 38, 38, 0.15) !important;
    color: #fecaca !important;
    border-color: rgba(220, 38, 38, 0.35) !important;
}}
[data-testid="stSidebar"] .stButton > button[kind="primary"]:hover {{
    background: rgba(220, 38, 38, 0.25) !important;
    color: #fff !important;
}}

/* ── Buttons ── */
.stButton > button {{
    background: var(--ps-surface) !important;
    color: var(--ps-text) !important;
    border: 1px solid var(--ps-border-strong) !important;
    border-radius: var(--ps-radius-sm) !important;
    padding: 0.6rem 1.1rem !important;
    font-weight: 600 !important;
    font-size: 0.875rem !important;
    text-transform: none !important;
    transition: all 0.15s ease !important;
    box-shadow: var(--ps-shadow-sm) !important;
}}
.stButton > button:hover {{
    background: var(--ps-surface-muted) !important;
    border-color: var(--ps-border-strong) !important;
    transform: translateY(-1px) !important;
    box-shadow: var(--ps-shadow) !important;
}}
.stButton > button[kind="primary"] {{
    background: var(--ps-accent) !important;
    color: #fff !important;
    border-color: var(--ps-accent-hover) !important;
}}
.stButton > button[kind="primary"]:hover {{
    background: var(--ps-accent-hover) !important;
}}
.stForm button, button[kind="primary"], button[type="submit"] {{
    background: var(--ps-text) !important;
    color: #fff !important;
    border: 1px solid #334155 !important;
    border-radius: var(--ps-radius-sm) !important;
    font-weight: 600 !important;
}}
.stForm button:hover, button[kind="primary"]:hover {{
    background: #334155 !important;
}}

/* ── Inputs ── */
.stTextInput > div > div > input,
.stNumberInput > div > div > input,
.stTextArea textarea {{
    background: var(--ps-surface) !important;
    color: var(--ps-text) !important;
    border: 1px solid var(--ps-border-strong) !important;
    border-radius: var(--ps-radius-sm) !important;
    padding: 0.6rem 0.85rem !important;
    font-weight: 500 !important;
    font-size: 0.9rem !important;
}}
.stTextInput > div > div > input:focus,
.stNumberInput > div > div > input:focus {{
    border-color: var(--ps-blue) !important;
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.12) !important;
}}
.stTextInput > div > div > input::placeholder {{
    color: var(--ps-text-muted) !important;
}}
.stSelectbox [data-baseweb="select"] {{
    background: var(--ps-surface) !important;
    border-radius: var(--ps-radius-sm) !important;
}}
.stSelectbox [data-baseweb="select"] span,
.stSelectbox [data-baseweb="select"] div {{
    color: var(--ps-text) !important;
}}
[role="listbox"], [data-baseweb="menu"] {{
    background: var(--ps-surface) !important;
    border: 1px solid var(--ps-border) !important;
    border-radius: var(--ps-radius-sm) !important;
    box-shadow: var(--ps-shadow-lg) !important;
}}
[role="option"] {{
    color: var(--ps-text) !important;
    background: var(--ps-surface) !important;
}}
[role="option"]:hover {{
    background: var(--ps-surface-muted) !important;
}}

/* ── Radio / toggles ── */
.stRadio > div {{
    display: flex;
    gap: 0.4rem;
    flex-wrap: wrap;
}}
.stRadio label {{
    background: var(--ps-surface) !important;
    color: var(--ps-text) !important;
    border: 1px solid var(--ps-border) !important;
    border-radius: var(--ps-radius-sm) !important;
    padding: 0.45rem 0.85rem !important;
    font-weight: 600 !important;
    font-size: 0.82rem !important;
}}
.stRadio label:hover {{
    border-color: var(--ps-border-strong) !important;
    background: var(--ps-surface-muted) !important;
}}
.stRadio label:has(input:checked) {{
    background: var(--ps-accent-soft) !important;
    border-color: var(--ps-accent) !important;
    color: var(--ps-accent) !important;
}}
div[data-testid="stRadio"] label p,
div[data-testid="stRadio"] label span {{
    color: inherit !important;
}}

/* ── Metrics (Streamlit native) ── */
[data-testid="stMetric"] {{
    background: var(--ps-surface) !important;
    border: 1px solid var(--ps-border) !important;
    border-radius: var(--ps-radius-lg) !important;
    padding: 1.15rem !important;
    box-shadow: var(--ps-shadow-sm) !important;
}}
[data-testid="stMetric"]:hover {{
    box-shadow: var(--ps-shadow) !important;
    transform: translateY(-1px);
    border-color: var(--ps-border-strong) !important;
}}
[data-testid="stMetricLabel"] {{
    font-size: 0.72rem !important;
    font-weight: 700 !important;
    color: var(--ps-text-muted) !important;
    text-transform: uppercase !important;
    letter-spacing: 0.05em !important;
}}
[data-testid="stMetricValue"] {{
    font-size: 1.65rem !important;
    font-weight: 800 !important;
    color: var(--ps-text) !important;
    letter-spacing: -0.02em !important;
}}
[data-testid="column"]:has([data-testid="stMetric"]) img {{
    display: none !important;
}}

/* ── Expanders / cards ── */
[data-testid="stExpander"] {{
    background: var(--ps-surface) !important;
    border: 1px solid var(--ps-border) !important;
    border-left: 3px solid var(--ps-border-strong) !important;
    border-radius: var(--ps-radius) !important;
    box-shadow: var(--ps-shadow-sm) !important;
    margin: 0.65rem 0 !important;
}}
[data-testid="stExpander"].lot-profitable {{
    border-left-color: var(--ps-success) !important;
}}
[data-testid="stExpander"].lot-not-profitable {{
    border-left-color: var(--ps-danger) !important;
}}
[data-testid="stExpander"]::before {{
    display: none !important;
}}
[data-testid="stExpander"] summary {{
    font-weight: 700 !important;
    padding: 0.9rem 1.1rem !important;
    background: var(--ps-surface-muted) !important;
    color: var(--ps-text) !important;
    border-radius: var(--ps-radius) var(--ps-radius) 0 0 !important;
}}
[data-testid="stExpander"]:hover {{
    transform: none !important;
    box-shadow: var(--ps-shadow) !important;
}}

/* ── Badges ── */
.badge {{
    display: inline-block;
    padding: 0.25rem 0.6rem;
    border-radius: 999px;
    font-size: 0.68rem;
    font-weight: 700;
    margin: 0.15rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border: 1px solid;
}}
.badge-reverse {{ background: #f5f3ff; color: #7c3aed; border-color: #ddd6fe; }}
.badge-ed1 {{ background: #fef2f2; color: #dc2626; border-color: #fecaca; }}
.badge-profitable {{ background: #ecfdf5; color: #059669; border-color: #a7f3d0; }}

/* ── Alerts ── */
.stSuccess {{
    background: #ecfdf5 !important;
    border: 1px solid #a7f3d0 !important;
    border-radius: var(--ps-radius) !important;
    color: #065f46 !important;
}}
.stWarning {{
    background: #fffbeb !important;
    border: 1px solid #fde68a !important;
    border-radius: var(--ps-radius) !important;
    color: #92400e !important;
}}
.stInfo {{
    background: #eff6ff !important;
    border: 1px solid #bfdbfe !important;
    border-radius: var(--ps-radius) !important;
}}
hr {{
    border: none !important;
    height: 1px !important;
    background: var(--ps-border) !important;
    margin: 1.5rem 0 !important;
}}

/* ── Card images ── */
[data-testid="stExpander"] [data-testid="stImage"] img,
[data-testid="stHorizontalBlock"] [data-testid="stImage"] img {{
    border-radius: var(--ps-radius) !important;
    border: 1px solid var(--ps-border) !important;
    box-shadow: var(--ps-shadow-sm) !important;
    transition: transform 0.2s ease, box-shadow 0.2s ease !important;
}}
[data-testid="stExpander"] [data-testid="stImage"] img:hover,
[data-testid="stHorizontalBlock"] [data-testid="stImage"] img:hover {{
    transform: scale(1.02) !important;
    box-shadow: var(--ps-shadow) !important;
    border-color: var(--ps-border-strong) !important;
}}
[data-testid="stImage"], [data-testid="stImage"] > div {{
    background: transparent !important;
}}

/* ── Tabs ── */
[data-testid="stTabs"] [role="tablist"] {{
    gap: 0.25rem !important;
    border-bottom: 1px solid var(--ps-border) !important;
    padding-bottom: 0 !important;
}}
[data-testid="stTabs"] [role="tab"] {{
    font-weight: 600 !important;
    font-size: 0.85rem !important;
    color: var(--ps-text-secondary) !important;
    border-radius: var(--ps-radius-sm) var(--ps-radius-sm) 0 0 !important;
    padding: 0.5rem 0.85rem !important;
}}
[data-testid="stTabs"] [role="tab"][aria-selected="true"] {{
    color: var(--ps-accent) !important;
    border-bottom: 2px solid var(--ps-accent) !important;
}}

/* ── Plotly charts ── */
[data-testid="stPlotlyChart"] {{
    background: var(--ps-surface);
    border: 1px solid var(--ps-border);
    border-radius: var(--ps-radius-lg);
    padding: 0.5rem;
    box-shadow: var(--ps-shadow-sm);
}}

/* ── Quick actions row ── */
.ps-quick-actions {{
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 0.75rem;
    margin: 1rem 0 1.5rem;
}}

/* ── Mobile card grids (functional) ── */
.mobile-card-grid {{
    display: grid !important;
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    gap: 0.35rem !important;
    width: 100% !important;
}}
.mobile-card-tile {{
    background: var(--ps-surface) !important;
    border: 1px solid var(--ps-border) !important;
    border-radius: var(--ps-radius-sm) !important;
    padding: 0.35rem !important;
}}
.codex-floating-cart {{ display: none; }}

/* ── Mobile overrides ── */
@media (max-width: 760px), (pointer: coarse) and (max-width: 900px) {{
    .main .block-container {{
        padding-left: 0.75rem !important;
        padding-right: 0.75rem !important;
        padding-bottom: 5rem !important;
    }}
    .ps-kpi-value {{ font-size: 1.35rem !important; }}
    .ps-app-header {{ padding: 0.85rem 1rem; }}
    .codex-floating-cart {{
        display: flex !important;
        position: fixed !important;
        right: 0.85rem !important;
        bottom: calc(5.8rem + env(safe-area-inset-bottom, 0px)) !important;
        width: 3.2rem !important;
        height: 3.2rem !important;
        border-radius: 999px !important;
        background: var(--ps-success) !important;
        color: #fff !important;
        align-items: center !important;
        justify-content: center !important;
        text-decoration: none !important;
        font-size: 1.35rem !important;
        font-weight: 800 !important;
        z-index: 9500 !important;
        box-shadow: var(--ps-shadow-lg) !important;
        border: 2px solid #fff !important;
    }}
    .codex-floating-cart span {{
        position: absolute !important;
        top: -0.35rem !important;
        right: -0.35rem !important;
        min-width: 1.2rem !important;
        height: 1.2rem !important;
        border-radius: 999px !important;
        background: var(--ps-danger) !important;
        color: #fff !important;
        font-size: 0.65rem !important;
        font-weight: 800 !important;
        display: flex !important;
        align-items: center !important;
        justify-content: center !important;
        border: 2px solid #fff !important;
    }}
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div + div {{
        background: #e8eef7 !important;
        position: sticky !important;
        z-index: 6900 !important;
    }}
    div[data-testid="stHorizontalBlock"]:has([data-testid="stImage"]) {{
        display: grid !important;
        grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        gap: 0.25rem !important;
    }}
}}
</style>
"""


def inject_functional_css() -> str:
    """Sticky forms, mobile grids, and sale-page layout hacks."""
    return """
<style>
div[style*="display: flex"][style*="justify-content: center"] img {
    margin: 0 auto !important;
    display: block !important;
}
[data-codex-add-sticky="1"] {
    isolation: isolate !important;
    contain: paint !important;
}
@media (max-width: 760px), (pointer: coarse) and (max-width: 900px) {
    img[src*="/pokemon/other/official-artwork/25"],
    img[src*="/pokemon/other/official-artwork/133"] {
        display: none !important;
        visibility: hidden !important;
        pointer-events: none !important;
    }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div,
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div + div {
        background: #e8eef7 !important;
        margin: 0 !important;
        padding: 0.1rem 0.35rem !important;
        position: sticky !important;
        z-index: 6900 !important;
        overflow: hidden !important;
    }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div { top: 0 !important; border-radius: 12px 12px 0 0 !important; }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div { top: 1.7rem !important; }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div { top: 4.1rem !important; }
    [data-testid="stElementContainer"]:has([data-add-card-form-marker]) + div + div + div + div { top: 6.6rem !important; border-radius: 0 0 12px 12px !important; }
    div[data-testid="stHorizontalBlock"]:has([data-testid="stImage"]) {
        display: grid !important;
        grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
        gap: 0.25rem !important;
    }
    body:has([data-sale-mobile-marker]) .block-container,
    .stApp:has([data-sale-mobile-marker]) .block-container {
        max-width: 100% !important;
        padding-left: 0.5rem !important;
        padding-right: 0.5rem !important;
    }
}
</style>
"""


def inject_mobile_overrides() -> str:
    """Additional compact layout rules when mobile mode is active."""
    return """
<style>
html, body, .stApp {
    overflow-x: hidden !important;
    width: 100% !important;
}
body.codex-mobile-mode .stApp::before,
body.codex-mobile-mode .stApp::after {
    content: none !important;
    display: none !important;
}
section[data-testid="stSidebar"] {
    min-width: 13.5rem !important;
    max-width: 16rem !important;
}
.main .block-container {
    max-width: 100% !important;
    padding-left: 0.55rem !important;
    padding-right: 0.55rem !important;
    padding-top: 0.75rem !important;
}
div[data-testid="stHorizontalBlock"] {
    gap: 0.45rem !important;
}
div[data-testid="column"] {
    min-width: 0 !important;
}
div[data-testid="stButton"] button {
    min-height: 2.75rem !important;
    width: 100% !important;
    white-space: normal !important;
    line-height: 1.15 !important;
    padding-left: 0.45rem !important;
    padding-right: 0.45rem !important;
}
div[data-testid="stNumberInput"] input,
div[data-testid="stTextInput"] input,
div[data-testid="stTextArea"] textarea,
div[data-baseweb="select"] {
    min-height: 2.65rem !important;
    font-size: 0.95rem !important;
}
img {
    max-width: 100% !important;
    height: auto;
}
.mobile-card-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr)) !important;
    gap: 0.55rem !important;
}
.mobile-card-tile {
    min-width: 0 !important;
    padding: 0.35rem !important;
}
.mobile-card-imgbox {
    min-height: 0 !important;
}
.mobile-card-imgbox img {
    width: 100% !important;
    max-height: 155px !important;
    object-fit: contain !important;
}
.mobile-card-name {
    font-size: 0.78rem !important;
    line-height: 1.15 !important;
}
.mobile-card-meta {
    font-size: 0.7rem !important;
    line-height: 1.15 !important;
}
[data-testid="stDataFrame"],
[data-testid="stTable"],
.js-plotly-plot {
    max-width: 100% !important;
    overflow-x: auto !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.35rem !important;
}
</style>
"""


def wrapped_css() -> str:
    """Premium story-like styling for the Pokestock Wrapped page."""
    return """
<style>
.ps-wrapped-entry {
    min-height: clamp(180px, 28dvh, 300px);
    display: grid;
    place-items: center;
    padding: clamp(0.65rem, 2.2vw, 1.45rem);
    border-radius: 28px;
    color: #ffffff;
    background:
        linear-gradient(115deg, rgba(255,255,255,0.055), transparent 22%, rgba(250,204,21,0.075) 38%, transparent 58%),
        radial-gradient(circle at 78% 18%, rgba(94, 92, 230, 0.28), transparent 30%),
        linear-gradient(145deg, #030711 0%, #101426 46%, #140d23 100%);
    border: 1px solid rgba(255,255,255,0.12);
    box-shadow: 0 30px 80px rgba(15, 23, 42, 0.20);
    overflow: hidden;
    position: relative;
}
.stApp:has(.ps-wrapped-entry) .main .block-container {
    padding-top: 0.85rem !important;
    padding-bottom: 1rem !important;
}
.ps-wrapped-entry::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        linear-gradient(128deg, transparent 0 42%, rgba(255,255,255,0.09) 48%, transparent 55%),
        repeating-linear-gradient(90deg, rgba(255,255,255,0.045) 0 1px, transparent 1px 18px);
    background-size: 100% 100%, 42px 42px;
    mask-image: radial-gradient(circle at center, rgba(0,0,0,0.82), transparent 80%);
}
.ps-wrapped-entry-card {
    position: relative;
    z-index: 1;
    width: min(720px, 100%);
    display: grid;
    justify-items: center;
    gap: clamp(0.32rem, 0.9vw, 0.58rem);
    text-align: center;
    padding: clamp(0.72rem, 2.25vw, 1.55rem);
    border-radius: 24px;
    border: 1px solid rgba(255,255,255,0.20);
    background:
        linear-gradient(135deg, rgba(255,255,255,0.18), rgba(255,255,255,0.075)),
        linear-gradient(115deg, transparent 28%, rgba(250,204,21,0.10) 48%, transparent 66%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.16), 0 28px 70px rgba(0,0,0,0.28);
    backdrop-filter: blur(18px);
}
.ps-wrapped-entry-card span {
    color: rgba(255,255,255,0.68);
    font-size: 0.78rem;
    font-weight: 950;
    letter-spacing: 0.16em;
    text-transform: uppercase;
}
.ps-wrapped-entry-card strong {
    color: #ffffff;
    font-size: clamp(1.8rem, 4vw, 3.25rem);
    line-height: 1;
    font-weight: 950;
    letter-spacing: -0.04em;
    text-shadow: 0 18px 56px rgba(0,0,0,0.34);
}
.ps-wrapped-entry-card em {
    max-width: 520px;
    color: rgba(255,255,255,0.76);
    font-style: normal;
    font-size: clamp(0.82rem, 1.45vw, 1rem);
    line-height: 1.32;
    font-weight: 750;
}
.stApp:has(.ps-wrapped-entry) .main .stButton > button {
    min-height: 3.2rem !important;
    border-radius: 999px !important;
    font-weight: 950 !important;
    color: #ffffff !important;
    background: linear-gradient(135deg, #7c3aed, #0ea5e9) !important;
    border: 1px solid rgba(255,255,255,0.22) !important;
    box-shadow: 0 18px 44px rgba(37,99,235,0.28) !important;
}
@media (max-width: 760px) {
    .stApp:has(.ps-wrapped-entry) .main .block-container {
        padding-top: 0.75rem !important;
        padding-bottom: 1rem !important;
    }
    .ps-wrapped-entry {
        min-height: min(34dvh, 285px);
        padding: 0.72rem;
        border-radius: 22px;
    }
    .ps-wrapped-entry-card {
        gap: 0.42rem;
        padding: 0.92rem;
        border-radius: 22px;
    }
    .ps-wrapped-entry-card span {
        font-size: 0.66rem;
    }
    .ps-wrapped-entry-card strong {
        font-size: clamp(1.85rem, 10.5vw, 3.35rem);
        line-height: 0.96;
        letter-spacing: 0;
    }
    .ps-wrapped-entry-card em {
        font-size: clamp(0.82rem, 3.4vw, 0.96rem);
        line-height: 1.32;
    }
    .stApp:has(.ps-wrapped-entry) .main .stButton > button {
        min-height: 2.85rem !important;
    }
}
.ps-wrapped-shell {
    min-height: 100dvh;
    width: 100vw;
    height: 100dvh;
    box-sizing: border-box;
    display: grid;
    grid-template-rows: minmax(0, 1fr) auto;
    gap: clamp(0.25rem, 1dvh, 0.65rem);
    margin: 0;
    padding: clamp(0.85rem, 2.5vw, 1.4rem);
    border-radius: 0;
    color: #ffffff;
    font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    background:
        linear-gradient(123deg, rgba(255,255,255,0.06) 0 1px, transparent 1px 24%),
        radial-gradient(circle at 78% 18%, rgba(37, 99, 235, 0.20), transparent 28%),
        linear-gradient(145deg, #02050d 0%, #0a1020 46%, #171022 100%);
    border: 1px solid rgba(255,255,255,0.10);
    box-shadow: 0 34px 100px rgba(5, 8, 22, 0.46), inset 0 1px 0 rgba(255,255,255,0.08);
    position: fixed;
    inset: 0;
    z-index: 50;
    overflow: hidden;
    isolation: isolate;
}
.ps-wrapped-shell,
.ps-wrapped-shell * {
    box-sizing: border-box;
    min-width: 0;
}
.ps-wrapped-shell strong,
.ps-wrapped-shell em,
.ps-wrapped-shell span,
.ps-wrapped-shell small,
.ps-wrapped-title,
.ps-wrapped-big-number,
.ps-wrapped-subtitle {
    overflow-wrap: anywhere;
    word-break: normal;
}
.stApp:has(.ps-wrapped-shell) .main .block-container {
    max-width: 100vw !important;
    width: 100vw !important;
    padding: 0 !important;
    margin: 0 !important;
}
.stApp:has(.ps-wrapped-shell) [data-testid="stHeader"],
.stApp:has(.ps-wrapped-shell) [data-testid="stToolbar"],
.stApp:has(.ps-wrapped-shell) [data-testid="stDecoration"],
.stApp:has(.ps-wrapped-shell) [data-testid="stStatusWidget"],
.stApp:has(.ps-wrapped-shell) footer {
    display: none !important;
}
.stApp:has(.ps-wrapped-shell) [data-testid="stSidebar"] {
    display: none !important;
}
.stApp:has(.ps-wrapped-shell) [data-testid="stAppViewContainer"] > .main {
    margin-left: 0 !important;
}
.stApp:has(.ps-wrapped-shell),
.stApp:has(.ps-wrapped-shell) [data-testid="stAppViewContainer"],
.stApp:has(.ps-wrapped-shell) .main {
    background: #050816 !important;
    overflow: hidden !important;
}
.ps-wrapped-shell::before {
    content: "";
    position: absolute;
    inset: -2px;
    background:
        repeating-linear-gradient(90deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 26px),
        repeating-linear-gradient(0deg, rgba(255,255,255,0.025) 0 1px, transparent 1px 26px);
    background-size: 100% 100%;
    mask-image: radial-gradient(circle at 50% 50%, rgba(0,0,0,0.62), transparent 78%);
    pointer-events: none;
    z-index: 0;
    animation: psWrappedGrid 18s linear infinite;
}
.ps-wrapped-shell::after {
    content: "";
    position: absolute;
    width: min(70vw, 42rem);
    height: min(70vw, 42rem);
    right: -18vw;
    bottom: -20vw;
    border-radius: 24px;
    background:
        linear-gradient(135deg, rgba(255,255,255,0.11), transparent 45%),
        linear-gradient(45deg, transparent, rgba(250,204,21,0.08));
    filter: blur(1px);
    transform: rotate(-12deg);
    pointer-events: none;
    z-index: 0;
}
.ps-wrapped-grain,
.ps-wrapped-card-back,
.ps-wrapped-foil-band,
.ps-wrapped-orb {
    position: absolute;
    z-index: 0;
    pointer-events: none;
}
.ps-wrapped-orb {
    width: 9rem;
    height: 9rem;
    border-radius: 999px;
    background: rgba(250, 204, 21, 0.16);
    filter: blur(34px);
    left: -2.5rem;
    bottom: 18%;
    animation: psWrappedOrb 8s ease-in-out infinite alternate;
}
.ps-wrapped-grain {
    inset: 0;
    opacity: 0.18;
    background-image:
        radial-gradient(circle at 15% 20%, rgba(255,255,255,0.16) 0 1px, transparent 1px),
        radial-gradient(circle at 65% 70%, rgba(255,255,255,0.11) 0 1px, transparent 1px);
    background-size: 18px 18px, 27px 27px;
    mix-blend-mode: screen;
}
.ps-wrapped-card-back {
    width: min(48vw, 34rem);
    height: min(66vw, 44rem);
    right: clamp(-15rem, -13vw, -6rem);
    top: 50%;
    transform: translateY(-50%) rotate(-9deg);
    border-radius: clamp(1.2rem, 3vw, 2.4rem);
    border: 1px solid rgba(255,255,255,0.13);
    background:
        linear-gradient(145deg, rgba(255,255,255,0.10), rgba(255,255,255,0.02)),
        repeating-linear-gradient(135deg, rgba(255,255,255,0.055) 0 1px, transparent 1px 16px),
        linear-gradient(145deg, rgba(9, 17, 36, 0.88), rgba(26, 17, 44, 0.74));
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.10), 0 42px 110px rgba(0,0,0,0.34);
    opacity: 0.48;
    animation: psWrappedCardBack 10s ease-in-out infinite alternate;
}
.ps-wrapped-foil-band {
    inset: -20% auto auto -18%;
    width: 42vw;
    height: 140dvh;
    transform: rotate(17deg);
    background:
        linear-gradient(90deg, transparent, rgba(255,255,255,0.11), rgba(250,204,21,0.08), rgba(56,189,248,0.08), transparent);
    filter: blur(0.5px);
    opacity: 0.52;
    animation: psWrappedFoilBand 8s ease-in-out infinite alternate;
}
.ps-wrapped-particles,
.ps-wrapped-holo-ring {
    position: absolute;
    inset: 0;
    z-index: 0;
    pointer-events: none;
}
.ps-wrapped-artifact {
    position: absolute;
    z-index: 1;
    right: clamp(0.8rem, 5vw, 5.5rem);
    bottom: clamp(4.5rem, 9dvh, 7.5rem);
    width: clamp(5.2rem, 13vw, 11rem);
    height: clamp(5.2rem, 13vw, 11rem);
    opacity: 0.72;
    pointer-events: none;
    filter: drop-shadow(0 24px 55px rgba(0,0,0,0.34));
    animation: psWrappedArtifactFloat 6.4s ease-in-out infinite alternate;
}
.ps-wrapped-artifact::before,
.ps-wrapped-artifact::after,
.ps-wrapped-artifact span {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    display: block;
}
.ps-wrapped-artifact::before {
    border: 1px solid rgba(255,255,255,0.20);
    background:
        linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.035)),
        linear-gradient(115deg, transparent 36%, rgba(250,204,21,0.16) 48%, transparent 62%);
    backdrop-filter: blur(10px);
}
.ps-wrapped-artifact::after {
    inset: 18%;
    border: 1px solid rgba(255,255,255,0.16);
    opacity: 0.82;
}
.ps-wrapped-artifact span {
    inset: 32%;
    background: linear-gradient(135deg, #facc15, #7dd3fc);
    box-shadow: 0 0 28px rgba(250,204,21,0.25);
}
.ps-wrapped-artifact-booster {
    border-radius: 18px;
    transform: rotate(-10deg);
}
.ps-wrapped-artifact-booster::before {
    clip-path: polygon(12% 0, 88% 0, 100% 14%, 92% 100%, 8% 100%, 0 14%);
}
.ps-wrapped-artifact-booster span {
    inset: 40% 18%;
    border-radius: 999px;
}
.ps-wrapped-artifact-stack::before,
.ps-wrapped-artifact-binder::before,
.ps-wrapped-artifact-vault::before {
    border-radius: 20px;
    transform: rotate(-7deg);
}
.ps-wrapped-artifact-stack::after,
.ps-wrapped-artifact-binder::after,
.ps-wrapped-artifact-vault::after {
    inset: 10%;
    border-radius: 16px;
    transform: translate(12%, -10%) rotate(8deg);
    background: rgba(255,255,255,0.08);
}
.ps-wrapped-artifact-coin,
.ps-wrapped-artifact-badge {
    border-radius: 999px;
}
.ps-wrapped-artifact-coin::before,
.ps-wrapped-artifact-badge::before {
    border-radius: 999px;
    background:
        conic-gradient(from 140deg, rgba(250,204,21,0.92), rgba(255,255,255,0.24), rgba(125,211,252,0.50), rgba(250,204,21,0.92));
}
.ps-wrapped-artifact-coin::after,
.ps-wrapped-artifact-badge::after {
    border-radius: 999px;
    inset: 24%;
    background: rgba(2,6,23,0.55);
}
.ps-wrapped-artifact-parcel::before {
    border-radius: 22px;
    transform: rotate(7deg);
}
.ps-wrapped-artifact-parcel::after {
    inset: 46% 0 auto;
    height: 10%;
    border-radius: 999px;
    background: rgba(250,204,21,0.45);
}
.ps-wrapped-artifact-calendar::before,
.ps-wrapped-artifact-notebook::before {
    border-radius: 18px;
}
.ps-wrapped-artifact-calendar::after,
.ps-wrapped-artifact-notebook::after {
    inset: 16% 18%;
    border-radius: 8px;
    background:
        repeating-linear-gradient(0deg, rgba(255,255,255,0.18) 0 1px, transparent 1px 14px),
        repeating-linear-gradient(90deg, rgba(255,255,255,0.10) 0 1px, transparent 1px 20px);
}
.ps-wrapped-artifact-trophy::before {
    clip-path: polygon(26% 8%, 74% 8%, 68% 58%, 57% 58%, 57% 78%, 74% 78%, 74% 92%, 26% 92%, 26% 78%, 43% 78%, 43% 58%, 32% 58%);
    background: linear-gradient(135deg, rgba(250,204,21,0.84), rgba(255,255,255,0.18));
}
.ps-wrapped-artifact-scope {
    border-radius: 999px;
}
.ps-wrapped-artifact-scope::before {
    border-radius: 999px;
    background: radial-gradient(circle, transparent 35%, rgba(255,255,255,0.14) 36%, rgba(255,255,255,0.06) 62%, transparent 63%);
}
.ps-wrapped-artifact-scope::after {
    inset: 50% 0 auto;
    height: 1px;
    background: rgba(125,211,252,0.58);
    box-shadow: 0 -2.6rem 0 rgba(125,211,252,0.20), 0 2.6rem 0 rgba(125,211,252,0.20);
}
.ps-wrapped-artifact-spark::before {
    clip-path: polygon(50% 0, 62% 36%, 100% 50%, 62% 64%, 50% 100%, 38% 64%, 0 50%, 38% 36%);
    background: linear-gradient(135deg, #facc15, #7dd3fc);
}
.ps-wrapped-artifact-table::before {
    border-radius: 26px;
    transform: perspective(280px) rotateX(54deg) rotateZ(-7deg);
}
.ps-wrapped-artifact-trainer::before {
    border-radius: 28px;
    background:
        linear-gradient(135deg, rgba(255,255,255,0.18), rgba(255,255,255,0.05)),
        radial-gradient(circle at 50% 18%, rgba(250,204,21,0.26), transparent 28%);
}
.ps-wrapped-artifact-trainer::after {
    inset: 12%;
    border-radius: 22px;
    border: 1px solid rgba(250,204,21,0.22);
}
@keyframes psWrappedArtifactFloat {
    from { transform: translate3d(0, 0, 0) rotate(-3deg); }
    to { transform: translate3d(-0.6rem, -0.9rem, 0) rotate(3deg); }
}
.ps-wrapped-particles {
    background:
        radial-gradient(circle at 18% 22%, rgba(255,255,255,0.26) 0 1px, transparent 2px),
        radial-gradient(circle at 80% 18%, rgba(186,230,253,0.24) 0 1px, transparent 2px),
        radial-gradient(circle at 72% 78%, rgba(253,224,71,0.20) 0 1px, transparent 2px);
    background-size: 15rem 15rem, 19rem 19rem, 23rem 23rem;
    opacity: 0.26;
    animation: psWrappedParticles 20s linear infinite;
}
.ps-wrapped-holo-ring {
    width: min(72vw, 54rem);
    height: min(72vw, 54rem);
    inset: 50% auto auto 50%;
    transform: translate(-50%, -50%);
    border-radius: 999px;
    background:
        conic-gradient(from 120deg, transparent, rgba(255,255,255,0.07), rgba(125,211,252,0.10), rgba(250,204,21,0.08), transparent);
    filter: blur(24px);
    opacity: 0.22;
    animation: psWrappedRing 16s ease-in-out infinite alternate;
}
.ps-wrapped-scene-revenue {
    background:
        linear-gradient(118deg, rgba(250,204,21,0.10), transparent 32%, rgba(34,197,94,0.09)),
        radial-gradient(circle at 78% 14%, rgba(148,163,184,0.20), transparent 34%),
        linear-gradient(145deg, #04100d 0%, #081727 50%, #130f21 100%);
}
.ps-wrapped-scene-profit {
    background:
        linear-gradient(135deg, rgba(250,204,21,0.12), transparent 34%, rgba(168,85,247,0.08)),
        radial-gradient(circle at 78% 18%, rgba(255,255,255,0.12), transparent 28%),
        linear-gradient(145deg, #090711 0%, #171226 52%, #0f172a 100%);
}
.ps-wrapped-scene-mvp,
.ps-wrapped-scene-pull {
    background:
        linear-gradient(125deg, rgba(250,204,21,0.10), transparent 30%, rgba(14,165,233,0.10)),
        radial-gradient(circle at 50% 12%, rgba(255,255,255,0.12), transparent 32%),
        linear-gradient(145deg, #040611 0%, #10172f 48%, #061526 100%);
}
.ps-wrapped-scene-deal {
    background:
        linear-gradient(120deg, rgba(34,197,94,0.14), transparent 32%, rgba(250,204,21,0.12)),
        linear-gradient(145deg, #020617 0%, #0f172a 50%, #1f1b45 100%);
}
.ps-wrapped-scene-month,
.ps-wrapped-scene-sold {
    background:
        linear-gradient(135deg, rgba(59,130,246,0.12), transparent 38%, rgba(244,114,182,0.08)),
        linear-gradient(145deg, #070318 0%, #111936 50%, #041326 100%);
}
.ps-wrapped-scene-lot,
.ps-wrapped-scene-risk,
.ps-wrapped-scene-stock,
.ps-wrapped-scene-timeline {
    background:
        linear-gradient(125deg, rgba(125,211,252,0.08), transparent 28%, rgba(250,204,21,0.08)),
        radial-gradient(circle at 8% 84%, rgba(255,255,255,0.08), transparent 28%),
        linear-gradient(145deg, #030712 0%, #101827 52%, #160f28 100%);
}
.ps-wrapped-scene-profile,
.ps-wrapped-scene-final {
    background:
        linear-gradient(115deg, rgba(250,204,21,0.12), transparent 30%, rgba(14,165,233,0.10)),
        radial-gradient(circle at 50% 0%, rgba(255,255,255,0.10), transparent 30%),
        linear-gradient(145deg, #050816 0%, #17112d 46%, #020617 100%);
}
.ps-wrapped-scene-intro .ps-wrapped-card-back {
    opacity: 0.58;
    right: clamp(-12rem, -9vw, -4rem);
}
.ps-wrapped-scene-mvp .ps-wrapped-card-back,
.ps-wrapped-scene-pull .ps-wrapped-card-back,
.ps-wrapped-scene-lot .ps-wrapped-card-back {
    opacity: 0.66;
    filter: drop-shadow(0 0 34px rgba(250,204,21,0.10));
}
.ps-wrapped-scene-deal .ps-wrapped-foil-band,
.ps-wrapped-scene-profit .ps-wrapped-foil-band {
    opacity: 0.68;
}
@keyframes psWrappedFoilBand {
    from { transform: translateX(-6vw) rotate(17deg); opacity: 0.34; }
    to { transform: translateX(8vw) rotate(17deg); opacity: 0.58; }
}
@keyframes psWrappedCardBack {
    from { transform: translateY(-50%) rotate(-10deg) scale(0.98); }
    to { transform: translateY(-50%) rotate(-7deg) scale(1.02); }
}
@keyframes psWrappedParticles {
    from { transform: translate3d(0, 0, 0); }
    to { transform: translate3d(-8rem, 5rem, 0); }
}
@keyframes psWrappedRing {
    from { transform: translate(-50%, -50%) rotate(-10deg) scale(0.92); opacity: 0.28; }
    to { transform: translate(-50%, -50%) rotate(18deg) scale(1.05); opacity: 0.52; }
}
.ps-wrapped-hero,
.ps-wrapped-controls,
.ps-wrapped-details {
    position: relative;
    z-index: 2;
}
.ps-wrapped-hero {
    min-height: 0;
    height: 100%;
    display: grid;
    grid-template-rows: auto minmax(0, 1fr);
    gap: clamp(0.55rem, 1.45dvh, 1.05rem);
}
@keyframes psWrappedGrid {
    from { transform: translate3d(0,0,0); }
    to { transform: translate3d(42px,42px,0); }
}
@keyframes psWrappedOrb {
    from { transform: translate3d(0,0,0) scale(1); opacity: 0.7; }
    to { transform: translate3d(26px,-20px,0) scale(1.16); opacity: 0.95; }
}
.ps-wrapped-top {
    position: relative;
    z-index: 6;
    display: grid;
    grid-template-columns: 1fr auto;
    align-items: start;
    gap: 1rem;
}
.ps-wrapped-brand {
    display: inline-flex;
    align-items: center;
    gap: 0.55rem;
    width: fit-content;
    padding: 0.42rem 0.72rem;
    border: 1px solid rgba(255,255,255,0.18);
    border-radius: 999px;
    background: rgba(255,255,255,0.12);
    backdrop-filter: blur(16px);
    color: rgba(255,255,255,0.86);
    font-size: 0.76rem;
    font-weight: 900;
    text-transform: uppercase;
    letter-spacing: 0.12em;
}
.ps-wrapped-brand::before {
    content: "DX";
    width: 1.55rem;
    height: 1.55rem;
    display: grid;
    place-items: center;
    border-radius: 999px;
    color: #111827;
    background: linear-gradient(135deg, #facc15, #7dd3fc);
    font-size: 0.62rem;
    font-weight: 950;
    letter-spacing: 0;
}
.ps-wrapped-count {
    color: rgba(255,255,255,0.68);
    font-weight: 800;
    font-size: 0.72rem;
    text-align: right;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.ps-wrapped-progress {
    grid-column: 1 / -1;
    height: 3px;
    border-radius: 999px;
    background: rgba(255,255,255,0.18);
    overflow: hidden;
}
.ps-wrapped-progress span {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, #facc15, #ffffff, #7dd3fc);
    box-shadow: 0 0 18px rgba(250, 204, 21, 0.34);
    transition: width 0.35s ease;
}
.ps-wrapped-story {
    position: relative;
    z-index: 5;
    display: grid;
    align-content: center;
    justify-items: center;
    text-align: center;
    gap: clamp(0.5rem, 1.25dvh, 1rem);
    padding: clamp(0.35rem, 1.6dvh, 1.35rem) clamp(0.55rem, 2.2vw, 1.7rem);
    max-height: 100%;
    animation: psWrappedIn 0.38s cubic-bezier(.2,.8,.2,1) both;
}
.ps-wrapped-story::before {
    content: "";
    position: absolute;
    inset: 8% 12%;
    z-index: -1;
    border-radius: 999px;
    background: radial-gradient(circle, rgba(255,255,255,0.10), transparent 58%);
    filter: blur(18px);
    opacity: 0.52;
    transform: scale(0.9);
    animation: psWrappedBreath 5.8s ease-in-out infinite alternate;
}
.ps-wrapped-layout-card::before,
.ps-wrapped-layout-duo::before {
    inset: 3% 18%;
    border-radius: 34px;
    background:
        linear-gradient(115deg, transparent, rgba(250,204,21,0.08), transparent),
        radial-gradient(circle, rgba(255,255,255,0.08), transparent 64%);
}
.ps-wrapped-layout-hero .ps-wrapped-kicker,
.ps-wrapped-layout-number .ps-wrapped-kicker,
.ps-wrapped-layout-profile .ps-wrapped-kicker,
.ps-wrapped-layout-final .ps-wrapped-kicker {
    transform: translateY(-0.15rem);
}
.ps-wrapped-layout-number .ps-wrapped-big-number {
    padding: 0.04em 0.12em 0.12em;
    border-radius: clamp(1.2rem, 3vw, 2.4rem);
    background:
        radial-gradient(circle at 25% 0%, rgba(255,255,255,0.16), transparent 42%),
        linear-gradient(135deg, rgba(255,255,255,0.10), rgba(255,255,255,0.035));
    border: 1px solid rgba(255,255,255,0.13);
    box-shadow: 0 32px 90px rgba(0,0,0,0.24), 0 0 68px rgba(250,204,21,0.16);
}
.ps-wrapped-layout-card .ps-wrapped-title,
.ps-wrapped-layout-duo .ps-wrapped-title,
.ps-wrapped-layout-timeline .ps-wrapped-title {
    font-size: clamp(1.35rem, 4.8vw, 3.65rem);
}
.ps-wrapped-layout-card .ps-wrapped-big-number {
    font-size: clamp(1.95rem, 6.4vw, 4.8rem);
}
.ps-wrapped-layout-duo .ps-wrapped-big-number,
.ps-wrapped-layout-profile .ps-wrapped-big-number {
    font-size: clamp(2rem, 7vw, 5.4rem);
}
@keyframes psWrappedIn {
    from { opacity: 0; transform: translateY(18px) scale(0.975); filter: blur(5px); }
    to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
@keyframes psWrappedBreath {
    from { opacity: 0.32; transform: scale(0.88); }
    to { opacity: 0.62; transform: scale(1.08); }
}
.ps-wrapped-kicker {
    padding: 0.36rem 0.72rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.16);
    color: rgba(255,255,255,0.78);
    font-size: clamp(0.62rem, 1.7vw, 0.74rem);
    font-weight: 900;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
}
.ps-wrapped-scene-revenue .ps-wrapped-kicker,
.ps-wrapped-scene-profit .ps-wrapped-kicker {
    background: rgba(250,204,21,0.13);
    border-color: rgba(250,204,21,0.24);
}
.ps-wrapped-scene-mvp .ps-wrapped-kicker,
.ps-wrapped-scene-pull .ps-wrapped-kicker {
    background: rgba(56,189,248,0.12);
    border-color: rgba(56,189,248,0.24);
}
.ps-wrapped-scene-deal .ps-wrapped-kicker {
    background: rgba(34,197,94,0.12);
    border-color: rgba(34,197,94,0.24);
}
.ps-wrapped-title {
    width: min(920px, calc(100vw - 2rem));
    max-width: 100%;
    margin: 0 auto;
    font-size: clamp(1.55rem, 6.1vw, 4.65rem);
    line-height: 1.06;
    font-weight: 950;
    letter-spacing: 0;
    text-wrap: balance;
    color: #ffffff;
    text-shadow: 0 18px 60px rgba(0,0,0,0.35);
    animation: psWrappedTitleReveal 0.58s cubic-bezier(.2,.8,.2,1) both;
}
.ps-wrapped-big-number {
    max-width: min(980px, calc(100vw - 2rem));
    font-size: clamp(2.45rem, 9.8vw, 6.7rem);
    line-height: 0.98;
    font-weight: 950;
    letter-spacing: -0.04em;
    color: transparent;
    background: linear-gradient(135deg, #fff7cc 0%, #facc15 36%, #7dd3fc 78%, #ffffff 100%);
    -webkit-background-clip: text;
    background-clip: text;
    text-shadow:
        0 0 22px rgba(250, 204, 21, 0.34),
        0 20px 60px rgba(250, 204, 21, 0.18);
    animation: psWrappedPop 0.48s cubic-bezier(.2,.8,.2,1) both;
}
@keyframes psWrappedTitleReveal {
    from { opacity: 0; transform: translateY(12px); }
    to { opacity: 1; transform: translateY(0); }
}
.ps-wrapped-big-number::first-letter {
    letter-spacing: -0.02em;
}
@keyframes psWrappedPop {
    from { opacity: 0; transform: scale(0.82); filter: blur(5px); }
    to { opacity: 1; transform: scale(1); }
}
.ps-wrapped-subtitle {
    width: min(760px, calc(100vw - 2rem));
    max-width: 100%;
    color: rgba(255,255,255,0.76);
    font-size: clamp(0.86rem, 1.85vw, 1.12rem);
    line-height: 1.42;
    font-weight: 650;
    animation: psWrappedSubtitleReveal 0.7s cubic-bezier(.2,.8,.2,1) both;
    animation-delay: 0.04s;
}
@keyframes psWrappedSubtitleReveal {
    from { opacity: 0; transform: translateY(9px); }
    to { opacity: 1; transform: translateY(0); }
}
.ps-wrapped-glass-grid {
    width: min(900px, 100%);
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.8rem;
    margin-top: 0.25rem;
}
.ps-wrapped-mini-strip {
    width: min(900px, 100%);
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
    gap: 0.7rem;
    margin-top: 0.1rem;
}
.ps-wrapped-mini-stat {
    min-height: 5.1rem;
    display: grid;
    align-content: center;
    gap: 0.2rem;
    padding: 0.82rem 0.95rem;
    border-radius: 20px;
    border: 1px solid rgba(255,255,255,0.17);
    background: linear-gradient(180deg, rgba(255,255,255,0.14), rgba(255,255,255,0.075));
    box-shadow: 0 15px 38px rgba(0,0,0,0.18), inset 0 1px 0 rgba(255,255,255,0.12);
}
.ps-wrapped-mini-stat span {
    color: rgba(255,255,255,0.66);
    font-size: 0.68rem;
    font-weight: 900;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}
.ps-wrapped-mini-stat strong {
    color: #ffffff;
    font-size: clamp(1.2rem, 3.4vw, 2.1rem);
    line-height: 1;
    font-weight: 950;
}
.ps-wrapped-metric {
    min-height: 7.2rem;
    display: grid;
    align-content: center;
    gap: 0.24rem;
    border: 1px solid rgba(255,255,255,0.18);
    background: linear-gradient(180deg, rgba(255,255,255,0.16), rgba(255,255,255,0.08));
    backdrop-filter: blur(18px);
    border-radius: 22px;
    padding: 1rem;
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.12), 0 18px 45px rgba(0,0,0,0.18);
}
.ps-wrapped-metric span {
    display: block;
    color: rgba(255,255,255,0.68);
    font-size: 0.72rem;
    font-weight: 900;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.ps-wrapped-metric strong {
    display: block;
    color: #ffffff;
    font-size: clamp(1.35rem, 3.2vw, 2.3rem);
    line-height: 1;
    font-weight: 950;
}
.ps-wrapped-metric em {
    color: rgba(255,255,255,0.62);
    font-style: normal;
    font-size: 0.82rem;
    font-weight: 700;
}
.ps-wrapped-list {
    width: min(840px, 100%);
    display: grid;
    gap: 0.62rem;
}
.ps-wrapped-feature {
    width: min(780px, 100%);
    display: grid;
    grid-template-columns: minmax(6.2rem, min(12rem, 30dvh)) 1fr;
    align-items: center;
    gap: 1rem;
    padding: 1rem;
    border: 1px solid rgba(255,255,255,0.22);
    border-radius: 26px;
    background: linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.08));
    backdrop-filter: blur(18px);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.14), 0 28px 70px rgba(0,0,0,0.27);
    text-align: left;
}
.ps-wrapped-feature span {
    display: block;
    color: rgba(255,255,255,0.65);
    font-size: 0.72rem;
    font-weight: 900;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 0.35rem;
}
.ps-wrapped-feature strong {
    display: block;
    color: #ffffff;
    font-size: clamp(1.15rem, 3.4vw, 2.25rem);
    line-height: 1.08;
    font-weight: 950;
}
.ps-wrapped-feature em {
    display: block;
    margin-top: 0.45rem;
    color: rgba(255,255,255,0.70);
    font-style: normal;
    font-size: 0.92rem;
    font-weight: 700;
}
.ps-wrapped-card-visual {
    width: 100%;
    aspect-ratio: 0.72;
    display: grid;
    place-items: center;
    border-radius: 18px;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.20);
    overflow: hidden;
    box-shadow: 0 20px 46px rgba(0,0,0,0.26), 0 0 42px rgba(14,165,233,0.14);
}
.ps-wrapped-card-visual::before {
    content: "";
    position: absolute;
    inset: -38%;
    background: linear-gradient(115deg, transparent 36%, rgba(255,255,255,0.20) 48%, transparent 60%);
    transform: translateX(-26%) rotate(10deg);
    animation: psWrappedCardShine 4.8s ease-in-out infinite;
    pointer-events: none;
}
.ps-wrapped-card-visual {
    position: relative;
}
.ps-wrapped-card-visual img {
    width: 100%;
    height: 100%;
    object-fit: contain;
    position: relative;
    z-index: 1;
}
@keyframes psWrappedCardShine {
    0%, 100% { transform: translateX(-32%) rotate(10deg); opacity: 0.18; }
    45% { transform: translateX(28%) rotate(10deg); opacity: 0.45; }
}
.ps-wrapped-card-placeholder span {
    padding: 0.8rem;
    color: rgba(255,255,255,0.62);
    text-align: center;
    font-size: 0.82rem;
    font-weight: 850;
}
.ps-wrapped-row {
    display: grid;
    grid-template-columns: auto 1fr;
    align-items: center;
    gap: 0.85rem;
    padding: 0.82rem 0.95rem;
    border: 1px solid rgba(255,255,255,0.17);
    border-radius: 18px;
    background: rgba(255,255,255,0.115);
    backdrop-filter: blur(16px);
    text-align: left;
}
.ps-wrapped-rank {
    width: 2.35rem;
    height: 2.35rem;
    border-radius: 999px;
    display: grid !important;
    place-items: center;
    background: linear-gradient(135deg, #facc15, #fb7185);
    color: #111827 !important;
    font-weight: 950;
}
.ps-wrapped-row strong {
    display: block;
    color: #ffffff;
    font-size: 1rem;
    line-height: 1.2;
}
.ps-wrapped-row span:not(.ps-wrapped-rank) {
    display: block;
    color: rgba(255,255,255,0.64);
    font-size: 0.84rem;
    font-weight: 650;
    margin-top: 0.12rem;
}
.ps-wrapped-empty {
    padding: 1rem;
    border-radius: 18px;
    border: 1px solid rgba(255,255,255,0.16);
    background: rgba(255,255,255,0.1);
    color: rgba(255,255,255,0.76);
    font-weight: 800;
}
.ps-wrapped-chip-row {
    width: min(760px, 100%);
    display: flex;
    justify-content: center;
    align-items: stretch;
    gap: 0.7rem;
    flex-wrap: wrap;
    margin-top: 0.2rem;
}
.ps-wrapped-chip {
    min-width: min(13rem, 100%);
    display: grid;
    gap: 0.18rem;
    padding: 0.78rem 1rem;
    border-radius: 999px;
    border: 1px solid rgba(255,255,255,0.20);
    background:
        linear-gradient(135deg, rgba(255,255,255,0.18), rgba(255,255,255,0.075)),
        radial-gradient(circle at 20% 0%, rgba(250,204,21,0.18), transparent 52%);
    box-shadow: inset 0 1px 0 rgba(255,255,255,0.15), 0 16px 40px rgba(0,0,0,0.18);
    backdrop-filter: blur(18px);
}
.ps-wrapped-chip span {
    color: rgba(255,255,255,0.62);
    font-size: 0.66rem;
    font-weight: 950;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.ps-wrapped-chip strong {
    color: #ffffff;
    font-size: clamp(1rem, 2.4vw, 1.45rem);
    line-height: 1.05;
    font-weight: 950;
}
.ps-wrapped-scene-visual {
    width: min(195px, 30vw, 27dvh);
    max-height: min(28dvh, 290px);
    margin: 0.1rem auto 0.2rem;
    animation: psWrappedFloat 4.8s ease-in-out infinite;
    filter: drop-shadow(0 26px 46px rgba(0,0,0,0.34));
}
.ps-wrapped-story:has(.ps-wrapped-scene-visual) {
    gap: clamp(0.34rem, 0.85dvh, 0.72rem);
}
.ps-wrapped-story:has(.ps-wrapped-scene-visual) .ps-wrapped-scene-visual {
    width: min(180px, 28vw, 24dvh);
    max-height: 24dvh;
}
.ps-wrapped-story:has(.ps-wrapped-scene-visual) .ps-wrapped-chip {
    padding: 0.54rem 0.82rem;
}
.ps-wrapped-scene-visual .ps-wrapped-card-visual {
    border-radius: 24px;
    background:
        radial-gradient(circle at 25% 5%, rgba(250,204,21,0.20), transparent 42%),
        linear-gradient(135deg, rgba(255,255,255,0.17), rgba(255,255,255,0.055));
    border-color: rgba(255,255,255,0.32);
}
@keyframes psWrappedFloat {
    0%, 100% { transform: translateY(0) rotate(-1deg); }
    50% { transform: translateY(-10px) rotate(1deg); }
}
.ps-wrapped-profile-card {
    width: min(760px, 100%);
    display: grid;
    justify-items: center;
    gap: 0.32rem;
    padding: clamp(1.1rem, 3vw, 1.8rem);
    border-radius: 30px;
    border: 1px solid rgba(255,255,255,0.24);
    background:
        linear-gradient(135deg, rgba(34,197,94,0.22), rgba(14,165,233,0.12)),
        radial-gradient(circle at 18% 10%, rgba(250,204,21,0.22), transparent 42%);
    box-shadow: 0 28px 72px rgba(0,0,0,0.26), inset 0 1px 0 rgba(255,255,255,0.18);
    text-align: center;
    position: relative;
    overflow: hidden;
}
.ps-wrapped-profile-card::before {
    content: "";
    position: absolute;
    inset: -40%;
    background: conic-gradient(from 160deg, transparent, rgba(250,204,21,0.20), rgba(56,189,248,0.22), transparent);
    animation: psWrappedRing 12s ease-in-out infinite alternate;
    pointer-events: none;
}
.ps-wrapped-profile-card > * {
    position: relative;
    z-index: 1;
}
.ps-wrapped-profile-card span,
.ps-wrapped-share-top span,
.ps-wrapped-share-profile span {
    color: rgba(255,255,255,0.68);
    font-size: 0.72rem;
    font-weight: 950;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}
.ps-wrapped-profile-card strong {
    color: #ffffff;
    font-size: clamp(1.8rem, 5.6vw, 3.9rem);
    line-height: 1.04;
    font-weight: 950;
    text-shadow: 0 0 30px rgba(34,197,94,0.24);
}
.ps-wrapped-profile-card em,
.ps-wrapped-profile-card small {
    max-width: 560px;
    color: rgba(255,255,255,0.78);
    font-style: normal;
    font-weight: 750;
    line-height: 1.45;
}
.ps-wrapped-profile-card small {
    color: rgba(255,255,255,0.58);
    font-size: 0.82rem;
}
.ps-wrapped-share-preview {
    width: min(420px, 82vw);
    aspect-ratio: 9 / 14.5;
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: 1rem;
    padding: clamp(1rem, 4vw, 1.35rem);
    border-radius: 34px;
    border: 1px solid rgba(255,255,255,0.28);
    background:
        linear-gradient(122deg, rgba(255,255,255,0.09), transparent 22%, rgba(250,204,21,0.12) 42%, transparent 62%),
        radial-gradient(circle at 18% 8%, rgba(250,204,21,0.22), transparent 34%),
        radial-gradient(circle at 88% 82%, rgba(56,189,248,0.18), transparent 34%),
        linear-gradient(145deg, rgba(5,8,22,0.96), rgba(36,16,79,0.95));
    box-shadow: 0 34px 88px rgba(0,0,0,0.36), inset 0 1px 0 rgba(255,255,255,0.20);
    text-align: left;
    overflow: hidden;
    position: relative;
}
.ps-wrapped-share-shine {
    position: absolute;
    inset: -20%;
    z-index: 0;
    background:
        radial-gradient(circle at 25% 12%, rgba(250,204,21,0.20), transparent 32%),
        radial-gradient(circle at 82% 86%, rgba(56,189,248,0.22), transparent 34%),
        linear-gradient(115deg, transparent 33%, rgba(255,255,255,0.10) 47%, transparent 61%);
    animation: psWrappedHolo 6.2s ease-in-out infinite;
    pointer-events: none;
}
.ps-wrapped-share-preview::after {
    content: "";
    position: absolute;
    inset: -40%;
    background: linear-gradient(115deg, transparent 32%, rgba(255,255,255,0.18) 45%, transparent 58%);
    transform: rotate(10deg);
    animation: psWrappedHolo 5.6s ease-in-out infinite;
    pointer-events: none;
}
.ps-wrapped-share-preview::before {
    content: "";
    position: absolute;
    inset: 0.55rem;
    border-radius: 28px;
    border: 1px solid rgba(255,255,255,0.12);
    pointer-events: none;
    z-index: 1;
}
@keyframes psWrappedHolo {
    0%, 100% { transform: translateX(-18%) rotate(10deg); opacity: 0.28; }
    50% { transform: translateX(18%) rotate(10deg); opacity: 0.52; }
}
.ps-wrapped-share-top,
.ps-wrapped-share-grid,
.ps-wrapped-share-profile {
    position: relative;
    z-index: 1;
}
.ps-wrapped-share-top strong {
    display: block;
    color: #ffffff;
    font-size: clamp(1.05rem, 3vw, 1.75rem);
    line-height: 1.12;
    font-weight: 950;
    margin-top: 0.32rem;
}
.ps-wrapped-share-grid {
    display: grid;
    align-content: center;
    gap: 0.62rem;
}
.ps-wrapped-share-grid div,
.ps-wrapped-share-profile {
    padding: 0.82rem 0.9rem;
    border-radius: 20px;
    background:
        linear-gradient(135deg, rgba(255,255,255,0.135), rgba(255,255,255,0.065)),
        radial-gradient(circle at 0% 0%, rgba(250,204,21,0.08), transparent 38%);
    border: 1px solid rgba(255,255,255,0.16);
}
.ps-wrapped-share-grid span {
    display: block;
    color: rgba(255,255,255,0.62);
    font-size: 0.66rem;
    font-weight: 950;
    letter-spacing: 0.1em;
    text-transform: uppercase;
}
.ps-wrapped-share-grid strong,
.ps-wrapped-share-profile strong {
    display: block;
    color: #ffffff;
    font-size: clamp(0.98rem, 3.2vw, 1.48rem);
    line-height: 1.12;
    font-weight: 950;
    margin-top: 0.18rem;
}
.ps-wrapped-deal-card,
.ps-wrapped-stock-card {
    width: min(760px, 100%);
    display: grid;
    grid-template-columns: minmax(6.4rem, min(12rem, 30dvh)) 1fr;
    align-items: center;
    gap: 1rem;
    padding: clamp(0.9rem, 2.6vw, 1.35rem);
    border-radius: 30px;
    border: 1px solid rgba(255,255,255,0.23);
    background:
        radial-gradient(circle at 0% 0%, rgba(250,204,21,0.22), transparent 38%),
        linear-gradient(135deg, rgba(255,255,255,0.16), rgba(255,255,255,0.07));
    box-shadow: 0 30px 74px rgba(0,0,0,0.26), inset 0 1px 0 rgba(255,255,255,0.15);
    backdrop-filter: blur(18px);
    text-align: left;
}
.ps-wrapped-stock-card {
    background:
        radial-gradient(circle at 100% 0%, rgba(34,197,94,0.22), transparent 38%),
        linear-gradient(135deg, rgba(255,255,255,0.15), rgba(255,255,255,0.065));
}
.ps-wrapped-deal-card .ps-wrapped-scene-visual,
.ps-wrapped-stock-card .ps-wrapped-scene-visual {
    width: min(100%, 10.4rem, 25dvh);
    max-height: 25dvh;
}
.ps-wrapped-deal-copy span,
.ps-wrapped-stock-card span {
    display: block;
    color: rgba(255,255,255,0.66);
    font-size: 0.72rem;
    font-weight: 950;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.38rem;
}
.ps-wrapped-deal-copy strong,
.ps-wrapped-stock-card strong {
    display: block;
    color: #ffffff;
    font-size: clamp(1.12rem, 3.4vw, 2.25rem);
    line-height: 1.08;
    font-weight: 950;
}
.ps-wrapped-deal-copy em,
.ps-wrapped-deal-copy small,
.ps-wrapped-stock-card em,
.ps-wrapped-stock-card small {
    display: block;
    color: rgba(255,255,255,0.72);
    font-style: normal;
    font-size: 0.92rem;
    font-weight: 750;
    line-height: 1.35;
    margin-top: 0.42rem;
}
.ps-wrapped-deal-copy small,
.ps-wrapped-stock-card small {
    color: #facc15;
    font-weight: 900;
}
.ps-wrapped-timeline {
    width: min(760px, 100%);
    display: grid;
    gap: 0.7rem;
    position: relative;
}
.ps-wrapped-timeline::before {
    content: "";
    position: absolute;
    top: 1.4rem;
    bottom: 1.4rem;
    left: 1.35rem;
    width: 2px;
    background: linear-gradient(#facc15, #38bdf8, #a78bfa);
    opacity: 0.45;
}
.ps-wrapped-timeline-item {
    position: relative;
    display: grid;
    grid-template-columns: 2.8rem 1fr;
    align-items: center;
    gap: 0.8rem;
    padding: 0.78rem 0.95rem;
    border-radius: 20px;
    border: 1px solid rgba(255,255,255,0.18);
    background: rgba(255,255,255,0.11);
    backdrop-filter: blur(14px);
    text-align: left;
}
.ps-wrapped-timeline-item > span {
    width: 2.7rem;
    height: 2.7rem;
    display: grid;
    place-items: center;
    border-radius: 999px;
    color: #111827;
    background: linear-gradient(135deg, #facc15, #38bdf8);
    font-weight: 950;
    box-shadow: 0 0 24px rgba(56,189,248,0.26);
}
.ps-wrapped-timeline-item strong {
    display: block;
    color: #ffffff;
    font-size: 0.84rem;
    font-weight: 950;
    letter-spacing: 0.08em;
    text-transform: uppercase;
}
.ps-wrapped-timeline-item em {
    display: block;
    color: #ffffff;
    font-style: normal;
    font-size: 1.08rem;
    line-height: 1.18;
    font-weight: 900;
    margin-top: 0.1rem;
}
.ps-wrapped-timeline-item small {
    color: rgba(255,255,255,0.62);
    font-weight: 750;
}
.ps-wrapped-final-panel {
    width: min(880px, 100%);
    display: grid;
    justify-items: center;
    gap: 0.34rem;
    padding: clamp(1.25rem, 3vw, 2.1rem);
    border-radius: 30px;
    border: 1px solid rgba(255,255,255,0.20);
    background:
        radial-gradient(circle at 20% 0%, rgba(250,204,21,0.26), transparent 34%),
        radial-gradient(circle at 100% 100%, rgba(56,189,248,0.22), transparent 34%),
        linear-gradient(135deg, rgba(255,255,255,0.18), rgba(255,255,255,0.08));
    box-shadow: 0 30px 80px rgba(0,0,0,0.28), inset 0 1px 0 rgba(255,255,255,0.16);
}
.ps-wrapped-final-panel span {
    color: rgba(255,255,255,0.72);
    font-size: 0.76rem;
    font-weight: 950;
    letter-spacing: 0.14em;
    text-transform: uppercase;
}
.ps-wrapped-final-panel strong {
    color: #facc15;
    font-size: clamp(2.35rem, 8.4vw, 6.1rem);
    line-height: 1;
    font-weight: 950;
    letter-spacing: -0.04em;
    text-shadow: 0 0 26px rgba(250,204,21,0.35);
}
.ps-wrapped-final-panel em {
    color: rgba(255,255,255,0.78);
    font-style: normal;
    font-size: clamp(0.95rem, 2vw, 1.18rem);
    font-weight: 800;
    text-align: center;
}
.ps-wrapped-controls {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-top: 0.2rem;
}
.ps-wrapped-controls .stButton > button {
    min-height: 3.15rem !important;
    border-radius: 999px !important;
    font-weight: 900 !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.22) !important;
    background: rgba(255,255,255,0.12) !important;
    box-shadow: 0 16px 38px rgba(0,0,0,0.20) !important;
    backdrop-filter: blur(12px) !important;
}
.ps-wrapped-controls .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #7c3aed, #0ea5e9) !important;
    border-color: rgba(255,255,255,0.26) !important;
}
.ps-wrapped-controls .stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 22px 52px rgba(0,0,0,0.28) !important;
}
.ps-wrapped-bottom-hint {
    display: none;
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-hero {
    padding-bottom: clamp(6.9rem, 14dvh, 8.4rem);
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-story {
    align-content: start;
    gap: clamp(0.32rem, 0.85dvh, 0.62rem);
    padding-top: clamp(0.25rem, 0.9dvh, 0.75rem);
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-title {
    font-size: clamp(1.25rem, 3.8vw, 2.65rem);
    line-height: 1.12;
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-subtitle {
    font-size: clamp(0.78rem, 1.45vw, 0.98rem);
    line-height: 1.3;
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-preview {
    width: auto;
    height: min(45dvh, 520px);
    max-width: min(84vw, 400px);
    min-height: 0;
    gap: clamp(0.32rem, 0.8dvh, 0.75rem);
    padding: clamp(0.72rem, 1.7dvh, 1.1rem);
    grid-template-rows: auto minmax(0, 1fr) auto;
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-grid {
    gap: clamp(0.25rem, 0.7dvh, 0.5rem);
    min-height: 0;
    align-content: space-evenly;
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-grid div,
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-profile {
    padding: clamp(0.42rem, 0.9dvh, 0.7rem) clamp(0.55rem, 1.5vw, 0.85rem);
    min-height: 0;
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-top strong {
    font-size: clamp(0.95rem, 2.55vw, 1.45rem);
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-grid span,
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-profile span {
    font-size: clamp(0.52rem, 1vw, 0.62rem);
}
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-grid strong,
.ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-share-profile strong {
    font-size: clamp(0.86rem, 2.45vw, 1.22rem);
    line-height: 1.08;
}
.ps-wrapped-story-click-layer {
    height: 0;
    overflow: visible;
}
.stApp:has(.ps-wrapped-shell) .main .stButton > button {
    min-height: 3rem !important;
    border-radius: 999px !important;
    font-weight: 900 !important;
    color: #ffffff !important;
    border: 1px solid rgba(255,255,255,0.22) !important;
    background: rgba(15,23,42,0.88) !important;
    box-shadow: 0 14px 34px rgba(15,23,42,0.22) !important;
}
.stApp:has(.ps-wrapped-shell) .main .stButton > button[kind="primary"] {
    background: linear-gradient(135deg, #7c3aed, #0ea5e9) !important;
    border-color: rgba(255,255,255,0.26) !important;
}
.stApp:has(.ps-wrapped-shell) .main .stButton > button:hover {
    transform: translateY(-2px) !important;
    box-shadow: 0 20px 46px rgba(15,23,42,0.32) !important;
}
.stApp:has(.ps-wrapped-shell) .main .stButton > button:has(p),
.stApp:has(.ps-wrapped-shell) .main .stButton > button p {
    color: inherit !important;
}
.stApp:has(.ps-wrapped-shell) .main .stButton > button[disabled] {
    opacity: 0.38 !important;
    cursor: not-allowed !important;
}
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-story-click-layer) + div [data-testid="stHorizontalBlock"] {
    position: fixed !important;
    inset: 0 !important;
    z-index: 120 !important;
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 0 !important;
    pointer-events: auto !important;
}
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-story-click-layer) + div [data-testid="stHorizontalBlock"] > div,
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-story-click-layer) + div [data-testid="stHorizontalBlock"] [data-testid="column"],
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-story-click-layer) + div [data-testid="stHorizontalBlock"] .stButton,
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-story-click-layer) + div [data-testid="stHorizontalBlock"] .stButton > button {
    height: 100dvh !important;
    min-height: 100dvh !important;
    pointer-events: auto !important;
}
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-story-click-layer) + div [data-testid="stHorizontalBlock"] .stButton > button {
    opacity: 0 !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    background: transparent !important;
    color: transparent !important;
    padding: 0 !important;
}
.stApp:has(.ps-wrapped-shell) .element-container:has(.ps-wrapped-close-zone) + div .stButton > button {
    position: fixed !important;
    left: 50% !important;
    bottom: max(1.2rem, env(safe-area-inset-bottom)) !important;
    width: min(420px, calc(100vw - 2rem)) !important;
    transform: translateX(-50%) !important;
    z-index: 131 !important;
    opacity: 1 !important;
    color: #ffffff !important;
    background: linear-gradient(135deg, #7c3aed, #0ea5e9) !important;
    border: 1px solid rgba(255,255,255,0.30) !important;
    box-shadow: 0 24px 70px rgba(14,165,233,0.34) !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev,
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next {
    position: fixed !important;
    top: 0 !important;
    width: 50vw !important;
    height: 100dvh !important;
    min-height: 100dvh !important;
    z-index: 120 !important;
    pointer-events: auto !important;
    margin: 0 !important;
    padding: 0 !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev {
    left: 0 !important;
    right: auto !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next {
    left: auto !important;
    right: 0 !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev .stButton,
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next .stButton,
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev [data-testid="stButton"],
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next [data-testid="stButton"] {
    width: 100% !important;
    height: 100% !important;
    min-height: 100dvh !important;
    pointer-events: auto !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev button,
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next button {
    position: absolute !important;
    inset: 0 !important;
    width: 100% !important;
    height: 100% !important;
    min-height: 100dvh !important;
    z-index: 120 !important;
    opacity: 0 !important;
    color: transparent !important;
    background: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 0 !important;
    margin: 0 !important;
    cursor: pointer !important;
    pointer-events: auto !important;
    font-size: 0 !important;
    line-height: 0 !important;
    transform: none !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev button *,
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next button * {
    color: transparent !important;
    opacity: 0 !important;
    font-size: 0 !important;
    line-height: 0 !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_download_card button {
    position: fixed !important;
    left: 50% !important;
    bottom: calc(max(1.2rem, env(safe-area-inset-bottom)) + 4.1rem) !important;
    width: min(420px, calc(100vw - 2rem)) !important;
    transform: translateX(-50%) !important;
    z-index: 130 !important;
    opacity: 1 !important;
    color: #ffffff !important;
    background: rgba(255,255,255,0.14) !important;
    border: 1px solid rgba(255,255,255,0.30) !important;
    box-shadow: 0 22px 64px rgba(0,0,0,0.28) !important;
    backdrop-filter: blur(16px) !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_close button {
    position: fixed !important;
    left: 50% !important;
    bottom: max(1.2rem, env(safe-area-inset-bottom)) !important;
    width: min(420px, calc(100vw - 2rem)) !important;
    transform: translateX(-50%) !important;
    z-index: 131 !important;
    opacity: 1 !important;
    color: #ffffff !important;
    background: linear-gradient(135deg, #7c3aed, #0ea5e9) !important;
    border: 1px solid rgba(255,255,255,0.30) !important;
    box-shadow: 0 24px 70px rgba(14,165,233,0.34) !important;
}
.ps-wrapped-details {
    margin-top: 0.75rem;
}
.ps-wrapped-details [data-testid="stExpander"] {
    background: rgba(255,255,255,0.08) !important;
    border-color: rgba(255,255,255,0.12) !important;
}
@media (max-width: 760px) {
    .ps-wrapped-shell {
        min-height: 100dvh;
        height: 100dvh;
        border-radius: 0;
        padding: 0.55rem;
        margin: 0;
        gap: 0.2rem;
    }
    .ps-wrapped-hero {
        min-height: 0;
        height: 100%;
        gap: 0.45rem;
    }
    .ps-wrapped-top {
        grid-template-columns: 1fr;
    }
    .ps-wrapped-count {
        text-align: left;
    }
    .ps-wrapped-story {
        padding: 0.24rem;
        gap: clamp(0.34rem, 0.9dvh, 0.58rem);
    }
    .ps-wrapped-title {
        width: calc(100vw - 1.4rem);
        font-size: clamp(1.38rem, 8.8vw, 3.05rem);
        line-height: 1.1;
    }
    .ps-wrapped-big-number {
        max-width: calc(100vw - 1.4rem);
        font-size: clamp(2.05rem, 14.5vw, 4.65rem);
        line-height: 1;
    }
    .ps-wrapped-subtitle {
        width: calc(100vw - 1.4rem);
        font-size: clamp(0.78rem, 3.4vw, 0.92rem);
        line-height: 1.34;
    }
    .ps-wrapped-chip-row {
        gap: 0.45rem;
    }
    .ps-wrapped-chip {
        min-width: calc(50% - 0.45rem);
        padding: 0.62rem 0.72rem;
    }
    .ps-wrapped-scene-visual {
        width: min(160px, 39vw, 24dvh);
        max-height: 24dvh;
    }
    .ps-wrapped-profile-card {
        border-radius: 22px;
        padding: 1rem;
    }
    .ps-wrapped-profile-card strong {
        font-size: clamp(1.8rem, 11vw, 3.3rem);
    }
    .ps-wrapped-share-preview {
        width: auto;
        height: min(38dvh, 380px);
        max-width: min(78vw, 315px);
        gap: 0.34rem;
        padding: 0.68rem;
        border-radius: 26px;
    }
    .ps-wrapped-share-top strong {
        font-size: clamp(0.92rem, 4.6vw, 1.25rem);
        line-height: 1.1;
    }
    .ps-wrapped-share-grid {
        gap: 0.25rem;
    }
    .ps-wrapped-share-grid div,
    .ps-wrapped-share-profile {
        padding: 0.38rem 0.46rem;
        border-radius: 16px;
    }
    .ps-wrapped-share-grid span,
    .ps-wrapped-share-profile span {
        font-size: 0.56rem;
    }
    .ps-wrapped-share-grid strong,
    .ps-wrapped-share-profile strong {
        font-size: clamp(0.78rem, 4vw, 1.08rem);
        line-height: 1.08;
    }
    .ps-wrapped-deal-card,
    .ps-wrapped-stock-card {
        grid-template-columns: minmax(4.6rem, 22vw) 1fr;
        gap: 0.62rem;
        border-radius: 21px;
        padding: 0.72rem;
    }
.ps-wrapped-deal-card .ps-wrapped-scene-visual,
.ps-wrapped-stock-card .ps-wrapped-scene-visual {
        width: min(100%, 8.6rem, 22dvh);
        max-height: 22dvh;
    }
    .ps-wrapped-deal-copy strong,
    .ps-wrapped-stock-card strong {
        font-size: clamp(0.95rem, 5.3vw, 1.48rem);
        line-height: 1.08;
    }
    .ps-wrapped-deal-copy em,
    .ps-wrapped-deal-copy small,
    .ps-wrapped-stock-card em,
    .ps-wrapped-stock-card small {
        font-size: 0.74rem;
        margin-top: 0.26rem;
    }
    .ps-wrapped-timeline {
        gap: 0.45rem;
    }
    .ps-wrapped-timeline::before {
        left: 1.08rem;
    }
    .ps-wrapped-timeline-item {
        grid-template-columns: 2.2rem 1fr;
        gap: 0.55rem;
        padding: 0.58rem 0.66rem;
        border-radius: 16px;
    }
    .ps-wrapped-timeline-item > span {
        width: 2.15rem;
        height: 2.15rem;
    }
    .ps-wrapped-timeline-item em {
        font-size: 0.82rem;
        line-height: 1.12;
    }
    .ps-wrapped-timeline-item small {
        font-size: 0.72rem;
    }
    .ps-wrapped-glass-grid {
        grid-template-columns: 1fr;
        gap: 0.55rem;
    }
    .ps-wrapped-mini-strip {
        grid-template-columns: 1fr;
        gap: 0.48rem;
    }
    .ps-wrapped-mini-stat {
        min-height: 4.45rem;
        border-radius: 17px;
        padding: 0.72rem 0.82rem;
    }
    .ps-wrapped-metric {
        min-height: 5.2rem;
        border-radius: 18px;
        padding: 0.85rem;
    }
    .ps-wrapped-list {
        gap: 0.48rem;
    }
    .ps-wrapped-row {
        padding: 0.7rem;
        border-radius: 16px;
    }
    .ps-wrapped-feature {
        grid-template-columns: minmax(4.8rem, 23vw) 1fr;
        gap: 0.75rem;
        padding: 0.75rem;
        border-radius: 20px;
    }
    .ps-wrapped-final-panel {
        border-radius: 22px;
        padding: 1rem;
    }
    .ps-wrapped-feature strong {
        font-size: clamp(0.95rem, 5.4vw, 1.55rem);
        line-height: 1.08;
    }
    .ps-wrapped-feature em {
        font-size: 0.78rem;
    }
    .ps-wrapped-controls {
        gap: 0.55rem;
    }
    .ps-wrapped-controls .stButton > button {
        min-height: 2.85rem !important;
        font-size: 0.86rem !important;
    }
    .ps-wrapped-bottom-hint {
        display: none;
    }
    .ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-hero {
        padding-bottom: 6.8rem;
    }
    .ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-story {
        gap: 0.26rem;
        padding-top: 0.1rem;
    }
    .ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-title {
        font-size: clamp(1rem, 6.4vw, 1.85rem);
        line-height: 1.12;
    }
    .ps-wrapped-shell:has(.ps-wrapped-share-preview) .ps-wrapped-subtitle {
        font-size: clamp(0.68rem, 2.9vw, 0.78rem);
        line-height: 1.24;
    }
    .stApp:has(.ps-wrapped-shell) .main .stButton > button {
        min-height: 2.8rem !important;
        font-size: 0.86rem !important;
    }
}

/* Wrapped creative redesign overrides: editorial collector story, crisp text, varied scenes. */
.ps-wrapped-shell {
    background:
        radial-gradient(circle at 14% 14%, rgba(247,213,109,0.10), transparent 22%),
        linear-gradient(135deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 34px),
        linear-gradient(150deg, #04030a 0%, #0c1122 48%, #1e1233 100%) !important;
}
.ps-wrapped-shell::before {
    background:
        linear-gradient(90deg, rgba(255,255,255,0.025) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.018) 1px, transparent 1px) !important;
    background-size: 52px 52px !important;
    mask-image: linear-gradient(90deg, transparent, rgba(0,0,0,0.74) 18%, rgba(0,0,0,0.74) 82%, transparent) !important;
    animation: none !important;
}
.ps-wrapped-shell::after {
    background:
        linear-gradient(135deg, rgba(255,255,255,0.075), transparent 42%),
        repeating-linear-gradient(90deg, rgba(255,255,255,0.045) 0 1px, transparent 1px 18px) !important;
    border: 1px solid rgba(255,255,255,0.10);
    filter: none !important;
    opacity: 0.52;
}
.ps-wrapped-title,
.ps-wrapped-big-number,
.ps-wrapped-feature strong,
.ps-wrapped-share-grid strong,
.ps-wrapped-share-profile strong,
.ps-wrapped-profile-card strong {
    text-shadow: none !important;
    filter: none !important;
    letter-spacing: 0 !important;
}
.ps-wrapped-title {
    max-width: min(980px, 92vw);
    font-size: clamp(2.15rem, 5.9vw, 5.9rem) !important;
    line-height: 0.96 !important;
}
.ps-wrapped-big-number {
    font-size: clamp(3.25rem, 10.5vw, 9.2rem) !important;
    line-height: 0.9 !important;
    color: #ffffff !important;
    background: none !important;
    -webkit-text-fill-color: #ffffff !important;
}
.ps-wrapped-kicker {
    background: rgba(247,213,109,0.12) !important;
    border: 1px solid rgba(247,213,109,0.24) !important;
    color: #f7d56d !important;
}
.ps-wrapped-story,
.ps-wrapped-story > * {
    animation: psWrappedEditorialReveal 560ms cubic-bezier(.16,1,.3,1) both !important;
}
.ps-wrapped-story > *:nth-child(2) { animation-delay: 60ms !important; }
.ps-wrapped-story > *:nth-child(3) { animation-delay: 115ms !important; }
.ps-wrapped-story > *:nth-child(4) { animation-delay: 165ms !important; }
.ps-wrapped-story > *:nth-child(5) { animation-delay: 220ms !important; }
@keyframes psWrappedEditorialReveal {
    from { opacity: 0; transform: translateY(22px) scale(0.985); }
    to { opacity: 1; transform: translateY(0) scale(1); }
}

.ps-wrapped-scene-intro {
    background:
        radial-gradient(circle at 50% 18%, rgba(247,213,109,0.16), transparent 24%),
        linear-gradient(115deg, transparent 0 42%, rgba(255,255,255,0.055) 42% 43%, transparent 43%),
        linear-gradient(150deg, #03030a 0%, #0e1224 54%, #221334 100%) !important;
}
.ps-wrapped-scene-intro .ps-wrapped-story {
    justify-items: center;
    text-align: center;
}
.ps-wrapped-scene-intro .ps-wrapped-artifact {
    right: 50%;
    bottom: 9dvh;
    transform: translateX(50%) rotate(-5deg);
    width: clamp(7rem, 16vw, 13rem);
    height: clamp(7rem, 16vw, 13rem);
    opacity: 0.44;
}

.ps-wrapped-scene-revenue,
.ps-wrapped-scene-profit,
.ps-wrapped-scene-risk {
    background:
        linear-gradient(90deg, rgba(255,255,255,0.035) 0 1px, transparent 1px 100%),
        repeating-linear-gradient(0deg, rgba(255,255,255,0.050) 0 1px, transparent 1px 38px),
        linear-gradient(150deg, #07100e 0%, #0a1722 50%, #181126 100%) !important;
}
.ps-wrapped-scene-profit {
    background:
        radial-gradient(circle at 82% 28%, rgba(247,213,109,0.16), transparent 24%),
        repeating-linear-gradient(0deg, rgba(247,213,109,0.08) 0 1px, transparent 1px 42px),
        linear-gradient(150deg, #08070d 0%, #161220 54%, #0f172a 100%) !important;
}
.ps-wrapped-scene-revenue .ps-wrapped-story,
.ps-wrapped-scene-profit .ps-wrapped-story,
.ps-wrapped-scene-risk .ps-wrapped-story {
    justify-items: start;
    text-align: left;
    align-content: center;
    width: min(980px, 92vw);
    margin-left: clamp(0rem, 4vw, 5rem);
}
.ps-wrapped-scene-revenue .ps-wrapped-story::after,
.ps-wrapped-scene-profit .ps-wrapped-story::after,
.ps-wrapped-scene-risk .ps-wrapped-story::after {
    content: "";
    position: absolute;
    right: clamp(1rem, 8vw, 8rem);
    top: 13dvh;
    width: clamp(7rem, 17vw, 14rem);
    height: clamp(13rem, 34dvh, 24rem);
    border-radius: 18px;
    background:
        linear-gradient(#fff7ed, #fef3c7),
        repeating-linear-gradient(0deg, transparent 0 24px, rgba(17,24,39,0.16) 24px 25px);
    opacity: 0.13;
    transform: rotate(7deg);
    box-shadow: 0 24px 70px rgba(0,0,0,0.24);
}

.ps-wrapped-scene-sold {
    background:
        radial-gradient(circle at 18% 72%, rgba(56,189,248,0.16), transparent 28%),
        linear-gradient(150deg, #050816 0%, #111936 52%, #061526 100%) !important;
}
.ps-wrapped-scene-sold .ps-wrapped-story {
    align-content: end;
    padding-bottom: clamp(3rem, 11dvh, 8rem);
    text-align: right;
    justify-items: end;
}
.ps-wrapped-scene-sold .ps-wrapped-artifact {
    left: clamp(1.2rem, 7vw, 7rem);
    right: auto;
    bottom: clamp(5rem, 14dvh, 10rem);
}

.ps-wrapped-scene-month {
    background:
        linear-gradient(90deg, rgba(255,255,255,0.055) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.040) 1px, transparent 1px),
        linear-gradient(150deg, #060617 0%, #101936 50%, #24142d 100%) !important;
    background-size: 88px 88px, 88px 88px, auto !important;
}
.ps-wrapped-scene-month .ps-wrapped-story {
    width: min(850px, 88vw);
    margin: auto;
    border: 1px solid rgba(255,255,255,0.16);
    border-radius: 36px;
    background: rgba(255,255,255,0.055);
    padding: clamp(1.2rem, 3vw, 2.4rem);
}

.ps-wrapped-layout-card,
.ps-wrapped-layout-duo {
    display: grid !important;
    grid-template-columns: minmax(13rem, 29vw) minmax(0, 1fr);
    grid-template-areas:
        "visual kicker"
        "visual title"
        "visual big"
        "visual sub"
        "visual chips";
    align-items: center;
    justify-items: start;
    text-align: left;
    column-gap: clamp(1rem, 4vw, 4rem);
}
.ps-wrapped-layout-card .ps-wrapped-kicker,
.ps-wrapped-layout-duo .ps-wrapped-kicker { grid-area: kicker; }
.ps-wrapped-layout-card .ps-wrapped-title,
.ps-wrapped-layout-duo .ps-wrapped-title { grid-area: title; }
.ps-wrapped-layout-card .ps-wrapped-big-number,
.ps-wrapped-layout-duo .ps-wrapped-big-number { grid-area: big; }
.ps-wrapped-layout-card .ps-wrapped-subtitle,
.ps-wrapped-layout-duo .ps-wrapped-subtitle { grid-area: sub; }
.ps-wrapped-layout-card .ps-wrapped-scene-visual,
.ps-wrapped-layout-duo .ps-wrapped-scene-visual { grid-area: visual; width: min(28vw, 19rem, 48dvh) !important; max-height: 54dvh !important; }
.ps-wrapped-layout-card .ps-wrapped-chip-row,
.ps-wrapped-layout-duo .ps-wrapped-chip-row,
.ps-wrapped-layout-duo .ps-wrapped-deal-card,
.ps-wrapped-layout-duo .ps-wrapped-stock-card { grid-area: chips; }
.ps-wrapped-scene-mvp,
.ps-wrapped-scene-pull {
    background:
        radial-gradient(circle at 24% 42%, rgba(247,213,109,0.18), transparent 23%),
        linear-gradient(140deg, #040611 0%, #10172f 50%, #061526 100%) !important;
}
.ps-wrapped-scene-lot,
.ps-wrapped-scene-stock {
    background:
        repeating-linear-gradient(90deg, rgba(255,255,255,0.050) 0 1px, transparent 1px 25%),
        repeating-linear-gradient(0deg, rgba(255,255,255,0.040) 0 1px, transparent 1px 33.33%),
        linear-gradient(150deg, #040611 0%, #101827 52%, #160f28 100%) !important;
}
.ps-wrapped-card-visual {
    border-radius: 22px !important;
    background:
        linear-gradient(135deg, rgba(255,255,255,0.13), rgba(255,255,255,0.045)),
        linear-gradient(115deg, transparent 30%, rgba(247,213,109,0.10) 50%, transparent 68%) !important;
    box-shadow: 0 20px 50px rgba(0,0,0,0.26), inset 0 1px 0 rgba(255,255,255,0.15) !important;
}
.ps-wrapped-card-visual img {
    object-fit: contain !important;
    filter: none !important;
}

.ps-wrapped-scene-deal {
    background:
        linear-gradient(150deg, rgba(34,197,94,0.10), transparent 40%),
        repeating-linear-gradient(-8deg, rgba(255,255,255,0.045) 0 1px, transparent 1px 34px),
        linear-gradient(150deg, #020617 0%, #0f172a 50%, #1f1b45 100%) !important;
}
.ps-wrapped-deal-card,
.ps-wrapped-stock-card,
.ps-wrapped-profile-card {
    box-shadow: 0 20px 54px rgba(0,0,0,0.22), inset 0 1px 0 rgba(255,255,255,0.14) !important;
    backdrop-filter: blur(8px) !important;
}

.ps-wrapped-scene-timeline {
    background:
        linear-gradient(90deg, rgba(247,213,109,0.12) 0 1px, transparent 1px),
        linear-gradient(150deg, #050816 0%, #111827 50%, #180f28 100%) !important;
    background-size: 100% 100%, auto !important;
}
.ps-wrapped-timeline-item {
    background: rgba(255,255,255,0.075) !important;
    border-color: rgba(255,255,255,0.14) !important;
}

.ps-wrapped-scene-profile {
    background:
        radial-gradient(circle at 50% 20%, rgba(247,213,109,0.16), transparent 24%),
        linear-gradient(150deg, #050816 0%, #17112d 46%, #020617 100%) !important;
}
.ps-wrapped-scene-profile .ps-wrapped-story {
    justify-items: center;
    text-align: center;
}
.ps-wrapped-profile-card {
    transform: rotate(-1.2deg);
    border-color: rgba(247,213,109,0.30) !important;
}

.ps-wrapped-scene-final {
    background:
        radial-gradient(circle at 50% 12%, rgba(247,213,109,0.14), transparent 25%),
        linear-gradient(150deg, #04030a 0%, #161126 52%, #030712 100%) !important;
}
.ps-wrapped-share-preview {
    aspect-ratio: 9 / 14 !important;
    height: min(51dvh, 560px) !important;
    border-radius: 34px !important;
    background:
        linear-gradient(140deg, rgba(255,255,255,0.16), rgba(255,255,255,0.045)),
        radial-gradient(circle at 20% 15%, rgba(247,213,109,0.22), transparent 32%),
        linear-gradient(150deg, #090711, #14162b 52%, #211236) !important;
    border: 1px solid rgba(247,213,109,0.34) !important;
    box-shadow: 0 28px 80px rgba(0,0,0,0.30), inset 0 1px 0 rgba(255,255,255,0.14) !important;
}
.ps-wrapped-share-preview::before {
    background:
        linear-gradient(90deg, rgba(255,255,255,0.04) 1px, transparent 1px),
        linear-gradient(0deg, rgba(255,255,255,0.035) 1px, transparent 1px) !important;
    background-size: 28px 28px !important;
}
.ps-wrapped-share-top strong {
    text-shadow: none !important;
}
.ps-wrapped-share-grid {
    grid-template-columns: 1fr !important;
}
.ps-wrapped-share-grid div,
.ps-wrapped-share-profile {
    background: rgba(255,255,255,0.075) !important;
    border-color: rgba(255,255,255,0.14) !important;
}

@media (max-width: 760px) {
    .ps-wrapped-title {
        font-size: clamp(1.9rem, 10vw, 3.55rem) !important;
        line-height: 0.98 !important;
    }
    .ps-wrapped-big-number {
        font-size: clamp(2.8rem, 17vw, 5.4rem) !important;
    }
    .ps-wrapped-scene-revenue .ps-wrapped-story,
    .ps-wrapped-scene-profit .ps-wrapped-story,
    .ps-wrapped-scene-risk .ps-wrapped-story {
        margin-left: 0;
        width: 100%;
    }
    .ps-wrapped-layout-card,
    .ps-wrapped-layout-duo {
        grid-template-columns: 1fr;
        grid-template-areas:
            "kicker"
            "title"
            "big"
            "sub"
            "visual"
            "chips";
        justify-items: center;
        text-align: center;
        align-content: center;
    }
    .ps-wrapped-layout-card .ps-wrapped-scene-visual,
    .ps-wrapped-layout-duo .ps-wrapped-scene-visual {
        width: min(43vw, 10rem, 23dvh) !important;
        max-height: 23dvh !important;
    }
    .ps-wrapped-scene-sold .ps-wrapped-story {
        text-align: center;
        justify-items: center;
        align-content: center;
        padding-bottom: 0.3rem;
    }
    .ps-wrapped-scene-month .ps-wrapped-story {
        width: 100%;
        padding: 0.9rem;
        border-radius: 24px;
    }
    .ps-wrapped-share-preview {
        height: min(43dvh, 410px) !important;
        max-width: min(76vw, 310px) !important;
    }
}
</style>
"""
