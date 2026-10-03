import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, MA_COLOR, BLUE_SPECTRUM, CHAIN_NAME,
    show_chart, show_table, page_header, sidebar_controls, safe_call, empty_ts,
    fmt_usd, fmt_pct,
)
from llama import get_fees, get_chain_tvl

st.set_page_config(page_title="Base Chain - Fees & Revenue", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Fees & Revenue",
    "What users pay on <b>Base</b> and what protocols keep: daily, weekly and monthly fees and revenue, "
    "top protocols by fees, fees by category, and a protocol-level table. "
    "Data comes from DefiLlama's free public API. See the <b>Sources</b> section at the bottom."
)

# Legend centered on the title row (not directly under the title)
LEGEND_TOP_CENTER = dict(orientation="h", x=0.5, xanchor="center", y=1.08, yanchor="bottom")

# ============================================================
# --- Load data ---
# ============================================================
with st.spinner("Loading fees and revenue data..."):
    fees = sc(get_fees, CHAIN_NAME, "dailyFees", default={}, label="DefiLlama fees") or {}
    revenue = sc(get_fees, CHAIN_NAME, "dailyRevenue", default={}, label="DefiLlama revenue") or {}
    tvl_df = sc(get_chain_tvl, CHAIN_NAME, default=empty_ts(), label="DefiLlama chain TVL")

fee_series = fees.get("series", empty_ts()) if fees else empty_ts()
rev_series = revenue.get("series", empty_ts()) if revenue else empty_ts()
fprot = fees.get("protocols", pd.DataFrame()) if fees else pd.DataFrame()
rprot = revenue.get("protocols", pd.DataFrame()) if revenue else pd.DataFrame()

if not fees and not revenue:
    st.warning("Fees and revenue data is unavailable right now.")
    if errors:
        with st.expander("⚠️ Data warnings"):
            for e in errors:
                st.write(f"- {e}")
    st.stop()

# ============================================================
# --- KPIs ---
# ============================================================
current_tvl = tvl_df.iloc[-1]["value"] if tvl_df is not None and not tvl_df.empty else None
f24, f7, f30 = fees.get("total24h"), fees.get("total7d"), fees.get("total30d")
r24, r30 = revenue.get("total24h"), revenue.get("total30d")
fee_yield = (f30 * 365 / 30 / current_tvl * 100) if f30 and current_tvl else None
rev_ratio = (r30 / f30 * 100) if r30 is not None and f30 else None

top_name, top_share = "N/A", None
if not fprot.empty and fprot["total30d"].notna().any():
    tot = fprot["total30d"].sum()
    best = fprot.sort_values("total30d", ascending=False).iloc[0]
    top_name = best["Name"]
    top_share = best["total30d"] / tot * 100 if tot else None

st.markdown("**Chain totals**")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Fees (24h)", fmt_usd(f24), fmt_pct(fees.get("change_1d")) if fees.get("change_1d") is not None else None)
k2.metric("Fees (7d)", fmt_usd(f7))
k3.metric("Fees (30d)", fmt_usd(f30))
k4.metric("Revenue (24h)", fmt_usd(r24), fmt_pct(revenue.get("change_1d")) if revenue and revenue.get("change_1d") is not None else None)

k5, k6, k7, k8 = st.columns(4)
k5.metric("Revenue (30d)", fmt_usd(r30))
k6.metric("Revenue / Fees (30d)", f"{rev_ratio:.1f}%" if rev_ratio is not None else "N/A")
k7.metric("Annualized Fees / TVL", f"{fee_yield:.2f}%" if fee_yield is not None else "N/A")
k8.metric("Top Protocol by Fees (30d)", top_name, f"{top_share:.1f}% of fees" if top_share is not None else None,
          delta_color="off")
st.caption("'Annualized Fees / TVL' = last-30-day fees scaled to a year, divided by current TVL. "
           "'Revenue / Fees' is the share of fees kept by protocols or token holders (DefiLlama definitions).")

st.markdown("---")

# ============================================================
# --- Fees & revenue chart (daily / weekly / monthly) ---
# ============================================================
st.subheader("Fees & Revenue Over Time")

if fee_series.empty and rev_series.empty:
    st.info("Fees history is unavailable right now.")
else:
    c1, c2 = st.columns([2, 3])
    with c1:
        gran = st.radio("Timeframe", ["Daily", "Weekly", "Monthly"], horizontal=True, key="fee_gran")
    with c2:
        range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}
        default_idx = {"Daily": 2, "Weekly": 3, "Monthly": 4}[gran]
        fr = st.radio("Range", list(range_map.keys()), horizontal=True, index=default_idx,
                      key=f"fee_range_{gran}")
    dd = range_map[fr]

    def aggregate_sum(df: pd.DataFrame) -> pd.DataFrame:
        """Sum daily values into weekly (Mon–Sun) or monthly buckets; the incomplete last bucket is dropped."""
        if gran == "Daily" or df.empty:
            return df
        s = df.set_index("date")["value"]
        if gran == "Weekly":
            rs = s.resample("W-MON", label="left", closed="left")
            span_end = lambda d: d + pd.Timedelta(days=6)
        else:
            rs = s.resample("MS")
            span_end = lambda d: d + pd.offsets.MonthEnd(0)
        out = rs.sum().reset_index()
        out.columns = ["date", "value"]
        return out[out["date"].map(span_end) <= df["date"].max()].reset_index(drop=True)

    def in_range(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or dd is None:
            return df
        return df[df["date"] >= df["date"].max() - timedelta(days=dd)]

    f_ = in_range(aggregate_sum(fee_series))
    r_ = in_range(aggregate_sum(rev_series))

    fig = go.Figure()
    if not f_.empty:
        fig.add_trace(go.Bar(x=f_["date"], y=f_["value"], marker_color=ACCENT, name="Fees"))
    if not r_.empty:
        fig.add_trace(go.Scatter(x=r_["date"], y=r_["value"], mode="lines",
                                 line=dict(color=MA_COLOR, width=2), name="Revenue"))
    fig.update_layout(title=f"{gran} Chain Fees & Revenue", height=420,
                      margin=dict(l=10, r=10, t=80, b=10), yaxis_title="USD",
                      hovermode="x unified", plot_bgcolor="white", legend=LEGEND_TOP_CENTER)
    show_chart(fig)
    if gran != "Daily":
        st.caption("Weekly buckets run Monday–Sunday. The current, incomplete week or month is not shown so it "
                   "does not look like a drop.")

st.markdown("---")

# ============================================================
# --- Protocol breakdown ---
# ============================================================
st.subheader("Fees by Protocol & Category")
if not fprot.empty:
    fp = fprot[["Name", "category", "total24h", "total7d", "total30d", "change_1d"]].rename(columns={
        "category": "Category", "total24h": "Fees 24h", "total7d": "Fees 7d", "total30d": "Fees 30d",
        "change_1d": "Change 1d (%)"})
    if not rprot.empty:
        rp = rprot[["Name", "total24h", "total30d"]].rename(columns={"total24h": "Revenue 24h", "total30d": "Revenue 30d"})
        fp = fp.merge(rp, on="Name", how="left")
    fp = fp.sort_values("Fees 30d", ascending=False)

    top_f = fp.head(10).sort_values("Fees 30d")
    fl, fr_ = st.columns(2)
    with fl:
        fig = go.Figure(go.Bar(x=top_f["Fees 30d"], y=top_f["Name"], orientation="h", marker_color=ACCENT,
                               text=[fmt_usd(v) for v in top_f["Fees 30d"]], textposition="outside"))
        fig.update_layout(title="Top 10 Protocols by Fees (30d)", height=400,
                          margin=dict(l=10, r=70, t=50, b=10), xaxis_title="USD", plot_bgcolor="white")
        show_chart(fig)
    with fr_:
        cf = fp.groupby("Category", as_index=False)["Fees 30d"].sum().sort_values("Fees 30d", ascending=False)
        cf = cf[cf["Fees 30d"] > 0]
        if not cf.empty:
            fig = px.pie(cf, names="Category", values="Fees 30d", hole=0.5,
                         color_discrete_sequence=BLUE_SPECTRUM, title="Fees by Category (30d)")
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=400, margin=dict(l=10, r=10, t=50, b=10))
            show_chart(fig)

    C = st.column_config
    money_cols = {c: C.NumberColumn(format="$%.0f")
                  for c in ["Fees 24h", "Fees 7d", "Fees 30d", "Revenue 24h", "Revenue 30d"] if c in fp.columns}
    money_cols["Change 1d (%)"] = C.NumberColumn(format="%.2f%%")
    show_table(fp, column_config=money_cols)
    st.caption("Fees = total paid by users; revenue = the part kept by the protocol/token holders (DefiLlama "
               "definitions). Not every protocol reports revenue.")
else:
    st.info("Protocol-level fees data is unavailable right now.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| Chain totals, history, protocol breakdown | Chain and protocol fees / revenue (daily, 24h, 7d, 30d) | [DefiLlama Fees – Base](https://defillama.com/fees/chain/base) · `api.llama.fi/overview/fees/Base` (`dataType=dailyFees` and `dailyRevenue`) |
| Annualized Fees / TVL | Current chain TVL | [DefiLlama – Base](https://defillama.com/chain/Base) · `api.llama.fi/v2/historicalChainTvl/Base` |
| Derived metrics | Weekly/monthly aggregation, revenue/fees ratio, fee yield | Calculated in this app |
"""
)
st.caption("Third-party APIs may change limits or availability at any time.")

if errors:
    with st.expander("⚠️ Data warnings"):
        for e in errors:
            st.write(f"- {e}")

st.markdown(
    f"""<div style="margin-top:25px; font-size:13px; color:gray;">
Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</div>""",
    unsafe_allow_html=True,
)
