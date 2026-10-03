import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, MA_COLOR, BLUE_SPECTRUM, CHAIN_NAME,
    show_chart, show_table, page_header, sidebar_controls, safe_call, empty_ts,
    fmt_usd, fmt_pct, pct_change,
)
from llama import get_chain_tvl, get_all_chains, get_protocols
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
    page_title="Base Chain — TVL",
    page_icon="https://images.cryptorank.io/coins/150x150.base1752857325751.png",
    layout="wide"
)

# --- Title with Logo ---
st.markdown(
    """
    <div style="display: flex; align-items: center; gap: 15px;">
        <img src="https://images.cryptorank.io/coins/150x150.base1752857325751.png" alt="Base" style="width:60px; height:60px;">
        <h1 style="margin: 0;">Base Chain — TVL</h1>
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




# ============================================================
# --- Load data ---
# ============================================================
with st.spinner("Loading TVL data..."):
    tvl_df = sc(get_chain_tvl, CHAIN_NAME, default=empty_ts(), label="DefiLlama chain TVL")
    chains_df = sc(get_all_chains, default=pd.DataFrame(), label="DefiLlama chains")
    protocols_df = sc(get_protocols, CHAIN_NAME, default=pd.DataFrame(), label="DefiLlama protocols")

if tvl_df.empty:
    st.warning("TVL history is unavailable right now.")
    if errors:
        with st.expander("⚠️ Data warnings"):
            for e in errors:
                st.write(f"- {e}")
    st.stop()

counted_df = protocols_df[protocols_df["Counted in Chain TVL"]] if not protocols_df.empty else protocols_df

# ============================================================
# --- KPIs ---
# ============================================================
current_tvl = tvl_df.iloc[-1]["value"]
current_date = tvl_df.iloc[-1]["date"]
c1d, c7d, c30d = pct_change(tvl_df, 1), pct_change(tvl_df, 7), pct_change(tvl_df, 30)
ath_row = tvl_df.loc[tvl_df["value"].idxmax()]
ath_tvl, ath_date = ath_row["value"], ath_row["date"]
from_ath = (current_tvl - ath_tvl) / ath_tvl * 100 if ath_tvl else None

chain_rank, dominance = None, None
if not chains_df.empty:
    row = chains_df[chains_df["name"] == CHAIN_NAME]
    chain_rank = int(row["rank"].values[0]) if not row.empty else None
    total_defi = chains_df["tvl"].sum()
    dominance = current_tvl / total_defi * 100 if total_defi else None

top1_name, top1, top3, top10, hhi = "N/A", None, None, None, None
if not counted_df.empty:
    tot = counted_df["TVL"].sum()
    shares = (counted_df["TVL"] / tot * 100).sort_values(ascending=False).reset_index(drop=True)
    top1_name = counted_df.sort_values("TVL", ascending=False).iloc[0]["Protocol"]
    top1, top3, top10 = shares.head(1).sum(), shares.head(3).sum(), shares.head(10).sum()
    hhi = float((shares ** 2).sum())

st.markdown(f"##### As of {current_date.strftime('%Y-%m-%d')}")
a1, a2, a3, a4 = st.columns(4)
a1.metric("Total TVL", fmt_usd(current_tvl), fmt_pct(c1d))
a2.metric("TVL Change (7d)", fmt_pct(c7d))
a3.metric("TVL Change (30d)", fmt_pct(c30d))
a4.metric("Chain Rank by TVL", f"#{chain_rank}" if chain_rank else "N/A")

b1, b2, b3, b4 = st.columns(4)
b1.metric("All-Time High TVL", fmt_usd(ath_tvl), ath_date.strftime("%Y-%m-%d"), delta_color="off")
b2.metric("Down From ATH", fmt_pct(from_ath))
b3.metric("DeFi TVL Dominance", f"{dominance:.2f}%" if dominance is not None else "N/A")
b4.metric("Protocols (counted in TVL)", f"{len(counted_df)}" if not protocols_df.empty else "N/A")

e1, e2, e3, e4 = st.columns(4)
e1.metric("Top Protocol Share", f"{top1:.1f}%" if top1 is not None else "N/A", top1_name, delta_color="off")
e2.metric("Top-3 Share", f"{top3:.1f}%" if top3 is not None else "N/A")
e3.metric("Top-10 Share", f"{top10:.1f}%" if top10 is not None else "N/A")
e4.metric("Concentration (HHI)", f"{hhi:,.0f}" if hhi is not None else "N/A")
st.caption("HHI = sum of squared protocol shares (0–10,000). Higher means TVL is concentrated in fewer protocols.")

st.markdown("---")

# ============================================================
# --- TVL history ---
# ============================================================
st.subheader("TVL History")
h1, h2, h3 = st.columns([3, 1, 1])
range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}
with h1:
    rc = st.radio("Range", list(range_map.keys()), horizontal=True, index=4, key="tvl_range")
with h2:
    log_y = st.checkbox("Log scale", value=False, key="tvl_log")
with h3:
    show_ma = st.checkbox("7D moving avg", value=False, key="tvl_ma")
d = range_map[rc]


def in_range(df):
    if df.empty or d is None:
        return df
    return df[df["date"] >= df["date"].max() - timedelta(days=d)]


plot_df = in_range(tvl_df)
fig = go.Figure(go.Scatter(x=plot_df["date"], y=plot_df["value"], mode="lines", fill="tozeroy",
                           line=dict(color=ACCENT, width=2), fillcolor=ACCENT_FILL, name="TVL"))
if show_ma:
    fig.add_trace(go.Scatter(x=tvl_df["date"], y=tvl_df["value"].rolling(7).mean(), mode="lines",
                             line=dict(color=MA_COLOR, width=2), name="7D MA"))
    fig.update_xaxes(range=[plot_df["date"].min(), plot_df["date"].max()])
fig.update_layout(title="Base — Total Value Locked", height=420, margin=dict(l=10, r=10, t=80, b=10),
                  yaxis_title="TVL (USD)", yaxis_type="log" if log_y else "linear",
                  hovermode="x unified", plot_bgcolor="white", legend=LEGEND_TOP_CENTER)
show_chart(fig)

st.markdown("---")

# ============================================================
# --- Chain comparison ---
# ============================================================
st.subheader("Compare With Other Chains")
if not chains_df.empty:
    names = chains_df.head(25)["name"].tolist()
    defaults = [n for n in ["Ethereum", "Arbitrum", "OP Mainnet", "Solana"] if n in names]
    cc1, cc2, cc3 = st.columns([3, 2, 2])
    with cc1:
        picked = st.multiselect("Chains to compare (top 25 by TVL)", [n for n in names if n != CHAIN_NAME],
                                default=defaults, key="cmp_chains")
    with cc2:
        mode = st.radio("View", ["Indexed (=100 at start)", "Absolute TVL"], key="cmp_mode")
    indexed = mode.startswith("Indexed")
    with cc3:
        min_start = st.number_input("Start indexing when every chain's TVL ≥ (USD)", min_value=0,
                                    value=1_000_000, step=500_000, disabled=not indexed, key="cmp_min")

    series = {CHAIN_NAME: tvl_df}
    for ch in picked:
        s = sc(get_chain_tvl, ch, default=empty_ts(), label=f"DefiLlama TVL {ch}")
        if s is not None and not s.empty:
            series[ch] = s
    ranged = {k: in_range(v) for k, v in series.items()}
    ranged = {k: v for k, v in ranged.items() if not v.empty}

    plotted = {}
    if indexed:
        # Base (and other new chains) start with zero / tiny TVL, which breaks "=100" normalisation.
        # So we start only once every selected chain has reached the threshold.
        starts = {}
        for k, v in ranged.items():
            ok = v[v["value"] >= max(min_start, 1)]
            if not ok.empty:
                starts[k] = ok["date"].min()
        skipped = [k for k in ranged if k not in starts]
        if skipped:
            st.caption("Not shown (TVL never reached the threshold in this range): " + ", ".join(skipped))
        if starts:
            start = max(starts.values())
            for k in starts:
                v = ranged[k]
                v = v[v["date"] >= start]
                if v.empty or not v["value"].iloc[0]:
                    continue
                plotted[k] = pd.DataFrame({"date": v["date"], "y": v["value"] / v["value"].iloc[0] * 100})
    else:
        if ranged:
            start = max(v["date"].min() for v in ranged.values())
            for k, v in ranged.items():
                v = v[v["date"] >= start]
                if not v.empty:
                    plotted[k] = pd.DataFrame({"date": v["date"], "y": v["value"]})

    if plotted:
        fig = go.Figure()
        # draw other chains first, Base last so it stays on top
        for k in [x for x in plotted if x != CHAIN_NAME] + ([CHAIN_NAME] if CHAIN_NAME in plotted else []):
            style = dict(color=ACCENT, width=3.5) if k == CHAIN_NAME else dict(width=1.6)
            fig.add_trace(go.Scatter(x=plotted[k]["date"], y=plotted[k]["y"], mode="lines", name=k, line=style))
        fig.update_layout(
            title="TVL Comparison" + (" (indexed)" if indexed else ""),
            height=440, margin=dict(l=10, r=10, t=80, b=10),
            yaxis_title="Index (start = 100)" if indexed else "TVL (USD)",
            hovermode="x unified", plot_bgcolor="white", legend=LEGEND_TOP_CENTER)
        show_chart(fig)
        if indexed:
            st.caption(f"All chains are set to 100 on {start.strftime('%Y-%m-%d')}, the first day every selected "
                       "chain had at least the threshold TVL, so growth rates are comparable.")
    else:
        st.info("Nothing to plot for this selection. Try a lower threshold or a longer range.")

    top_chains = chains_df.head(15).sort_values("tvl")
    fig = go.Figure(go.Bar(
        x=top_chains["tvl"], y=top_chains["name"], orientation="h",
        marker_color=[ACCENT if n == CHAIN_NAME else "#b3b3ff" for n in top_chains["name"]],
        text=[fmt_usd(v) for v in top_chains["tvl"]], textposition="outside"))
    fig.update_layout(title="Top 15 Chains by TVL (Base highlighted if present)", height=480,
                      margin=dict(l=10, r=70, t=50, b=10), xaxis_title="TVL (USD)", plot_bgcolor="white")
    show_chart(fig)
else:
    st.info("Chain list is unavailable right now.")

st.markdown("---")

# ============================================================
# --- Categories & protocols ---
# ============================================================
st.subheader("TVL by Category & Protocol")
if protocols_df.empty:
    st.info("Protocol-level data is unavailable right now.")
else:
    include_excluded = st.checkbox(
        "Also include categories excluded from headline Chain TVL "
        "(Liquid Staking, Bridge, Onchain Capital Allocator, Risk Curators)", value=False)
    src = protocols_df if include_excluded else counted_df
    n_excl = int((~protocols_df["Counted in Chain TVL"]).sum())
    if n_excl:
        st.caption(f"{n_excl} protocol(s) belong to categories DefiLlama tracks but excludes from a chain's "
                   "headline TVL to avoid double counting. They are hidden by default.")

    cat_df = src.groupby("Category", as_index=False)["TVL"].sum().sort_values("TVL", ascending=False)
    cat_df["Share (%)"] = cat_df["TVL"] / cat_df["TVL"].sum() * 100
    cl, cr = st.columns(2)
    with cl:
        fig = px.pie(cat_df, names="Category", values="TVL", hole=0.5,
                     color_discrete_sequence=BLUE_SPECTRUM, title="TVL by Category")
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
        show_chart(fig)
    with cr:
        top10_df = src.sort_values("TVL", ascending=False).head(10).sort_values("TVL")
        fig = go.Figure(go.Bar(x=top10_df["TVL"], y=top10_df["Protocol"], orientation="h", marker_color=ACCENT,
                               text=[fmt_usd(v) for v in top10_df["TVL"]], textposition="outside"))
        fig.update_layout(title="Top 10 Protocols by TVL on Base", height=420,
                          margin=dict(l=10, r=70, t=50, b=10), xaxis_title="TVL (USD)", plot_bgcolor="white")
        show_chart(fig)

    tm = src[src["TVL"] > 0].copy()
    fig = px.treemap(tm, path=["Category", "Protocol"], values="TVL", color="Category",
                     color_discrete_sequence=BLUE_SPECTRUM, title="TVL Treemap (category → protocol)")
    fig.update_traces(textinfo="label+percent root")
    fig.update_layout(height=520, margin=dict(l=10, r=10, t=50, b=10))
    show_chart(fig)

    log_cat = st.checkbox("Log scale (category bars)", value=False, key="cat_log")
    cb1, cb2 = st.columns(2)
    with cb1:
        fig = go.Figure(go.Bar(x=cat_df["Category"], y=cat_df["TVL"], marker_color=ACCENT,
                               text=[fmt_usd(v) for v in cat_df["TVL"]], textposition="outside"))
        fig.update_layout(title="TVL by Category (bars)", height=420, margin=dict(l=10, r=10, t=50, b=10),
                          yaxis_title="TVL (USD)", yaxis_type="log" if log_cat else "linear",
                          xaxis_tickangle=-30, plot_bgcolor="white")
        show_chart(fig)
    with cb2:
        cat_show = cat_df.copy()
        cat_show["Protocols"] = cat_show["Category"].map(src.groupby("Category")["Protocol"].count())
        C = st.column_config
        show_table(cat_show, column_config={
            "TVL": C.NumberColumn(format="$%.0f"), "Share (%)": C.NumberColumn(format="%.2f%%")})

    st.markdown("---")

    # ------------------------------------------------------------
    # Movers
    # ------------------------------------------------------------
    st.subheader("Top Movers")
    min_tvl = st.number_input("Minimum TVL on Base (USD) to include", min_value=0, value=1_000_000, step=500_000)
    mv = src[src["TVL"] >= min_tvl]

    def mover_chart(col, ascending, title, color):
        s = mv[mv[col].notna()]
        s = s[s[col] < 0] if ascending else s[s[col] > 0]
        s = s.sort_values(col, ascending=ascending).head(10)
        if s.empty:
            st.info(f"No protocols for: {title}")
            return
        s = s.sort_values(col, ascending=not ascending)
        fig = go.Figure(go.Bar(x=s[col], y=s["Protocol"], orientation="h", marker_color=color,
                               text=[f"{v:+.2f}%" for v in s[col]], textposition="outside"))
        fig.update_layout(title=title, height=400, margin=dict(l=10, r=60, t=50, b=10),
                          xaxis_title="Change (%)", plot_bgcolor="white")
        show_chart(fig)

    g1, g2 = st.columns(2)
    with g1:
        mover_chart("Change 1d (%)", False, "Top Gainers — 1 Day", ACCENT)
    with g2:
        mover_chart("Change 7d (%)", False, "Top Gainers — 7 Days", ACCENT)
    l1, l2 = st.columns(2)
    with l1:
        mover_chart("Change 1d (%)", True, "Top Losers — 1 Day", DOWN_COLOR)
    with l2:
        mover_chart("Change 7d (%)", True, "Top Losers — 7 Days", DOWN_COLOR)
    st.caption("Change percentages are DefiLlama's protocol-wide figures (across all chains the protocol is "
               "deployed on), not Base-only. Use the Protocol Analyzer page for Base-specific history.")

    st.markdown("---")

    # ------------------------------------------------------------
    # Full table
    # ------------------------------------------------------------
    st.subheader("All Protocols on Base")
    t1, t2 = st.columns([2, 3])
    with t1:
        cats = sorted(src["Category"].unique().tolist())
        cat_pick = st.multiselect("Category filter (empty = all)", cats, key="tbl_cat")
    with t2:
        search = st.text_input("Search protocol", "", key="tbl_search")
    tbl = src.copy()
    if cat_pick:
        tbl = tbl[tbl["Category"].isin(cat_pick)]
    if search:
        tbl = tbl[tbl["Protocol"].str.contains(search, case=False, na=False)]
    tbl["Share of Base TVL (%)"] = tbl["TVL"] / src["TVL"].sum() * 100
    tbl = tbl[["Protocol", "Category", "TVL", "Share of Base TVL (%)", "Total TVL", "Base % of Protocol",
               "Chains", "Change 1d (%)", "Change 7d (%)", "Change 30d (%)", "Mcap/TVL", "Counted in Chain TVL", "URL"]]
    tbl = tbl.rename(columns={"TVL": "TVL on Base", "Total TVL": "TVL (all chains)", "Chains": "# Chains",
                              "Mcap/TVL": "Mcap/TVL (all chains)"})
    C = st.column_config
    show_table(tbl, column_config={
        "TVL on Base": C.NumberColumn(format="$%.0f"), "TVL (all chains)": C.NumberColumn(format="$%.0f"),
        "Share of Base TVL (%)": C.NumberColumn(format="%.2f%%"),
        "Base % of Protocol": C.NumberColumn(format="%.1f%%"),
        "Change 1d (%)": C.NumberColumn(format="%.2f%%"), "Change 7d (%)": C.NumberColumn(format="%.2f%%"),
        "Change 30d (%)": C.NumberColumn(format="%.2f%%"),
        "Mcap/TVL (all chains)": C.NumberColumn(format="%.2f"),
        "URL": C.LinkColumn("Website"),
    })
    st.caption(f"{len(tbl)} protocols shown.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| TVL history, KPIs, ATH, rank, dominance, chain comparison | Historical chain TVL and all-chains TVL | [DefiLlama – Base](https://defillama.com/chain/Base) · `api.llama.fi/v2/historicalChainTvl/{chain}`, `/v2/chains` |
| Categories, protocols, movers, full table | Protocol list with per-chain TVL, categories, changes, market cap | [DefiLlama Protocols](https://defillama.com/protocols/Base) · `api.llama.fi/protocols` |
| Derived metrics | Concentration (top-N share, HHI), indexed comparison, Base share of each protocol | Calculated in this app |
"""
)
st.caption(
    "Notes: by DefiLlama's methodology, some categories (Liquid Staking, Bridge, Onchain Capital Allocator, "
    "Risk Curators) are excluded from the headline chain TVL to avoid double counting. TVL is not a measure of "
    "safety or quality. Third-party APIs may change limits or availability at any time."
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
