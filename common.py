"""Shared constants and helpers for all Base dashboard pages."""
import pandas as pd
import requests
import streamlit as st
from datetime import timedelta

CHAIN_NAME = "Base"      # chain key as used by DefiLlama
CHAIN_ID = 8453
ACCENT = "#0000fe"       # main chart colour
ACCENT_DARK = "#00007a"
ACCENT_FILL = "rgba(0,0,254,0.12)"
MA_COLOR = "#f59e0b"     # contrast colour for moving-average lines
BOX_BG = "#E5F2FF"

BLUE_SPECTRUM = [
    "#00007a", "#0000b0", "#0000fe", "#3333ff", "#6666ff",
    "#8c8cff", "#b3b3ff", "#ccccff", "#e0e0ff", "#f0f0ff",
]

# Optional Blockscout PRO API key (free at dev.blockscout.com), set in .streamlit/secrets.toml:
#   BLOCKSCOUT_API_KEY = "proapi_xxx"
try:
    BLOCKSCOUT_KEY = st.secrets.get("BLOCKSCOUT_API_KEY", None)
except Exception:
    BLOCKSCOUT_KEY = None


# ------------------------------------------------------------
# Data access
# ------------------------------------------------------------
def bs_request(path: str, params: dict | None = None):
    """Blockscout request. Uses the PRO API if a key is set, else the public Base instance."""
    params = dict(params or {})
    if BLOCKSCOUT_KEY:
        url = f"https://api.blockscout.com/{CHAIN_ID}{path}"
        params["apikey"] = BLOCKSCOUT_KEY
    else:
        url = f"https://base.blockscout.com{path}"
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def safe_call(errors: list, fn, *args, default=None, label=""):
    """Run fn; on failure record the error and return `default` so the page stays alive."""
    try:
        return fn(*args)
    except Exception as e:
        errors.append(f"{label or fn.__name__}: {e}")
        return default


def empty_ts() -> pd.DataFrame:
    return pd.DataFrame(columns=["date", "value"])


# ------------------------------------------------------------
# UI helpers
# ------------------------------------------------------------
def show_chart(fig):
    try:
        st.plotly_chart(fig, width="stretch")
    except TypeError:  # older Streamlit versions
        st.plotly_chart(fig, use_container_width=True)


def show_table(df, **kwargs):
    try:
        st.dataframe(df, width="stretch", hide_index=True, **kwargs)
    except TypeError:
        st.dataframe(df, use_container_width=True, hide_index=True, **kwargs)


def page_header(title: str, description_html: str):
    st.markdown(
        f"""
<div style="display:flex; align-items:center; gap:15px;">
<div style="width:56px; height:56px; border-radius:50%; background:{ACCENT};"></div>
<h1 style="margin:0;">{title}</h1>
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
<div style="background-color:{BOX_BG}; border-left:6px solid {ACCENT};
padding:15px; border-radius:10px; margin-top:10px;
color:#1a1a1a; font-size:16px; line-height:1.6;">
{description_html}
</div>
""",
        unsafe_allow_html=True,
    )
    st.markdown("")


def sidebar_controls():
    st.sidebar.markdown("### Base Dashboard")
    if st.sidebar.button("🔄 Refresh data"):
        st.cache_data.clear()
        st.rerun()
    st.sidebar.caption("Data is cached: live data ~30-60s, charts ~1 hour.")


# ------------------------------------------------------------
# Formatting / math helpers
# ------------------------------------------------------------
def fmt_usd(x):
    if x is None or pd.isna(x):
        return "N/A"
    if abs(x) >= 1e9:
        return f"${x/1e9:,.2f}B"
    if abs(x) >= 1e6:
        return f"${x/1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"${x/1e3:,.2f}K"
    return f"${x:,.2f}"


def fmt_num(x, decimals=0):
    if x is None or pd.isna(x):
        return "N/A"
    if abs(x) >= 1e9:
        return f"{x/1e9:,.2f}B"
    if abs(x) >= 1e6:
        return f"{x/1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"{x/1e3:,.2f}K"
    return f"{x:,.{decimals}f}"


def fmt_pct(x):
    return "N/A" if x is None or pd.isna(x) else f"{x:+.2f}%"


def safe_float(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def pct_change(df: pd.DataFrame, days: int):
    """% change of df['value'] over the last `days` days."""
    if df is None or df.empty:
        return None
    latest_date = df["date"].max()
    latest = df.loc[df["date"] == latest_date, "value"].values[0]
    past = df[df["date"] <= latest_date - timedelta(days=days)]
    if past.empty:
        return None
    past_val = past.iloc[-1]["value"]
    if not past_val:
        return None
    return (latest - past_val) / past_val * 100
