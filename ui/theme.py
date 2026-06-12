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
    padding-top: 0.75rem !important;
}
div[data-testid="stButton"] button {
    min-height: 2.75rem !important;
    width: 100% !important;
}
div[data-testid="stNumberInput"] input,
div[data-testid="stTextInput"] input {
    min-height: 2.65rem !important;
    font-size: 0.95rem !important;
}
[data-testid="stMetricValue"] {
    font-size: 1.35rem !important;
}
</style>
"""
