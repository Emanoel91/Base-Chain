import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, MA_COLOR, BLUE_SPECTRUM,
    bs_request, safe_call, empty_ts, show_chart, show_table, page_header, sidebar_controls,
    fmt_usd, fmt_num, fmt_pct, safe_float, BLOCKSCOUT_KEY,
)

st.set_page_config(page_title="Base Chain - Transactions & Activity", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Transactions & Activity",
    "On-chain activity on <b>Base</b>: transactions, active and new addresses, success rate, "
    "fees, gas, blocks, and a live sample of the latest transactions. "
    "Use the controls below to change the time range and granularity. "
    "See the <b>Sources</b> section at the bottom of the page."
)

START = "2023-08-01"  # Base mainnet launch month
TODAY = datetime.now(timezone.utc).date()
TODAY_STR = TODAY.isoformat()

# Charts we want from Blockscout's stats service (skipped automatically if a chart is unavailable)
# agg = how to combine days into weeks/months; kind = chart style
METRICS = {
    "newTxns":          dict(title="Transactions",              agg="sum",  kind="bar",  ma=True),
    "txnsGrowth":       dict(title="Cumulative Transactions",   agg="last", kind="area", ma=False),
    "activeAccounts":   dict(title="Active Addresses (avg/day)", agg="mean", kind="bar",  ma=True),
    "newAccounts":      dict(title="New Addresses",             agg="sum",  kind="bar",  ma=True),
    "accountsGrowth":   dict(title="Cumulative Addresses",      agg="last", kind="area", ma=False),
    "txsPerActive":     dict(title="Transactions per Active Address", agg="mean", kind="line", ma=False),
    "txnsSuccessRate":  dict(title="Transaction Success Rate",  agg="mean", kind="line", ma=False),
    "averageTxnFee":    dict(title="Average Transaction Fee",   agg="mean", kind="line", ma=False),
    "txnsFee":          dict(title="Total Fees Paid",           agg="sum",  kind="bar",  ma=True),
    "averageGasPrice":  dict(title="Average Gas Price",         agg="mean", kind="line", ma=False),
    "newBlocks":        dict(title="New Blocks",                agg="sum",  kind="bar",  ma=False),
    "averageBlockSize": dict(title="Average Block Size",        agg="mean", kind="line", ma=False),
}
GROUPS = [
    ("Transactions", ["newTxns", "txnsGrowth"]),
    ("Addresses", ["activeAccounts", "newAccounts", "accountsGrowth", "txsPerActive"]),
    ("Success, Fees & Gas", ["txnsSuccessRate", "averageTxnFee", "txnsFee", "averageGasPrice"]),
    ("Blocks", ["newBlocks", "averageBlockSize"]),
]
DERIVED = {"txsPerActive"}


# ============================================================
# --- Data fetchers ---
# ============================================================
@st.cache_data(ttl=60, show_spinner=False)
def get_bs_stats() -> dict:
    return bs_request("/api/v2/stats")


@st.cache_data(ttl=3600, show_spinner=False)
def get_available_lines() -> dict:
    """Which chart ids does this Blockscout stats service expose?"""
    j = bs_request("/stats-service/api/v1/lines")
    found = {}

    def walk(o):
        if isinstance(o, dict):
            if isinstance(o.get("id"), str) and ("resolutions" in o or "units" in o):
                found[o["id"]] = {"title": o.get("title"), "units": o.get("units")}
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(j)
    return found


@st.cache_data(ttl=3600, show_spinner=False)
def get_line(name: str, start: str, end: str):
    """Daily series from the stats service -> (DataFrame[date, value], units, title)."""
    j = bs_request(f"/stats-service/api/v1/lines/{name}",
                   {"from": start, "to": end, "resolution": "DAY"})
    df = pd.DataFrame(j.get("chart", []))
    info = j.get("info", {}) or {}
    if df.empty or "date" not in df.columns:
        return empty_ts(), "", name
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "value": pd.to_numeric(df["value"], errors="coerce"),
    }).dropna()
    out = out[out["date"].dt.date < datetime.now(timezone.utc).date()]  # drop today's partial day
    units = info.get("units") or ""
    if name == "txnsSuccessRate" and not out.empty and out["value"].max() <= 1.0001:
        out["value"] = out["value"] * 100
        units = "%"
    return out.sort_values("date").reset_index(drop=True), units, info.get("title") or name


@st.cache_data(ttl=3600, show_spinner=False)
def get_legacy_tx_chart() -> pd.DataFrame:
    """Fallback: classic Blockscout daily transactions chart."""
    j = bs_request("/api/v2/stats/charts/transactions")
    df = pd.DataFrame(j.get("chart_data", []))
    if df.empty or "date" not in df.columns:
        return empty_ts()
    val_col = next((c for c in df.columns if c != "date"), None)
    out = pd.DataFrame({"date": pd.to_datetime(df["date"]),
                        "value": pd.to_numeric(df[val_col], errors="coerce")})
    out = out[out["date"].dt.date < datetime.now(timezone.utc).date()]
    return out.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=30, show_spinner=False)
def get_recent_txs(pages: int) -> pd.DataFrame:
    """Latest transactions (50 per page) from the Blockscout REST API."""
    rows, params = [], {}
    for _ in range(pages):
        j = bs_request("/api/v2/transactions", params)
        for t in j.get("items", []):
            to = t.get("to") or {}
            types = t.get("transaction_types") or []
            if "contract_creation" in types:
                ttype = "Contract creation"
            elif "token_creation" in types:
                ttype = "Token creation"
            elif "token_transfer" in types:
                ttype = "Token transfer"
            elif "contract_call" in types:
                ttype = "Contract call"
            elif "coin_transfer" in types:
                ttype = "ETH transfer"
            else:
                ttype = "Other"
            value_wei = safe_float(t.get("value"))
            fee_wei = safe_float((t.get("fee") or {}).get("value"))
            to_hash = to.get("hash")
            rows.append({
                "Hash": t.get("hash"),
                "Time (UTC)": pd.to_datetime(t.get("timestamp"), utc=True) if t.get("timestamp") else pd.NaT,
                "Type": ttype,
                "Method": t.get("method") or "unknown",
                "Status": "Success" if t.get("status") == "ok" else "Failed",
                "From": (t.get("from") or {}).get("hash"),
                "To": to.get("name") or (to_hash[:8] + "…" + to_hash[-6:] if to_hash else "Contract creation"),
                "Value (ETH)": value_wei / 1e18 if value_wei is not None else None,
                "Fee (ETH)": fee_wei / 1e18 if fee_wei is not None else None,
                "Gas Used": safe_float(t.get("gas_used")),
            })
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = nxt
    return pd.DataFrame(rows)


# ============================================================
# --- Load data ---
# ============================================================
with st.spinner("Loading Base activity data..."):
    stats = sc(get_bs_stats, default={}, label="Blockscout stats") or {}
    avail = sc(get_available_lines, default={}, label="Blockscout stats-service (chart list)")
    series = {}   # id -> (daily df, units, title)
    if avail:
        for sid in METRICS:
            if sid in DERIVED or sid not in avail:
                continue
            res = sc(get_line, sid, START, TODAY_STR, default=None, label=f"chart {sid}")
            if res and not res[0].empty:
                series[sid] = res
    else:
        legacy = sc(get_legacy_tx_chart, default=empty_ts(), label="Blockscout daily transactions (fallback)")
        if not legacy.empty:
            series["newTxns"] = (legacy, "transactions", "Transactions")

# Derived series: transactions per active address
if "newTxns" in series and "activeAccounts" in series:
    m = series["newTxns"][0].merge(series["activeAccounts"][0], on="date", suffixes=("_tx", "_act"))
    m = m[m["value_act"] > 0]
    if not m.empty:
        series["txsPerActive"] = (
            pd.DataFrame({"date": m["date"], "value": m["value_tx"] / m["value_act"]}),
            "txs / address", "Transactions per Active Address")

if not avail:
    st.warning(
        "Blockscout's stats-service is not reachable"
        + ("" if BLOCKSCOUT_KEY else " without an API key")
        + ", so only a reduced set of charts is available. Add a free key from dev.blockscout.com "
          "as `BLOCKSCOUT_API_KEY` in `.streamlit/secrets.toml` to enable all charts."
    )

eth_price = safe_float(stats.get("coin_price"))
total_txs = safe_float(stats.get("total_transactions"))
txs_today = safe_float(stats.get("transactions_today"))
utilization = safe_float(stats.get("network_utilization_percentage"))
gp = stats.get("gas_prices") or {}
gas_avg = safe_float(gp.get("average")) if isinstance(gp, dict) else None


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


def native(v, units):
    """Format a fee value that is expressed in the native coin."""
    if v is None:
        return "N/A", None
    if "ETH" in (units or "").upper():
        usd = f"≈ {fmt_usd(v * eth_price)}" if eth_price else None
        return f"{v:,.4f} ETH", usd
    return f"{v:,.4f} {units}".strip(), None


if "newTxns" in series:
    last_day = series["newTxns"][0].iloc[-1]["date"]
    st.markdown(f"##### Latest complete day: {last_day.strftime('%Y-%m-%d')} (UTC)")

st.markdown("**Transactions**")
k1, k2, k3, k4 = st.columns(4)
v, ch = last_vs_prev("newTxns")
k1.metric("Transactions (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
v7, ch7 = window_avg("newTxns", 7)
k2.metric("7D Avg / Day", fmt_num(v7), fmt_pct(ch7) if ch7 is not None else None)
v30, ch30 = window_avg("newTxns", 30)
k3.metric("30D Avg / Day", fmt_num(v30), fmt_pct(ch30) if ch30 is not None else None)
if "newTxns" in series:
    d = series["newTxns"][0]
    peak = d.loc[d["value"].idxmax()]
    k4.metric("Peak Daily Transactions", fmt_num(peak["value"]), peak["date"].strftime("%Y-%m-%d"), delta_color="off")
else:
    k4.metric("Peak Daily Transactions", "N/A")

k5, k6, k7, k8 = st.columns(4)
k5.metric("Transactions Today (UTC)", fmt_num(txs_today))
k6.metric("Total Transactions", fmt_num(total_txs))
v, _ = last_vs_prev("txnsSuccessRate")
k7.metric("Success Rate (last day)", f"{v:.2f}%" if v is not None else "N/A")
v, _ = last_vs_prev("txsPerActive")
k8.metric("Txs per Active Address", f"{v:,.2f}" if v is not None else "N/A")

st.markdown("**Addresses, Fees & Gas**")
a1, a2, a3, a4 = st.columns(4)
v, ch = last_vs_prev("activeAccounts")
a1.metric("Active Addresses (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
v, ch = last_vs_prev("newAccounts")
a2.metric("New Addresses (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
v, _ = last_vs_prev("accountsGrowth")
a3.metric("Total Addresses", fmt_num(v))
v, _ = last_vs_prev("averageTxnFee")
val, usd = native(v, series["averageTxnFee"][1] if "averageTxnFee" in series else "")
a4.metric("Avg Transaction Fee (last day)", val, usd, delta_color="off")

b1, b2, b3, b4 = st.columns(4)
v, _ = last_vs_prev("txnsFee")
val, usd = native(v, series["txnsFee"][1] if "txnsFee" in series else "")
b1.metric("Total Fees (last day)", val, usd, delta_color="off")
b2.metric("Avg Gas Price (now)", f"{gas_avg:.4f} gwei" if gas_avg is not None else "N/A")
b3.metric("Network Utilization (now)", f"{utilization:.2f}%" if utilization is not None else "N/A")
b4.metric("ETH Price", fmt_usd(eth_price))

st.markdown("---")

# ============================================================
# --- Controls ---
# ============================================================
ctl1, ctl2, ctl3 = st.columns([2, 3, 2])
with ctl1:
    gran = st.radio("Granularity", ["Daily", "Weekly", "Monthly"], horizontal=True)
with ctl2:
    range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}
    range_choice = st.radio("Range", list(range_map.keys()), horizontal=True, index=2)
with ctl3:
    show_ma = st.checkbox("Show moving average", value=True)
days = range_map[range_choice]
MA_WINDOW = {"Daily": 7, "Weekly": 4, "Monthly": 3}[gran]


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
    daily, units, _ = series[sid]
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
if not series:
    st.info("No time-series data is available right now. See the data warnings at the bottom.")

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
    if header == "Transactions" and "newTxns" in series:
        wd = in_range(series["newTxns"][0]).copy()
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
# --- Live sample of latest transactions ---
# ============================================================
st.subheader("Latest Transactions — Live Sample")
sample_n = st.select_slider("Sample size (latest transactions)", options=[50, 100, 150, 200], value=100)
tx_df = sc(get_recent_txs, sample_n // 50, default=pd.DataFrame(), label="Blockscout latest transactions")

if tx_df is not None and not tx_df.empty:
    span = (tx_df["Time (UTC)"].max() - tx_df["Time (UTC)"].min()).total_seconds()
    tps = len(tx_df) / span if span > 0 else None
    ok_rate = (tx_df["Status"] == "Success").mean() * 100
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Transactions in Sample", f"{len(tx_df)}")
    s2.metric("Sample Time Span", f"{span:,.0f}s")
    s3.metric("Approx. TPS (sample)", f"{tps:,.1f}" if tps else "N/A")
    s4.metric("Success Rate (sample)", f"{ok_rate:.1f}%")

    c_left, c_right = st.columns(2)
    with c_left:
        type_df = tx_df["Type"].value_counts().reset_index()
        type_df.columns = ["Type", "Count"]
        fig = px.pie(type_df, names="Type", values="Count", hole=0.5,
                     color_discrete_sequence=BLUE_SPECTRUM, title="Transactions by Type")
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
        show_chart(fig)
    with c_right:
        meth = tx_df["Method"].value_counts().head(10).sort_values().reset_index()
        meth.columns = ["Method", "Count"]
        fig = go.Figure(go.Bar(x=meth["Count"], y=meth["Method"], orientation="h",
                               marker_color=ACCENT, text=meth["Count"], textposition="outside"))
        fig.update_layout(title="Top 10 Methods Called", height=380,
                          margin=dict(l=10, r=40, t=50, b=10), xaxis_title="Transactions",
                          yaxis_title=None, plot_bgcolor="white")
        show_chart(fig)

    c_left, c_right = st.columns(2)
    with c_left:
        dest = tx_df["To"].value_counts().head(10).sort_values().reset_index()
        dest.columns = ["To", "Count"]
        fig = go.Figure(go.Bar(x=dest["Count"], y=dest["To"], orientation="h",
                               marker_color=ACCENT, text=dest["Count"], textposition="outside"))
        fig.update_layout(title="Top 10 Destination Addresses / Contracts", height=380,
                          margin=dict(l=10, r=40, t=50, b=10), xaxis_title="Transactions",
                          yaxis_title=None, plot_bgcolor="white")
        show_chart(fig)
    with c_right:
        fee = tx_df.dropna(subset=["Fee (ETH)"])
        if not fee.empty:
            fig = go.Figure(go.Histogram(x=fee["Fee (ETH)"], nbinsx=30, marker_color=ACCENT))
            fig.update_layout(title="Fee Distribution (ETH per transaction)", height=380,
                              margin=dict(l=10, r=10, t=50, b=10), xaxis_title="Fee (ETH)",
                              yaxis_title="Transactions", plot_bgcolor="white")
            show_chart(fig)

    disp = tx_df.head(25).copy()
    disp["Time (UTC)"] = disp["Time (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S")
    disp["Hash"] = disp["Hash"].apply(lambda h: f"{h[:10]}…{h[-6:]}" if isinstance(h, str) else h)
    disp["From"] = disp["From"].apply(lambda h: f"{h[:8]}…{h[-6:]}" if isinstance(h, str) else h)
    disp["Value (ETH)"] = disp["Value (ETH)"].apply(lambda x: f"{x:.6f}" if pd.notnull(x) else "N/A")
    disp["Fee (ETH)"] = disp["Fee (ETH)"].apply(lambda x: f"{x:.8f}" if pd.notnull(x) else "N/A")
    disp["Gas Used"] = disp["Gas Used"].apply(fmt_num)
    show_table(disp)
    st.caption("This is a small snapshot of the most recent transactions, not the whole chain — "
               "percentages here describe the sample only.")
else:
    st.info("Latest transactions are unavailable right now.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| Daily / weekly / monthly charts | Transactions, cumulative transactions, active & new addresses, success rate, fees, gas price, blocks | [Blockscout – Base](https://base.blockscout.com) · stats service `/stats-service/api/v1/lines/{chart}` (chart ids such as `newTxns`, `activeAccounts`, `newAccounts`, `txnsSuccessRate`, `txnsFee`) · [docs](https://docs.blockscout.com/devs/stats-dashboard) |
| Live KPIs | ETH price, total & today's transactions, gas price, utilization | [Blockscout – Base](https://base.blockscout.com) · `/api/v2/stats` |
| Live sample | Latest transactions, methods, destinations, fees | [Blockscout – Base](https://base.blockscout.com) · `/api/v2/transactions` |
| Derived metrics | Transactions per active address, weekday pattern, weekly/monthly aggregation | Calculated in this app from the daily series above |
"""
)
st.caption(
    "Notes: today's partial day is excluded from daily series; incomplete weeks/months are dropped when "
    "using Weekly/Monthly granularity. 'Active addresses' is averaged per day when aggregated. "
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
