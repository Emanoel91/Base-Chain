import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, MA_COLOR,
    safe_call, empty_ts, show_chart, page_header, sidebar_controls,
    fmt_usd, fmt_num, fmt_pct,
)

st.set_page_config(page_title="Base Chain - Transactions & Activity", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Transactions & Activity",
    "On-chain activity on <b>Base</b>, from mainnet launch to the latest complete day: transactions, "
    "active addresses, fees, throughput, TVL and stablecoin supply. "
    "All data comes from the <b>growthepie</b> public API. "
    "Use the controls below to change the time range and granularity. "
    "See the <b>Sources</b> section at the bottom of the page."
)

GTP_API = "https://api.growthepie.com/v1"
CHAIN = "base"

# ------------------------------------------------------------
# Metrics served by growthepie: /v1/metrics/chains/base/{metric}.json
#   agg   = how to combine days into weeks/months
#   kind  = chart style
#   money = metric may be offered in USD or ETH (value_usd / value_eth)
#   units = fallback unit when the file has a single "value" column
# ------------------------------------------------------------
METRICS = {
    "txcount":      dict(title="Transactions",                    agg="sum",  kind="bar",  ma=True,  units="transactions"),
    "txnsGrowth":   dict(title="Cumulative Transactions",         agg="last", kind="area", ma=False, units="transactions"),  # derived
    "daa":          dict(title="Active Addresses (avg/day)",      agg="mean", kind="bar",  ma=True,  units="addresses"),
    "txsPerActive": dict(title="Transactions per Active Address", agg="mean", kind="line", ma=False, units="txs / address"),  # derived
    "fees":         dict(title="Fees Paid by Users",              agg="sum",  kind="bar",  ma=True,  units="USD", money=True),
    "app_revenue":  dict(title="Onchain App Revenue",             agg="sum",  kind="bar",  ma=True,  units="USD", money=True),
    "profit":       dict(title="Chain Profit",                    agg="sum",  kind="bar",  ma=True,  units="USD", money=True),
    "throughput":   dict(title="Throughput (Mgas/s)",             agg="mean", kind="line", ma=False, units="Mgas/s"),
    "tvl":          dict(title="Total Value Locked",              agg="last", kind="area", ma=False, units="USD", money=True),
    "stables_mcap": dict(title="Stablecoin Supply",               agg="last", kind="area", ma=False, units="USD", money=True),
}
GROUPS = [
    ("Transactions", ["txcount", "txnsGrowth"]),
    ("Addresses", ["daa", "txsPerActive"]),
    ("Fees & Economics", ["fees", "app_revenue", "profit"]),
    ("Throughput & Value", ["throughput", "tvl", "stables_mcap"]),
]
DERIVED = {"txnsGrowth", "txsPerActive"}
UNIT_BY_COL = {"value_usd": "USD", "value_eth": "ETH"}


# ============================================================
# --- Data fetchers ---
# ============================================================
def _find_timeseries(o):
    """Locate the {'types': [...], 'data': [[...], ...]} block anywhere in the JSON."""
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
    ts = _find_timeseries(r.json())
    if ts is None or not ts["data"]:
        return empty_ts()
    df = pd.DataFrame(ts["data"], columns=ts["types"])
    tcol = "unix" if "unix" in df.columns else ("date" if "date" in df.columns else None)
    if tcol is None:
        return empty_ts()
    if tcol == "unix":
        unit = "ms" if df[tcol].astype("float64").abs().max() > 1e11 else "s"
        df["date"] = pd.to_datetime(df[tcol], unit=unit).dt.normalize()
        df = df.drop(columns=["unix"])
    else:
        df["date"] = pd.to_datetime(df["date"]).dt.normalize()
    for c in df.columns:
        if c != "date":
            df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df[df["date"].dt.date < datetime.now(timezone.utc).date()]  # drop today's partial day
    return df.sort_values("date").reset_index(drop=True)


# ============================================================
# --- Controls ---
# ============================================================
ctl1, ctl2, ctl3, ctl4 = st.columns([2, 3, 2, 2])
with ctl1:
    gran = st.radio("Granularity", ["Daily", "Weekly", "Monthly"], horizontal=True)
with ctl2:
    range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}
    range_choice = st.radio("Range", list(range_map.keys()), horizontal=True, index=4)
with ctl3:
    fee_unit = st.radio("Money unit", ["USD", "ETH"], horizontal=True)
with ctl4:
    show_ma = st.checkbox("Show moving average", value=True)
days = range_map[range_choice]
MA_WINDOW = {"Daily": 7, "Weekly": 4, "Monthly": 3}[gran]

st.markdown("---")


# ============================================================
# --- Load data ---
# ============================================================
def pick_col(raw: pd.DataFrame, cfg: dict):
    cols = [c for c in raw.columns if c != "date"]
    if cfg.get("money"):
        order = ("value_usd", "value_eth") if fee_unit == "USD" else ("value_eth", "value_usd")
        for c in order:
            if c in cols:
                return c, UNIT_BY_COL[c]
    if "value" in cols:
        return "value", cfg.get("units", "")
    if cols:
        return cols[0], UNIT_BY_COL.get(cols[0], cfg.get("units", ""))
    return None, ""


series = {}   # id -> (daily df[date, value], units)
with st.spinner("Loading Base data from growthepie..."):
    for sid, cfg in METRICS.items():
        if sid in DERIVED:
            continue
        raw = sc(get_metric_raw, sid, default=None, label=f"growthepie {sid}")
        if raw is None or raw.empty:
            continue
        col, units = pick_col(raw, cfg)
        if col is None:
            continue
        d = raw[["date", col]].rename(columns={col: "value"}).dropna()
        if not d.empty:
            series[sid] = (d.reset_index(drop=True), units)

# Derived series
if "txcount" in series:
    t = series["txcount"][0].copy()
    t["value"] = t["value"].cumsum()
    series["txnsGrowth"] = (t, "transactions")
if "txcount" in series and "daa" in series:
    m = series["txcount"][0].merge(series["daa"][0], on="date", suffixes=("_tx", "_act"))
    m = m[m["value_act"] > 0]
    if not m.empty:
        series["txsPerActive"] = (
            pd.DataFrame({"date": m["date"], "value": m["value_tx"] / m["value_act"]}), "txs / address")

if not series:
    st.warning("growthepie data could not be loaded right now. See the data warnings at the bottom.")


# ============================================================
# --- KPIs ---
# ============================================================
def last_vs_prev(sid):
    if sid not in series or len(series[sid][0]) < 2:
        return None, None
    df = series[sid][0]
    last, prev = df.iloc[-1]["value"], df.iloc[-2]["value"]
    return last, ((last - prev) / prev * 100 if prev else None)


def window_avg(sid, n):
    if sid not in series or len(series[sid][0]) < 2 * n:
        return None, None
    v = series[sid][0]["value"]
    cur, prv = v.tail(n).mean(), v.iloc[-2 * n:-n].mean()
    return cur, ((cur - prv) / prv * 100 if prv else None)


def money(v, sid):
    """Format a money value according to the unit of its series."""
    if v is None or pd.isna(v):
        return "N/A"
    units = series[sid][1] if sid in series else "USD"
    return fmt_usd(v) if units == "USD" else f"{v:,.2f} {units}"


if "txcount" in series:
    first_day = series["txcount"][0].iloc[0]["date"]
    last_day = series["txcount"][0].iloc[-1]["date"]
    st.markdown(f"##### Latest complete day: {last_day.strftime('%Y-%m-%d')} (UTC)")
    st.caption(f"Data available from {first_day.strftime('%Y-%m-%d')} to {last_day.strftime('%Y-%m-%d')} "
               f"({len(series['txcount'][0]):,} days).")

st.markdown("**Transactions**")
k1, k2, k3, k4 = st.columns(4)
v, ch = last_vs_prev("txcount")
k1.metric("Transactions (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
v7, ch7 = window_avg("txcount", 7)
k2.metric("7D Avg / Day", fmt_num(v7), fmt_pct(ch7) if ch7 is not None else None)
v30, ch30 = window_avg("txcount", 30)
k3.metric("30D Avg / Day", fmt_num(v30), fmt_pct(ch30) if ch30 is not None else None)
if "txcount" in series:
    d = series["txcount"][0]
    peak = d.loc[d["value"].idxmax()]
    k4.metric("Peak Daily Transactions", fmt_num(peak["value"]), peak["date"].strftime("%Y-%m-%d"), delta_color="off")
else:
    k4.metric("Peak Daily Transactions", "N/A")

st.markdown("**Addresses & Throughput**")
a1, a2, a3, a4 = st.columns(4)
v, _ = last_vs_prev("txnsGrowth")
a1.metric("Total Transactions (since first data day)", fmt_num(v))
v, ch = last_vs_prev("daa")
a2.metric("Active Addresses (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
v, _ = last_vs_prev("txsPerActive")
a3.metric("Txs per Active Address", f"{v:,.2f}" if v is not None else "N/A")
v, _ = last_vs_prev("throughput")
a4.metric("Throughput (last day)", f"{v:,.2f} Mgas/s" if v is not None else "N/A")

st.markdown("**Fees & Value**")
b1, b2, b3, b4 = st.columns(4)
v, ch = last_vs_prev("fees")
b1.metric("Fees Paid (last day)", money(v, "fees"), fmt_pct(ch) if ch is not None else None)
v30f = series["fees"][0]["value"].tail(30).sum() if "fees" in series else None
b2.metric("Fees Paid (last 30D)", money(v30f, "fees"))
v, _ = last_vs_prev("tvl")
b3.metric("TVL (latest)", money(v, "tvl"))
v, _ = last_vs_prev("stables_mcap")
b4.metric("Stablecoin Supply (latest)", money(v, "stables_mcap"))

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
    if df.empty or days is None:
        return df
    return df[df["date"] >= df["date"].max() - timedelta(days=days)]


def metric_chart(sid: str):
    cfg = METRICS[sid]
    daily, units = series[sid]
    df = in_range(aggregate(daily, cfg["agg"]))
    title = cfg["title"] if gran == "Daily" else f"{cfg['title']} — {gran}"
    fig = go.Figure()
    if cfg["kind"] == "bar":
        fig.add_trace(go.Bar(x=df["date"], y=df["value"], marker_color=ACCENT, name=cfg["title"]))
    elif cfg["kind"] == "area":
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"], mode="lines", fill="tozeroy",
                                 line=dict(color=ACCENT, width=2), fillcolor=ACCENT_FILL, name=cfg["title"]))
    else:
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"], mode="lines",
                                 line=dict(color=ACCENT, width=2), name=cfg["title"]))
    if show_ma and cfg["ma"] and len(df) > MA_WINDOW:
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"].rolling(MA_WINDOW).mean(), mode="lines",
                                 line=dict(color=MA_COLOR, width=2), name=f"{MA_WINDOW}-period MA"))
    fig.update_layout(title=title, height=360, margin=dict(l=10, r=10, t=50, b=10),
                      yaxis_title=units or None, xaxis_title=None, hovermode="x unified",
                      plot_bgcolor="white", showlegend=bool(show_ma and cfg["ma"]),
                      legend=dict(orientation="h", y=1.12, x=0))
    return fig


# ============================================================
# --- Chart groups ---
# ============================================================
for header, ids in GROUPS:
    present = [i for i in ids if i in series]
    missing = [METRICS[i]["title"] for i in ids if i not in series]
    if not present:
        continue
    st.subheader(header)
    for i in range(0, len(present), 2):
        cols = st.columns(2)
        for col, sid in zip(cols, present[i:i + 2]):
            with col:
                show_chart(metric_chart(sid))
    # Weekday pattern sits with the transactions group
    if header == "Transactions" and "txcount" in series:
        wd = in_range(series["txcount"][0]).copy()
        if not wd.empty:
            wd["wd"] = wd["date"].dt.dayofweek
            order = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            g = wd.groupby("wd")["value"].mean().reindex(range(7))
            fig = go.Figure(go.Bar(x=order, y=g.values, marker_color=ACCENT,
                                   text=[fmt_num(x) for x in g.values], textposition="outside"))
            fig.update_layout(title="Average Transactions by Day of Week (selected range)", height=340,
                              margin=dict(l=10, r=10, t=50, b=10), yaxis_title="Transactions",
                              plot_bgcolor="white")
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
| Daily / weekly / monthly charts | Transactions, active addresses, fees, app revenue, profit, throughput, TVL, stablecoin supply | [growthepie](https://www.growthepie.com/chains/base) · API `https://api.growthepie.com/v1/metrics/chains/base/{metric}.json` (`txcount`, `daa`, `fees`, `app_revenue`, `profit`, `throughput`, `tvl`, `stables_mcap`) |
| Derived metrics | Cumulative transactions, transactions per active address, weekday pattern, weekly/monthly aggregation | Calculated in this app from the daily growthepie series above |
"""
)
st.caption(
    "Notes: today's partial day is excluded from daily series; incomplete weeks/months are dropped when "
    "using Weekly/Monthly granularity. 'Active addresses' is averaged per day when aggregated. "
    "'Cumulative Transactions' is the running sum of daily counts from the first day available in the data. "
    "Third-party APIs may change limits or availability at any time."
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
