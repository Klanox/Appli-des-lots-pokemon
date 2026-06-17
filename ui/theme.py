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
    min-height: min(74vh, 720px);
    display: grid;
    place-items: center;
    padding: clamp(1.2rem, 4vw, 3rem);
    border-radius: 28px;
    color: #ffffff;
    background:
        radial-gradient(circle at 12% 8%, rgba(124, 58, 237, 0.85), transparent 30%),
        radial-gradient(circle at 86% 14%, rgba(14, 165, 233, 0.62), transparent 26%),
        linear-gradient(145deg, #050816 0%, #101033 45%, #1f0f46 100%);
    border: 1px solid rgba(255,255,255,0.12);
    box-shadow: 0 30px 80px rgba(15, 23, 42, 0.20);
    overflow: hidden;
    position: relative;
}
.ps-wrapped-entry::before {
    content: "";
    position: absolute;
    inset: 0;
    background:
        linear-gradient(rgba(255,255,255,0.055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px);
    background-size: 42px 42px;
    mask-image: radial-gradient(circle at center, rgba(0,0,0,0.75), transparent 78%);
}
.ps-wrapped-entry-card {
    position: relative;
    z-index: 1;
    width: min(720px, 100%);
    display: grid;
    justify-items: center;
    gap: 0.85rem;
    text-align: center;
    padding: clamp(1.4rem, 5vw, 3rem);
    border-radius: 30px;
    border: 1px solid rgba(255,255,255,0.20);
    background: linear-gradient(135deg, rgba(255,255,255,0.17), rgba(255,255,255,0.08));
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
    font-size: clamp(2.5rem, 8vw, 6rem);
    line-height: 0.9;
    font-weight: 950;
    letter-spacing: -0.04em;
    text-shadow: 0 18px 56px rgba(0,0,0,0.34);
}
.ps-wrapped-entry-card em {
    max-width: 520px;
    color: rgba(255,255,255,0.76);
    font-style: normal;
    font-size: clamp(0.98rem, 2.4vw, 1.25rem);
    line-height: 1.5;
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
.ps-wrapped-shell {
    min-height: 100dvh;
    width: 100vw;
    height: 100dvh;
    margin: 0;
    padding: clamp(0.85rem, 2.5vw, 1.4rem);
    border-radius: 0;
    color: #ffffff;
    background:
        radial-gradient(circle at 12% 8%, rgba(124, 58, 237, 0.95), transparent 28%),
        radial-gradient(circle at 88% 18%, rgba(14, 165, 233, 0.72), transparent 25%),
        radial-gradient(circle at 52% 98%, rgba(236, 72, 153, 0.42), transparent 32%),
        linear-gradient(145deg, #050816 0%, #101033 44%, #1f0f46 100%);
    border: 1px solid rgba(255,255,255,0.10);
    box-shadow: 0 34px 100px rgba(5, 8, 22, 0.46), inset 0 1px 0 rgba(255,255,255,0.08);
    position: fixed;
    inset: 0;
    z-index: 50;
    overflow: hidden;
    isolation: isolate;
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
        linear-gradient(rgba(255,255,255,0.055) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,0.045) 1px, transparent 1px);
    background-size: 42px 42px;
    mask-image: radial-gradient(circle at center, rgba(0,0,0,0.75), transparent 78%);
    pointer-events: none;
    z-index: 0;
    animation: psWrappedGrid 18s linear infinite;
}
.ps-wrapped-shell::after {
    content: "";
    position: absolute;
    width: 34rem;
    height: 34rem;
    right: -18rem;
    bottom: -19rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.14);
    filter: blur(10px);
    pointer-events: none;
    z-index: 0;
}
.ps-wrapped-orb {
    position: absolute;
    width: 9rem;
    height: 9rem;
    border-radius: 999px;
    background: rgba(255, 203, 5, 0.42);
    filter: blur(26px);
    left: -2.5rem;
    bottom: 18%;
    z-index: 0;
    animation: psWrappedOrb 8s ease-in-out infinite alternate;
}
.ps-wrapped-hero,
.ps-wrapped-controls,
.ps-wrapped-details {
    position: relative;
    z-index: 2;
}
.ps-wrapped-hero {
    min-height: calc(100dvh - 7.6rem);
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: clamp(0.9rem, 2vw, 1.25rem);
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
.ps-wrapped-count {
    color: rgba(255,255,255,0.68);
    font-weight: 800;
    font-size: 0.82rem;
    text-align: right;
}
.ps-wrapped-progress {
    grid-column: 1 / -1;
    height: 4px;
    border-radius: 999px;
    background: rgba(255,255,255,0.18);
    overflow: hidden;
}
.ps-wrapped-progress span {
    display: block;
    height: 100%;
    border-radius: inherit;
    background: linear-gradient(90deg, #facc15, #22c55e, #38bdf8, #f472b6);
    box-shadow: 0 0 24px rgba(56, 189, 248, 0.55);
    transition: width 0.35s ease;
}
.ps-wrapped-story {
    position: relative;
    z-index: 5;
    display: grid;
    align-content: center;
    justify-items: center;
    text-align: center;
    gap: clamp(0.85rem, 2vw, 1.2rem);
    padding: clamp(0.7rem, 2.5vw, 2rem);
    animation: psWrappedIn 0.38s cubic-bezier(.2,.8,.2,1) both;
}
@keyframes psWrappedIn {
    from { opacity: 0; transform: translateY(16px) scale(0.985); filter: blur(4px); }
    to { opacity: 1; transform: translateY(0) scale(1); filter: blur(0); }
}
.ps-wrapped-kicker {
    padding: 0.36rem 0.72rem;
    border-radius: 999px;
    background: rgba(255,255,255,0.12);
    border: 1px solid rgba(255,255,255,0.16);
    color: rgba(255,255,255,0.78);
    font-size: 0.74rem;
    font-weight: 900;
    letter-spacing: 0.12em;
    text-transform: uppercase;
}
.ps-wrapped-title {
    max-width: 860px;
    margin: 0 auto;
    font-size: clamp(2.25rem, 7.8vw, 5.6rem);
    line-height: 0.96;
    font-weight: 950;
    letter-spacing: 0;
    text-wrap: balance;
    color: #ffffff;
    text-shadow: 0 18px 60px rgba(0,0,0,0.35);
}
.ps-wrapped-big-number {
    font-size: clamp(3.2rem, 12vw, 8rem);
    line-height: 0.86;
    font-weight: 950;
    letter-spacing: -0.04em;
    color: #facc15;
    text-shadow:
        0 0 22px rgba(250, 204, 21, 0.34),
        0 20px 60px rgba(250, 204, 21, 0.18);
    animation: psWrappedPop 0.48s cubic-bezier(.2,.8,.2,1) both;
}
.ps-wrapped-big-number::first-letter {
    letter-spacing: -0.02em;
}
@keyframes psWrappedPop {
    from { opacity: 0; transform: scale(0.88); }
    to { opacity: 1; transform: scale(1); }
}
.ps-wrapped-subtitle {
    max-width: 700px;
    color: rgba(255,255,255,0.76);
    font-size: clamp(0.96rem, 2.2vw, 1.2rem);
    line-height: 1.55;
    font-weight: 650;
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
    grid-template-columns: minmax(7.5rem, 13rem) 1fr;
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
    font-size: clamp(1.35rem, 4vw, 2.8rem);
    line-height: 0.98;
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
.ps-wrapped-card-visual img {
    width: 100%;
    height: 100%;
    object-fit: contain;
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
    width: min(230px, 38vw);
    margin: 0.1rem auto 0.2rem;
    animation: psWrappedFloat 4.8s ease-in-out infinite;
    filter: drop-shadow(0 26px 46px rgba(0,0,0,0.34));
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
    font-size: clamp(2.2rem, 7vw, 4.6rem);
    line-height: 0.95;
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
    width: min(460px, 92vw);
    aspect-ratio: 9 / 14.5;
    display: grid;
    grid-template-rows: auto 1fr auto;
    gap: 1rem;
    padding: clamp(1rem, 4vw, 1.35rem);
    border-radius: 34px;
    border: 1px solid rgba(255,255,255,0.28);
    background:
        radial-gradient(circle at 18% 8%, rgba(250,204,21,0.26), transparent 34%),
        radial-gradient(circle at 88% 82%, rgba(56,189,248,0.26), transparent 34%),
        linear-gradient(145deg, rgba(5,8,22,0.96), rgba(36,16,79,0.95));
    box-shadow: 0 34px 88px rgba(0,0,0,0.36), inset 0 1px 0 rgba(255,255,255,0.20);
    text-align: left;
    overflow: hidden;
    position: relative;
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
    font-size: clamp(1.35rem, 4vw, 2.1rem);
    line-height: 1.02;
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
    background: rgba(255,255,255,0.12);
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
    font-size: clamp(1.2rem, 4vw, 1.75rem);
    line-height: 1.04;
    font-weight: 950;
    margin-top: 0.18rem;
}
.ps-wrapped-deal-card,
.ps-wrapped-stock-card {
    width: min(760px, 100%);
    display: grid;
    grid-template-columns: minmax(8rem, 13rem) 1fr;
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
    font-size: clamp(1.4rem, 4vw, 2.8rem);
    line-height: 0.98;
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
    font-size: clamp(3.1rem, 10vw, 7.6rem);
    line-height: 0.9;
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
    position: relative;
    z-index: 2;
    margin-top: 0.65rem;
    text-align: center;
    color: rgba(255,255,255,0.58);
    font-size: 0.78rem;
    font-weight: 750;
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
    z-index: 30 !important;
    display: grid !important;
    grid-template-columns: 1fr 1fr !important;
    gap: 0 !important;
    pointer-events: none !important;
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
    z-index: 80 !important;
    opacity: 1 !important;
    color: #ffffff !important;
    background: linear-gradient(135deg, #7c3aed, #0ea5e9) !important;
    border: 1px solid rgba(255,255,255,0.30) !important;
    box-shadow: 0 24px 70px rgba(14,165,233,0.34) !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev button,
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next button {
    position: fixed !important;
    top: 0 !important;
    width: 50vw !important;
    height: 100dvh !important;
    min-height: 100dvh !important;
    z-index: 85 !important;
    opacity: 0 !important;
    color: transparent !important;
    background: transparent !important;
    border: 0 !important;
    border-radius: 0 !important;
    box-shadow: none !important;
    padding: 0 !important;
    cursor: pointer !important;
    pointer-events: auto !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_prev button {
    left: 0 !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_tap_next button {
    right: 0 !important;
}
.stApp:has(.ps-wrapped-shell) .st-key-wrapped_download_card button {
    position: fixed !important;
    left: 50% !important;
    bottom: calc(max(1.2rem, env(safe-area-inset-bottom)) + 4.1rem) !important;
    width: min(420px, calc(100vw - 2rem)) !important;
    transform: translateX(-50%) !important;
    z-index: 92 !important;
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
    z-index: 90 !important;
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
        padding: 0.65rem;
        margin: 0;
    }
    .ps-wrapped-hero {
        min-height: calc(100dvh - 7.4rem);
    }
    .ps-wrapped-top {
        grid-template-columns: 1fr;
    }
    .ps-wrapped-count {
        text-align: left;
    }
    .ps-wrapped-story {
        padding: 0.4rem;
        gap: 0.72rem;
    }
    .ps-wrapped-title {
        font-size: clamp(2.05rem, 12vw, 4.2rem);
    }
    .ps-wrapped-big-number {
        font-size: clamp(3rem, 19vw, 5.8rem);
    }
    .ps-wrapped-subtitle {
        font-size: 0.95rem;
        line-height: 1.42;
    }
    .ps-wrapped-chip-row {
        gap: 0.45rem;
    }
    .ps-wrapped-chip {
        min-width: calc(50% - 0.45rem);
        padding: 0.62rem 0.72rem;
    }
    .ps-wrapped-scene-visual {
        width: min(185px, 44vw);
    }
    .ps-wrapped-profile-card {
        border-radius: 22px;
        padding: 1rem;
    }
    .ps-wrapped-profile-card strong {
        font-size: clamp(1.8rem, 11vw, 3.3rem);
    }
    .ps-wrapped-share-preview {
        width: min(360px, 88vw);
        max-height: 55dvh;
        gap: 0.55rem;
        padding: 0.9rem;
        border-radius: 26px;
    }
    .ps-wrapped-share-grid {
        gap: 0.42rem;
    }
    .ps-wrapped-share-grid div,
    .ps-wrapped-share-profile {
        padding: 0.58rem 0.68rem;
        border-radius: 16px;
    }
    .ps-wrapped-deal-card,
    .ps-wrapped-stock-card {
        grid-template-columns: 5.8rem 1fr;
        gap: 0.62rem;
        border-radius: 21px;
        padding: 0.72rem;
    }
    .ps-wrapped-deal-card .ps-wrapped-scene-visual,
    .ps-wrapped-stock-card .ps-wrapped-scene-visual {
        width: 100%;
    }
    .ps-wrapped-deal-copy strong,
    .ps-wrapped-stock-card strong {
        font-size: clamp(1rem, 6vw, 1.8rem);
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
        font-size: 0.88rem;
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
        grid-template-columns: 6.4rem 1fr;
        gap: 0.75rem;
        padding: 0.75rem;
        border-radius: 20px;
    }
    .ps-wrapped-final-panel {
        border-radius: 22px;
        padding: 1rem;
    }
    .ps-wrapped-feature strong {
        font-size: clamp(1.15rem, 7vw, 2rem);
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
        font-size: 0.72rem;
    }
    .stApp:has(.ps-wrapped-shell) .main .stButton > button {
        min-height: 2.8rem !important;
        font-size: 0.86rem !important;
    }
}
</style>
"""
