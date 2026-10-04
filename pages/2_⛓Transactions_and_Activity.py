import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, MA_COLOR,
    safe_call, empty_ts, show_chart, page_header, sidebar_controls,
    fmt_num, fmt_pct,
)

# --- Sidebar Footer Slightly Left-Aligned ---
st.sidebar.markdown(
    """
    <style>
    .sidebar-footer {
        position: fixed;
        bottom: 20px;
        width: 250px;
        font-size: 13px;
        color: gray;
        margin-left: 5px; /* Move slightly left */
        text-align: left;  
    }
    .sidebar-footer img {
        width: 16px;
        height: 16px;
        vertical-align: middle;
        border-radius: 50%;
        margin-right: 5px;
    }
    .sidebar-footer a {
        color: gray;
        text-decoration: none;
    }
    </style>

    <div class="sidebar-footer">
        <div>
            <a href="https://x.com/base" target="_blank">
                <img src="https://pbs.twimg.com/profile_images/2060695832840556549/R0s33fMN_400x400.jpg" alt="Base Logo">
                Powered by Base
            </a>
        </div>
        <div style="margin-top: 5px;">
            <a href="https://x.com/0xeman_raz" target="_blank">
                <img src="https://pbs.twimg.com/profile_images/2060406047391559681/sA9zPNKM_400x400.jpg" alt="Eman Raz">
                Built by Eman Raz
            </a>
        </div>
    </div>
    """,
    unsafe_allow_html=True
)
# --- Page Config: Tab Title & Icon ---
st.set_page_config(
    page_title="Base Chain — Transaction & Addresses",
    page_icon="https://images.cryptorank.io/coins/150x150.base1752857325751.png",
    layout="wide"
)

# --- Title with Logo ---
st.markdown(
    """
    <div style="display: flex; align-items: center; gap: 15px;">
        <img src="https://images.cryptorank.io/coins/150x150.base1752857325751.png" alt="Base" style="width:60px; height:60px;">
        <h1 style="margin: 0;">Base Chain — Transaction & Addresses</h1>
    </div>
    """,
    unsafe_allow_html=True
)

# --- Builder Info ------------------------------------------------------------------------
st.markdown(
    """
    <div style="margin-top: 25px; font-size: 16px;">
        <div style="display: flex; align-items: center; gap: 10px;">
            <img src="https://pbs.twimg.com/profile_images/2060406047391559681/sA9zPNKM_400x400.jpg" alt="Eman Raz" style="width:25px; height:25px; border-radius: 50%;">
            <span>Built by: <a href="https://x.com/0xeman_raz" target="_blank">Eman Raz</a></span>
        </div>
    </div>

    <!-- Support / Tips Box -->
    <div style="
        background-color: #F5F5F5;
        border-left: 5px solid #888;
        padding: 12px;
        border-radius: 10px;
        margin-top: 10px;
        font-size: 15px;
        color: #333;
    ">
        🎁 <b>Support / Tips:</b><br>
        <code>0x621bd661e3d57da1c8237209824827f1027abf62</code>
    </div>
    """,
    unsafe_allow_html=True
)

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Transactions & Activity",
    "On-chain activity on <b>Base</b>, from the first available day to the latest complete day: "
    "transactions, active addresses and fees. "
    "All data comes from the <b>growthepie</b> public API. "
    "Use the filters below to change the time frame and range. "
    "See the <b>Sources</b> section at the bottom of the page."
)

GTP_API = "https://api.growthepie.com/v1"
CHAIN = "base"

# Metrics used (growthepie: /v1/metrics/chains/base/{metric}.json)
#   agg  = how daily rows are combined into weekly / monthly buckets
#   kind = chart style
CHARTS = {
    "txcount":      dict(title="Transactions",                    agg="sum",  kind="bar",  ma=True,  units="transactions"),
    "txnsGrowth":   dict(title="Cumulative Transactions",         agg="last", kind="area", ma=False, units="transactions"),  # derived
    "daa":          dict(title="Active Addresses",                agg="mean", kind="bar",  ma=True,  units="addresses",
                         title_agg="Active Addresses (daily avg)"),
    "txsPerActive": dict(title="Transactions per Active Address", agg="mean", kind="line", ma=False, units="txs / address"),  # derived
}
GROUPS = [
    ("Transactions Analysis", ["txcount", "txnsGrowth"]),
    ("Addresses Analysis", ["daa", "txsPerActive"]),
]


# ============================================================
# --- Data fetchers ---
# ============================================================
def _find_timeseries(o):
    """Fallback: locate any {'types': [...], 'data': [[...], ...]} block in the JSON."""
    if isinstance(o, dict):
        if isinstance(o.get("types"), list) and isinstance(o.get("data"), list):
            return o
        for v in o.values():
            r = _find_timeseries(v)
            if r is not None:
                return r
    elif isinstance(o, list):
        for v in o:
            r = _find_timeseries(v)
            if r is not None:
                return r
    return None


@st.cache_data(ttl=3600, show_spinner=False)
def get_metric_raw(metric: str) -> pd.DataFrame:
    """Full daily history of one growthepie metric for Base -> DataFrame[date, <value columns>]."""
    r = requests.get(
        f"{GTP_API}/metrics/chains/{CHAIN}/{metric}.json",
        timeout=30, headers={"User-Agent": "base-dashboard/1.0"},
    )
    r.raise_for_status()
    j = r.json()
    # Each file holds several resolutions under details.timeseries (daily, weekly, monthly, hourly...)
    tsd = (j.get("details") or {}).get("timeseries") if isinstance(j, dict) else None
    ts = tsd.get("daily") if isinstance(tsd, dict) else None
    if not (isinstance(ts, dict) and ts.get("data")):
        ts = _find_timeseries(j)
    if ts is None or not ts["data"]:
        return empty_ts()
    df = pd.DataFrame(ts["data"], columns=ts["types"])
    if "unix" not in df.columns:
        return empty_ts()
    unit = "ms" if df["unix"].astype("float64").abs().max() > 1e11 else "s"
    df["date"] = pd.to_datetime(df["unix"], unit=unit).dt.normalize()
    df = df.drop(columns=["unix"])
    for c in df.columns:
        if c != "date":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["date"].dt.date < datetime.now(timezone.utc).date()]  # drop today's partial day
    return df.sort_values("date").reset_index(drop=True)


def col_series(raw, candidates):
    """Pick the first existing column among `candidates` -> DataFrame[date, value] (or None)."""
    if raw is None or raw.empty:
        return None
    for c in candidates:
        if c in raw.columns:
            d = raw[["date", c]].rename(columns={c: "value"}).dropna()
            return d.reset_index(drop=True) if not d.empty else None
    return None


# ============================================================
# --- Filters (each one a separate dropdown) ---
# ============================================================
RANGES = {"7D": 7, "30D": 30, "90D": 90, "Q (current quarter)": "Q", "180D": 180, "1Y": 365, "All": None}

f1, f2, f3, _ = st.columns([1, 1, 1, 3])
with f1:
    gran = st.selectbox("Time Frame", ["Daily", "Weekly", "Monthly"], index=0)
with f2:
    range_choice = st.selectbox("Range", list(RANGES.keys()), index=len(RANGES) - 1)
with f3:
    show_ma = st.selectbox("Moving Average", ["On", "Off"], index=0) == "On"
MA_WINDOW = {"Daily": 7, "Weekly": 4, "Monthly": 3}[gran]

st.markdown("---")


# ============================================================
# --- Load data ---
# ============================================================
with st.spinner("Loading Base data from growthepie..."):
    tx_raw = sc(get_metric_raw, "txcount", default=None, label="growthepie txcount")
    daa_raw = sc(get_metric_raw, "daa", default=None, label="growthepie daa")
    fees_raw = sc(get_metric_raw, "fees", default=None, label="growthepie fees")

tx = col_series(tx_raw, ["value"])
daa = col_series(daa_raw, ["value"])
fees_usd = col_series(fees_raw, ["usd", "value_usd"])
fees_eth = col_series(fees_raw, ["eth", "value_eth"])

series = {}   # chart id -> (daily df[date, value], units)
if tx is not None:
    series["txcount"] = (tx, CHARTS["txcount"]["units"])
    cum = tx.copy()
    cum["value"] = cum["value"].cumsum()
    series["txnsGrowth"] = (cum, CHARTS["txnsGrowth"]["units"])
if daa is not None:
    series["daa"] = (daa, CHARTS["daa"]["units"])
if tx is not None and daa is not None:
    m = tx.merge(daa, on="date", suffixes=("_tx", "_act"))
    m = m[m["value_act"] > 0]
    if not m.empty:
        series["txsPerActive"] = (
            pd.DataFrame({"date": m["date"], "value": m["value_tx"] / m["value_act"]}),
            CHARTS["txsPerActive"]["units"])

if not series:
    st.warning("growthepie data could not be loaded right now. See the data warnings at the bottom.")


# ============================================================
# --- KPI helpers ---
# ============================================================
def pct(cur, prev):
    if cur is None or prev is None or pd.isna(cur) or pd.isna(prev) or prev == 0:
        return None
    return (cur - prev) / prev * 100


def dlt(ch):
    return fmt_pct(ch) if ch is not None else None


def window_sum(df, n):
    """Sum of the last n days vs the n days before."""
    if df is None or len(df) < 2 * n:
        return None, None
    v = df["value"]
    cur, prv = v.tail(n).sum(), v.iloc[-2 * n:-n].sum()
    return cur, pct(cur, prv)


def window_avg(df, n):
    """Average of the last n days vs the n days before."""
    if df is None or len(df) < 2 * n:
        return None, None
    v = df["value"]
    cur, prv = v.tail(n).mean(), v.iloc[-2 * n:-n].mean()
    return cur, pct(cur, prv)


def last_vs_prev(df):
    if df is None or len(df) < 2:
        return None, None
    last, prev = df.iloc[-1]["value"], df.iloc[-2]["value"]
    return last, pct(last, prev)


def ytd_sum(df):
    """Sum since Jan 1 of the latest year vs the same period of the previous year."""
    if df is None or df.empty:
        return None, None
    end = df["date"].max()
    start = pd.Timestamp(year=end.year, month=1, day=1)
    cur = df.loc[df["date"] >= start, "value"].sum()
    prev_start = pd.Timestamp(year=end.year - 1, month=1, day=1)
    prev_end = end - pd.DateOffset(years=1)
    if df["date"].min() > prev_start:        # no full previous-year comparison window
        return cur, None
    prv = df.loc[(df["date"] >= prev_start) & (df["date"] <= prev_end), "value"].sum()
    return cur, pct(cur, prv)


def usd_compact(v):
    if v is None or pd.isna(v):
        return "N/A"
    a = abs(v)
    if a >= 1e9:
        return f"${v / 1e9:,.2f}B"
    if a >= 1e6:
        return f"${v / 1e6:,.2f}M"
    if a >= 1e3:
        return f"${v / 1e3:,.1f}K"
    return f"${v:,.2f}"


def eth_fmt(v, decimals=2):
    if v is None or pd.isna(v):
        return "N/A"
    return f"{v:,.{decimals}f} ETH"


def usd_small(v):
    if v is None or pd.isna(v):
        return "N/A"
    return f"${v:.5f}" if abs(v) < 0.01 else f"${v:.4f}"


def fee_per_tx_last(fees_df):
    """Fees / transactions on the latest day present in both series."""
    if fees_df is None or tx is None:
        return None
    m = fees_df.merge(tx, on="date", suffixes=("_fee", "_tx"))
    m = m[m["value_tx"] > 0]
    if m.empty:
        return None
    r = m.iloc[-1]
    return r["value_fee"] / r["value_tx"]


# ============================================================
# --- KPIs ---
# ============================================================
if tx is not None:
    first_day, last_day = tx.iloc[0]["date"], tx.iloc[-1]["date"]
    st.markdown(f"##### Latest complete day: {last_day.strftime('%Y-%m-%d')} (UTC)")
    st.caption(f"Data available from {first_day.strftime('%Y-%m-%d')} to {last_day.strftime('%Y-%m-%d')} "
               f"({len(tx):,} days).")

# Row 1 — transaction totals
r1 = st.columns(4)
r1[0].metric("Total Transactions (since first data day)", fmt_num(tx["value"].sum()) if tx is not None else "N/A")
v, ch = window_sum(tx, 7)
r1[1].metric("Transactions (7d)", fmt_num(v), dlt(ch))
v, ch = window_sum(tx, 30)
r1[2].metric("Transactions (30d)", fmt_num(v), dlt(ch))
v, ch = ytd_sum(tx)
r1[3].metric("Transactions (ytd)", fmt_num(v), dlt(ch))

# Row 2 — daily transaction levels
r2 = st.columns(4)
v, ch = last_vs_prev(tx)
r2[0].metric("Transactions (last day)", fmt_num(v), dlt(ch))
v, ch = window_avg(tx, 7)
r2[1].metric("7D Avg / Day", fmt_num(v), dlt(ch))
v, ch = window_avg(tx, 30)
r2[2].metric("30D Avg / Day", fmt_num(v), dlt(ch))
if tx is not None:
    peak = tx.loc[tx["value"].idxmax()]
    r2[3].metric("Peak Daily Transactions", fmt_num(peak["value"]), peak["date"].strftime("%Y-%m-%d"), delta_color="off")
else:
    r2[3].metric("Peak Daily Transactions", "N/A")

# Row 3 — addresses
r3 = st.columns(4)
v, ch = last_vs_prev(daa)
r3[0].metric("Active Addresses (last day)", fmt_num(v), dlt(ch))
tpa = series["txsPerActive"][0] if "txsPerActive" in series else None
v, ch = last_vs_prev(tpa)
r3[1].metric("Transaction per Address (last day)", f"{v:,.2f}" if v is not None else "N/A", dlt(ch))
v, ch = window_avg(daa, 7)
r3[2].metric("Avg Daily Active Address (7d)", fmt_num(v), dlt(ch))
v, ch = window_avg(daa, 30)
r3[3].metric("Avg Daily Active Address (30d)", fmt_num(v), dlt(ch))

# Row 4 — fees
r4 = st.columns(4)
r4[0].metric("Total Fees Paid $ (since first data day)",
             usd_compact(fees_usd["value"].sum()) if fees_usd is not None else "N/A")
r4[1].metric("Total Fees Paid ETH (since first data day)",
             eth_fmt(fees_eth["value"].sum()) if fees_eth is not None else "N/A")
r4[2].metric("Avg Fee per Transaction $ (last day)", usd_small(fee_per_tx_last(fees_usd)))
r4[3].metric("Avg Fee per Transaction ETH (last day)", eth_fmt(fee_per_tx_last(fees_eth), 8))

st.markdown("---")


# ============================================================
# --- Chart helpers ---
# ============================================================
def aggregate(df: pd.DataFrame, agg: str) -> pd.DataFrame:
    """Combine daily rows into weekly / monthly buckets (incomplete last bucket is dropped)."""
    if gran == "Daily" or df.empty:
        return df
    s = df.set_index("date")["value"]
    if gran == "Weekly":
        rs = s.resample("W-MON", label="left", closed="left")
        span_end = lambda d: d + pd.Timedelta(days=6)
    else:
        rs = s.resample("MS")
        span_end = lambda d: d + pd.offsets.MonthEnd(0)
    out = getattr(rs, agg)().dropna().reset_index()
    out.columns = ["date", "value"]
    last_date = df["date"].max()
    out = out[out["date"].map(span_end) <= last_date]
    return out.reset_index(drop=True)


def in_range(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    sel = RANGES[range_choice]
    end = df["date"].max()
    if sel is None:
        return df
    if sel == "Q":                                   # current calendar quarter to date
        start = pd.Timestamp(year=end.year, month=3 * ((end.month - 1) // 3) + 1, day=1)
        return df[df["date"] >= start]
    return df[df["date"] > end - timedelta(days=sel)]


def style_layout(fig, title, units=None, legend=False):
    """Title top-left; legend (when shown) centred and pushed down, clear of the title."""
    fig.update_layout(
        title=dict(text=title, x=0.0, xanchor="left", y=0.97, yanchor="top"),
        height=380 if legend else 340,
        margin=dict(l=10, r=10, t=100 if legend else 60, b=10),
        yaxis_title=units, xaxis_title=None, hovermode="x unified", plot_bgcolor="white",
        showlegend=legend,
        legend=dict(orientation="h", x=0.5, xanchor="center", y=1.04, yanchor="bottom"),
    )
    return fig


def metric_chart(sid: str):
    cfg = CHARTS[sid]
    daily, units = series[sid]
    df = in_range(aggregate(daily, cfg["agg"]))
    base_title = cfg.get("title_agg", cfg["title"]) if gran != "Daily" else cfg["title"]
    title = base_title if gran == "Daily" else f"{base_title} — {gran}"
    fig = go.Figure()
    if cfg["kind"] == "bar":
        fig.add_trace(go.Bar(x=df["date"], y=df["value"], marker_color=ACCENT, name=cfg["title"]))
    elif cfg["kind"] == "area":
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"], mode="lines", fill="tozeroy",
                                 line=dict(color=ACCENT, width=2), fillcolor=ACCENT_FILL, name=cfg["title"]))
    else:
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"], mode="lines",
                                 line=dict(color=ACCENT, width=2), name=cfg["title"]))
    legend = bool(show_ma and cfg["ma"])
    if legend and len(df) > MA_WINDOW:
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"].rolling(MA_WINDOW).mean(), mode="lines",
                                 line=dict(color=MA_COLOR, width=2), name=f"{MA_WINDOW}-period MA"))
    return style_layout(fig, title, units, legend=legend)


WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def weekday_tx_chart():
    wd = in_range(series["txcount"][0]).copy()
    if wd.empty:
        return None
    wd["wd"] = wd["date"].dt.dayofweek
    g = wd.groupby("wd")["value"].mean().reindex(range(7))
    fig = go.Figure(go.Bar(x=WEEKDAYS, y=g.values, marker_color=ACCENT,
                           text=[fmt_num(x) if pd.notna(x) else "" for x in g.values], textposition="outside"))
    return style_layout(fig, "Average Transactions by Day of Week (Selected Range)", "Transactions")


def weekday_fee_chart():
    """Average fee per transaction (USD) by weekday = total fees / total transactions of that weekday."""
    if fees_usd is None or tx is None:
        return None
    m = in_range(fees_usd.merge(tx, on="date", suffixes=("_fee", "_tx")))
    if m.empty:
        return None
    m = m.assign(wd=m["date"].dt.dayofweek)
    g = m.groupby("wd")[["value_fee", "value_tx"]].sum().reindex(range(7))
    avg = g["value_fee"] / g["value_tx"].where(g["value_tx"] > 0)
    fig = go.Figure(go.Bar(x=WEEKDAYS, y=avg.values, marker_color=ACCENT,
                           text=[usd_small(x) if pd.notna(x) else "" for x in avg.values], textposition="outside"))
    return style_layout(fig, "Average Transaction Fees by Day of Week (Selected Range)", "USD per transaction")


# ============================================================
# --- Chart groups ---
# ============================================================
for header, ids in GROUPS:
    present = [i for i in ids if i in series]
    missing = [CHARTS[i]["title"] for i in ids if i not in series]
    if not present:
        continue
    st.subheader(header)
    for i in range(0, len(present), 2):
        cols = st.columns(2)
        for col, sid in zip(cols, present[i:i + 2]):
            with col:
                show_chart(metric_chart(sid))
    if header == "Transactions Analysis" and "txcount" in series:
        wc1, wc2 = st.columns(2)
        with wc1:
            fig = weekday_tx_chart()
            if fig is not None:
                show_chart(fig)
        with wc2:
            fig = weekday_fee_chart()
            if fig is not None:
                show_chart(fig)
    if missing:
        st.caption("Not available from this data source: " + ", ".join(missing))

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| KPIs and charts | Transactions, active addresses | [growthepie](https://www.growthepie.com/chains/base) · `https://api.growthepie.com/v1/metrics/chains/base/txcount.json`, `.../daa.json` |
| Fee KPIs and fee-by-weekday chart | Fees paid by users (USD and ETH) | growthepie · `https://api.growthepie.com/v1/metrics/chains/base/fees.json` |
| Derived metrics | Cumulative transactions, transactions per active address, average fee per transaction, weekday patterns, weekly/monthly aggregation, YTD and period-over-period changes | Calculated in this app from the daily growthepie series above |
"""
)
st.caption(
    "Notes: today's partial day is excluded; incomplete weeks/months are dropped for Weekly/Monthly time frames. "
    "'Active Addresses' is averaged per day when aggregated. 'Q' range = current calendar quarter to date. "
    "Period changes compare against the equal-length preceding period (YTD: same dates of the previous year). "
    "'Total ... since first data day' sums the daily values available in the API. "
    "Average fee per transaction = fees paid / transactions for the day."
)

if errors:
    with st.expander("⚠️ Data warnings"):
        for e in errors:
            st.write(f"- {e}")

st.markdown(
    f"""<div style="margin-top:25px; font-size:13px; color:gray;">
Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>""",
    unsafe_allow_html=True,
)
