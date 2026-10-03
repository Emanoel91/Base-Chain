import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, BLUE_SPECTRUM, CHAIN_NAME,
    show_chart, show_table, page_header, sidebar_controls, safe_call, empty_ts,
    fmt_usd, fmt_pct, pct_change,
)
from llama import get_json, get_chain_tvl, get_protocols, get_protocol_detail

st.set_page_config(page_title="Base Chain - Protocol Analyzer", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Protocol Analyzer",
    "Pick any protocol deployed on <b>Base</b> and see its Base-specific TVL history, other TVL types and "
    "token composition. An optional yield-pool explorer is included at the bottom. "
    "Data comes from DefiLlama. See the <b>Sources</b> section at the bottom."
)

LEGEND_TOP_CENTER = dict(orientation="h", x=0.5, xanchor="center", y=1.08, yanchor="bottom")

try:
    LLAMA_KEY = st.secrets.get("DEFILLAMA_API_KEY", None)
except Exception:
    LLAMA_KEY = None


@st.cache_data(ttl=1800, show_spinner=False)
def get_yield_pools(chain: str, key: str | None) -> pd.DataFrame:
    url = f"https://pro-api.llama.fi/{key}/yields/pools" if key else "https://yields.llama.fi/pools"
    data = get_json(url, timeout=120).get("data", [])
    return pd.DataFrame([d for d in data if d.get("chain") == chain])


# ============================================================
# --- Load data ---
# ============================================================
with st.spinner("Loading protocol list..."):
    protocols_df = sc(get_protocols, CHAIN_NAME, default=pd.DataFrame(), label="DefiLlama protocols")
    tvl_df = sc(get_chain_tvl, CHAIN_NAME, default=empty_ts(), label="DefiLlama chain TVL")

current_tvl = tvl_df.iloc[-1]["value"] if tvl_df is not None and not tvl_df.empty else None
range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}

# ============================================================
# --- Protocol analyzer ---
# ============================================================
st.subheader("Protocol Analyzer (Base-specific history)")
if protocols_df is not None and not protocols_df.empty:
    cf1, cf2 = st.columns([2, 3])
    with cf1:
        cats = sorted(protocols_df["Category"].unique().tolist())
        cat_pick = st.multiselect("Filter by category (empty = all)", cats, key="an_cat")
    plist = protocols_df if not cat_pick else protocols_df[protocols_df["Category"].isin(cat_pick)]
    plist = plist.sort_values("TVL", ascending=False)

    if plist.empty:
        st.info("No protocols in the selected categories.")
    else:
        label_map = {f"{r['Protocol']} — {fmt_usd(r['TVL'])}": r["Slug"] for _, r in plist.iterrows()}
        with cf2:
            pick = st.selectbox("Choose a protocol", list(label_map.keys()))
        slug = label_map[pick]
        det = sc(get_protocol_detail, slug, CHAIN_NAME, default=None, label=f"DefiLlama protocol {slug}")
        if det:
            st.markdown(f"**{det['name']}** · {det.get('category') or 'N/A'}"
                        + (f" · token: {det['symbol']}" if det.get("symbol") and det["symbol"] != "-" else "")
                        + (f" · listed {det['listed']}" if det.get("listed") else ""))
            if det.get("description"):
                st.caption(det["description"])
            links = []
            if det.get("url"):
                links.append(f"[Website]({det['url']})")
            if det.get("twitter"):
                links.append(f"[X / Twitter](https://x.com/{det['twitter']})")
            links.append(f"[DefiLlama page](https://defillama.com/protocol/{slug})")
            st.markdown(" · ".join(links))

            ptvl = det["tvl"]
            pd_ = None
            if not ptvl.empty:
                q1, q2, q3, q4 = st.columns(4)
                q1.metric("TVL on Base", fmt_usd(ptvl.iloc[-1]["value"]), fmt_pct(pct_change(ptvl, 1)))
                q2.metric("Change (7d)", fmt_pct(pct_change(ptvl, 7)))
                q3.metric("Change (30d)", fmt_pct(pct_change(ptvl, 30)))
                share = ptvl.iloc[-1]["value"] / current_tvl * 100 if current_tvl else None
                q4.metric("Share of Base TVL", f"{share:.2f}%" if share is not None else "N/A")

                pr = st.radio("Range", list(range_map.keys()), horizontal=True, index=4, key="proto_range")
                pd_ = range_map[pr]
                pp = ptvl if pd_ is None else ptvl[ptvl["date"] >= ptvl["date"].max() - timedelta(days=pd_)]
                fig = go.Figure(go.Scatter(x=pp["date"], y=pp["value"], mode="lines", fill="tozeroy",
                                           line=dict(color=ACCENT, width=2), fillcolor=ACCENT_FILL))
                fig.update_layout(title=f"{det['name']} — TVL on Base", height=380,
                                  margin=dict(l=10, r=10, t=50, b=10), yaxis_title="TVL (USD)",
                                  hovermode="x unified", plot_bgcolor="white")
                show_chart(fig)
            else:
                st.info("No Base-specific TVL history returned for this protocol.")

            if det["flavors"]:
                fl = pd.DataFrame([{"Type": k, "TVL": v} for k, v in det["flavors"].items()])
                st.markdown("**Other TVL types on Base** (not part of headline TVL)")
                show_table(fl, column_config={"TVL": st.column_config.NumberColumn(format="$%.0f")})

            tok = det["tokens"]
            if not tok.empty:
                latest = tok.iloc[-1].sort_values(ascending=False)
                latest = latest[latest > 0]
                top_t = latest.head(8)
                rest = latest.iloc[8:].sum()
                pie = pd.DataFrame({"Token": list(top_t.index) + (["Others"] if rest > 0 else []),
                                    "USD": list(top_t.values) + ([rest] if rest > 0 else [])})
                tl, tr = st.columns(2)
                with tl:
                    fig = px.pie(pie, names="Token", values="USD", hole=0.5,
                                 color_discrete_sequence=BLUE_SPECTRUM, title="Token Composition (latest)")
                    fig.update_traces(textposition="inside", textinfo="percent+label")
                    fig.update_layout(height=400, margin=dict(l=10, r=10, t=50, b=10))
                    show_chart(fig)
                with tr:
                    keep = list(tok.sum().sort_values(ascending=False).head(6).index)
                    tp = tok[keep] if pd_ is None else tok[tok.index >= tok.index.max() - timedelta(days=pd_)][keep]
                    fig = go.Figure()
                    for i, col in enumerate(tp.columns):
                        fig.add_trace(go.Scatter(x=tp.index, y=tp[col], mode="lines", stackgroup="one", name=col,
                                                 line=dict(width=0.5, color=BLUE_SPECTRUM[i % len(BLUE_SPECTRUM)])))
                    fig.update_layout(title="Top Tokens Over Time (USD, stacked)", height=400,
                                      margin=dict(l=10, r=10, t=80, b=10), hovermode="x unified",
                                      plot_bgcolor="white", legend=LEGEND_TOP_CENTER)
                    show_chart(fig)
else:
    st.info("Protocol list is unavailable right now.")

st.markdown("---")

# ============================================================
# --- Yields (optional) ---
# ============================================================
st.subheader("Yield Pools (optional)")
st.caption("The yields dataset is large, and DefiLlama lists its yield endpoints as Pro in current documentation. "
           "Without a key the free endpoint may fail; with `DEFILLAMA_API_KEY` in `.streamlit/secrets.toml` "
           "the Pro endpoint is used.")
if st.checkbox("Load yield pools for Base", value=False, key="load_yields"):
    ydf = sc(get_yield_pools, CHAIN_NAME, LLAMA_KEY, default=pd.DataFrame(), label="DefiLlama yields")
    if ydf is not None and not ydf.empty:
        y1, y2, y3, y4 = st.columns(4)
        with y1:
            y_min_tvl = st.number_input("Min pool TVL (USD)", min_value=0, value=100_000, step=50_000)
        with y2:
            y_max_apy = st.number_input("Max APY (%) — hides outliers", min_value=1, value=500, step=50)
        with y3:
            y_stable = st.checkbox("Stablecoin pools only", value=False)
        with y4:
            projects = sorted(ydf["project"].dropna().unique().tolist())
            y_proj = st.multiselect("Project (empty = all)", projects)

        yf = ydf.copy()
        yf["tvlUsd"] = pd.to_numeric(yf["tvlUsd"], errors="coerce")
        yf["apy"] = pd.to_numeric(yf["apy"], errors="coerce")
        yf = yf[(yf["tvlUsd"] >= y_min_tvl) & (yf["apy"].notna()) & (yf["apy"] <= y_max_apy)]
        if y_stable and "stablecoin" in yf.columns:
            yf = yf[yf["stablecoin"] == True]  # noqa: E712
        if y_proj:
            yf = yf[yf["project"].isin(y_proj)]

        if yf.empty:
            st.info("No pools match these filters.")
        else:
            ya, yb = st.columns(2)
            with ya:
                pt = yf.groupby("project", as_index=False)["tvlUsd"].sum().sort_values("tvlUsd", ascending=False).head(15)
                pt = pt.sort_values("tvlUsd")
                fig = go.Figure(go.Bar(x=pt["tvlUsd"], y=pt["project"], orientation="h", marker_color=ACCENT))
                fig.update_layout(title="Top Projects by Yield-Pool TVL", height=440,
                                  margin=dict(l=10, r=20, t=50, b=10), plot_bgcolor="white")
                show_chart(fig)
            with yb:
                fig = px.scatter(yf, x="tvlUsd", y="apy", color="project", hover_name="symbol", log_x=True,
                                 color_discrete_sequence=BLUE_SPECTRUM[:8], title="APY vs Pool TVL")
                fig.update_layout(height=440, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white",
                                  xaxis_title="Pool TVL (USD)", yaxis_title="APY (%)", showlegend=False)
                show_chart(fig)
            cols = [c for c in ["project", "symbol", "tvlUsd", "apy", "apyBase", "apyReward", "apyMean30d",
                                "stablecoin", "ilRisk", "exposure", "poolMeta"] if c in yf.columns]
            C = st.column_config
            show_table(yf.sort_values("tvlUsd", ascending=False)[cols], column_config={
                "tvlUsd": C.NumberColumn("TVL", format="$%.0f"), "apy": C.NumberColumn("APY", format="%.2f%%"),
                "apyBase": C.NumberColumn("Base APY", format="%.2f%%"),
                "apyReward": C.NumberColumn("Reward APY", format="%.2f%%"),
                "apyMean30d": C.NumberColumn("30d Avg APY", format="%.2f%%")})
            st.caption("High APY often comes from temporary token rewards or very small pools. APY is not a "
                       "guarantee, and smart-contract and impermanent-loss risks apply. Not financial advice.")
    else:
        st.info("Yield data could not be loaded (the free endpoint may be unavailable without a Pro key).")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| Protocol list | Protocols with TVL on Base, categories | [DefiLlama Protocols](https://defillama.com/protocols/Base) · `api.llama.fi/protocols` |
| Protocol analyzer | Per-protocol TVL history, other TVL types and token breakdown on Base | `api.llama.fi/protocol/{slug}` |
| Share of Base TVL | Current chain TVL | [DefiLlama – Base](https://defillama.com/chain/Base) · `api.llama.fi/v2/historicalChainTvl/Base` |
| Yield pools (optional) | Pool APY and TVL | DefiLlama Yields · `yields.llama.fi/pools` (a Pro key may be required) |
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
