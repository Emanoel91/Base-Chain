import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, MA_COLOR, BLUE_SPECTRUM, CHAIN_NAME,
    show_chart, show_table, page_header, sidebar_controls, safe_call, empty_ts,
    fmt_usd, fmt_num, fmt_pct, pct_change,
)

st.set_page_config(page_title="Base Chain - DeFi & TVL", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — DeFi & TVL",
    "Total Value Locked on <b>Base</b>: history, categories, protocols, concentration, top movers, "
    "fees and revenue, comparison with other chains, and a protocol-level analyzer. "
    "Data comes from DefiLlama's free public API. See the <b>Sources</b> section at the bottom."
)

DOWN_COLOR = "#ef4444"
LLAMA = "https://api.llama.fi"

# Categories DefiLlama tracks but does NOT count toward a chain's headline TVL
EXCLUDED_FROM_CHAIN_TVL = {"Liquid Staking", "Bridge", "Onchain Capital Allocator", "Risk Curators"}

try:
    LLAMA_KEY = st.secrets.get("DEFILLAMA_API_KEY", None)
except Exception:
    LLAMA_KEY = None


# ============================================================
# --- Fetchers ---
# ============================================================
def get_json(url, params=None, timeout=60):
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


@st.cache_data(ttl=3600, show_spinner=False)
def get_chain_tvl(chain: str) -> pd.DataFrame:
    df = pd.DataFrame(get_json(f"{LLAMA}/v2/historicalChainTvl/{chain}"))
    df["date"] = pd.to_datetime(df["date"], unit="s")
    df = df.rename(columns={"tvl": "value"})
    return df[["date", "value"]].sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_all_chains() -> pd.DataFrame:
    df = pd.DataFrame(get_json(f"{LLAMA}/v2/chains")).sort_values("tvl", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def get_protocols(chain: str) -> pd.DataFrame:
    rows = []
    for p in get_json(f"{LLAMA}/protocols"):
        tvl_chain = ((p.get("chainTvls") or {}).get(chain)) or 0
        if tvl_chain and tvl_chain > 0:
            total = p.get("tvl")
            mcap = p.get("mcap")
            rows.append({
                "Protocol": p.get("name"),
                "Slug": p.get("slug"),
                "Category": p.get("category") or "Other",
                "TVL": tvl_chain,
                "Total TVL": total,
                "Chains": len(p.get("chains") or []),
                "Change 1d (%)": p.get("change_1d"),
                "Change 7d (%)": p.get("change_7d"),
                "Change 30d (%)": p.get("change_1m"),
                "Mcap": mcap,
                "Mcap/TVL": round(mcap / total, 2) if mcap and total else None,
                "URL": p.get("url"),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Base % of Protocol"] = df.apply(
            lambda r: r["TVL"] / r["Total TVL"] * 100 if r["Total TVL"] else None, axis=1)
        df["Counted in Chain TVL"] = ~df["Category"].isin(EXCLUDED_FROM_CHAIN_TVL)
        df = df.sort_values("TVL", ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=1800, show_spinner=False)
def get_protocol_detail(slug: str, chain: str) -> dict:
    j = get_json(f"{LLAMA}/protocol/{slug}")
    ct = j.get("chainTvls") or {}
    block = ct.get(chain) or {}

    tvl = pd.DataFrame(block.get("tvl") or [])
    if not tvl.empty:
        tvl["date"] = pd.to_datetime(tvl["date"], unit="s")
        tvl = tvl.rename(columns={"totalLiquidityUSD": "value"})[["date", "value"]]
        tvl = tvl.sort_values("date").reset_index(drop=True)
    else:
        tvl = empty_ts()

    rows = []
    for item in block.get("tokensInUsd") or []:
        rec = {"date": pd.to_datetime(item.get("date"), unit="s")}
        rec.update(item.get("tokens") or {})
        rows.append(rec)
    tok = pd.DataFrame(rows)
    if not tok.empty:
        tok = tok.sort_values("date").set_index("date").apply(pd.to_numeric, errors="coerce").fillna(0)

    flavors = {}
    for k, v in ct.items():
        if k.startswith(chain + "-") and isinstance(v, dict) and v.get("tvl"):
            flavors[k.split("-", 1)[1]] = v["tvl"][-1].get("totalLiquidityUSD")

    listed = j.get("listedAt")
    return {
        "name": j.get("name"), "description": j.get("description"), "url": j.get("url"),
        "twitter": j.get("twitter"), "category": j.get("category"), "symbol": j.get("symbol"),
        "mcap": j.get("mcap"),
        "listed": datetime.fromtimestamp(listed, tz=timezone.utc).strftime("%Y-%m-%d") if listed else None,
        "tvl": tvl, "tokens": tok, "flavors": flavors,
    }


def llama_series(arr) -> pd.DataFrame:
    if not arr:
        return empty_ts()
    df = pd.DataFrame(arr, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"], unit="s")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_fees(chain: str, data_type: str) -> dict:
    j = get_json(f"{LLAMA}/overview/fees/{chain}", {
        "dataType": data_type,
        "excludeTotalDataChart": "false",
        "excludeTotalDataChartBreakdown": "true",
    })
    prot = pd.DataFrame(j.get("protocols") or [])
    if not prot.empty:
        prot["Name"] = prot["displayName"] if "displayName" in prot.columns else prot.get("name")
        for c in ["total24h", "total7d", "total30d", "change_1d"]:
            if c not in prot.columns:
                prot[c] = None
            prot[c] = pd.to_numeric(prot[c], errors="coerce")
        if "category" not in prot.columns:
            prot["category"] = None
    return {
        "total24h": j.get("total24h"), "total7d": j.get("total7d"), "total30d": j.get("total30d"),
        "change_1d": j.get("change_1d"), "protocols": prot,
        "series": llama_series(j.get("totalDataChart")),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_stablecoins(chain: str) -> pd.DataFrame:
    rows = []
    for d in get_json(f"https://stablecoins.llama.fi/stablecoincharts/{chain}"):
        usd = (d.get("totalCirculatingUSD") or {}).get("peggedUSD")
        rows.append({"date": pd.to_datetime(int(d["date"]), unit="s"), "value": usd})
    df = pd.DataFrame(rows)
    if df.empty:
        return empty_ts()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=1800, show_spinner=False)
def get_yield_pools(chain: str, key: str | None) -> pd.DataFrame:
    url = f"https://pro-api.llama.fi/{key}/yields/pools" if key else "https://yields.llama.fi/pools"
    data = get_json(url, timeout=120).get("data", [])
    df = pd.DataFrame([d for d in data if d.get("chain") == chain])
    return df


# ============================================================
# --- Load data ---
# ============================================================
with st.spinner("Loading DeFi data..."):
    tvl_df = sc(get_chain_tvl, CHAIN_NAME, default=empty_ts(), label="DefiLlama chain TVL")
    chains_df = sc(get_all_chains, default=pd.DataFrame(), label="DefiLlama chains")
    protocols_df = sc(get_protocols, CHAIN_NAME, default=pd.DataFrame(), label="DefiLlama protocols")
    fees = sc(get_fees, CHAIN_NAME, "dailyFees", default={}, label="DefiLlama fees") or {}
    revenue = sc(get_fees, CHAIN_NAME, "dailyRevenue", default={}, label="DefiLlama revenue") or {}
    stable_df = sc(get_stablecoins, CHAIN_NAME, default=empty_ts(), label="DefiLlama stablecoins")

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

# concentration
top1_name, top1, top3, top10, hhi = "N/A", None, None, None, None
if not counted_df.empty:
    tot = counted_df["TVL"].sum()
    shares = (counted_df["TVL"] / tot * 100).sort_values(ascending=False).reset_index(drop=True)
    top1_name = counted_df.sort_values("TVL", ascending=False).iloc[0]["Protocol"]
    top1, top3, top10 = shares.head(1).sum(), shares.head(3).sum(), shares.head(10).sum()
    hhi = float((shares ** 2).sum())

fees24 = fees.get("total24h") if fees else None
fees30 = fees.get("total30d") if fees else None
rev24 = revenue.get("total24h") if revenue else None
fee_yield = (fees30 * 365 / 30 / current_tvl * 100) if fees30 and current_tvl else None
stable_now = stable_df.iloc[-1]["value"] if not stable_df.empty else None

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

d1, d2, d3, d4 = st.columns(4)
d1.metric("Chain Fees (24h)", fmt_usd(fees24), fmt_pct(fees.get("change_1d")) if fees and fees.get("change_1d") is not None else None)
d2.metric("Chain Revenue (24h)", fmt_usd(rev24))
d3.metric("Annualized Fees / TVL", f"{fee_yield:.2f}%" if fee_yield is not None else "N/A")
d4.metric("Stablecoins on Base", fmt_usd(stable_now))

e1, e2, e3, e4 = st.columns(4)
e1.metric("Top Protocol Share", f"{top1:.1f}%" if top1 is not None else "N/A", top1_name, delta_color="off")
e2.metric("Top-3 Share", f"{top3:.1f}%" if top3 is not None else "N/A")
e3.metric("Top-10 Share", f"{top10:.1f}%" if top10 is not None else "N/A")
e4.metric("Concentration (HHI)", f"{hhi:,.0f}" if hhi is not None else "N/A")
st.caption("HHI = sum of squared protocol shares (0–10,000). Higher means TVL is concentrated in fewer protocols. "
           "'Annualized Fees / TVL' = last-30-day fees scaled to a year, divided by current TVL.")

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
fig.update_layout(title="Base — Total Value Locked", height=420, margin=dict(l=10, r=10, t=50, b=10),
                  yaxis_title="TVL (USD)", yaxis_type="log" if log_y else "linear",
                  hovermode="x unified", plot_bgcolor="white", legend=dict(orientation="h", y=1.1, x=0))
show_chart(fig)

st.markdown("---")

# ============================================================
# --- Chain comparison ---
# ============================================================
st.subheader("Compare With Other Chains")
if not chains_df.empty:
    names = chains_df.head(25)["name"].tolist()
    defaults = [n for n in ["Ethereum", "Arbitrum", "OP Mainnet", "Solana"] if n in names]
    cc1, cc2 = st.columns([3, 1])
    with cc1:
        picked = st.multiselect("Chains to compare (top 25 by TVL)", [n for n in names if n != CHAIN_NAME],
                                default=defaults, key="cmp_chains")
    with cc2:
        mode = st.radio("View", ["Indexed (=100 at start)", "Absolute TVL"], key="cmp_mode")

    series = {CHAIN_NAME: tvl_df}
    for ch in picked:
        s = sc(get_chain_tvl, ch, default=empty_ts(), label=f"DefiLlama TVL {ch}")
        if s is not None and not s.empty:
            series[ch] = s
    ranged = {k: in_range(v) for k, v in series.items()}
    ranged = {k: v for k, v in ranged.items() if not v.empty}
    if len(ranged) >= 1:
        start = max(v["date"].min() for v in ranged.values())
        fig = go.Figure()
        for i, (k, v) in enumerate(ranged.items()):
            v = v[v["date"] >= start]
            if v.empty:
                continue
            y = v["value"] / v["value"].iloc[0] * 100 if mode.startswith("Indexed") else v["value"]
            line_style = dict(color=ACCENT, width=3) if k == CHAIN_NAME else dict(width=1.5)
            fig.add_trace(go.Scatter(x=v["date"], y=y, mode="lines", name=k, line=line_style))
        fig.update_layout(
            title="TVL Comparison" + (" (indexed)" if mode.startswith("Indexed") else ""),
            height=420, margin=dict(l=10, r=10, t=50, b=10),
            yaxis_title="Index" if mode.startswith("Indexed") else "TVL (USD)",
            hovermode="x unified", plot_bgcolor="white")
        show_chart(fig)
        st.caption("Indexed view starts all chains at 100 on the same date (the latest start among the selected "
                   "chains in the chosen range), so growth rates are comparable.")

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
               "deployed on), not Base-only. Use the Protocol Analyzer below for Base-specific history.")

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
# --- Fees & revenue ---
# ============================================================
st.subheader("Fees & Revenue")
fee_series, rev_series = (fees.get("series", empty_ts()) if fees else empty_ts(),
                          revenue.get("series", empty_ts()) if revenue else empty_ts())
if not fee_series.empty:
    fr = st.radio("Range", list(range_map.keys()), horizontal=True, index=2, key="fee_range")
    dd = range_map[fr]

    def rng(df):
        if df.empty or dd is None:
            return df
        return df[df["date"] >= df["date"].max() - timedelta(days=dd)]

    fig = go.Figure()
    f_ = rng(fee_series)
    fig.add_trace(go.Bar(x=f_["date"], y=f_["value"], marker_color=ACCENT, name="Fees"))
    if not rev_series.empty:
        r_ = rng(rev_series)
        fig.add_trace(go.Scatter(x=r_["date"], y=r_["value"], mode="lines",
                                 line=dict(color=MA_COLOR, width=2), name="Revenue"))
    fig.update_layout(title="Daily Chain Fees & Revenue", height=400, margin=dict(l=10, r=10, t=50, b=10),
                      yaxis_title="USD", hovermode="x unified", plot_bgcolor="white",
                      legend=dict(orientation="h", y=1.1, x=0))
    show_chart(fig)

fprot = fees.get("protocols", pd.DataFrame()) if fees else pd.DataFrame()
rprot = revenue.get("protocols", pd.DataFrame()) if revenue else pd.DataFrame()
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
    show_table(fp, column_config={
        c: C.NumberColumn(format="$%.0f") for c in ["Fees 24h", "Fees 7d", "Fees 30d", "Revenue 24h", "Revenue 30d"]
        if c in fp.columns} | {"Change 1d (%)": C.NumberColumn(format="%.2f%%")})
    st.caption("Fees = total paid by users; revenue = the part kept by the protocol/token holders (DefiLlama definitions). "
               "Not every protocol reports revenue.")
else:
    st.info("Fees data is unavailable right now.")

st.markdown("---")

# ============================================================
# --- Protocol analyzer ---
# ============================================================
st.subheader("Protocol Analyzer (Base-specific history)")
if not protocols_df.empty:
    plist = protocols_df.sort_values("TVL", ascending=False)
    label_map = {f"{r['Protocol']} — {fmt_usd(r['TVL'])}": r["Slug"] for _, r in plist.iterrows()}
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
                                  margin=dict(l=10, r=10, t=50, b=10), hovermode="x unified",
                                  plot_bgcolor="white", legend=dict(orientation="h", y=-0.15))
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
| TVL history, KPIs, ATH, rank, dominance, chain comparison | Historical chain TVL and all-chains TVL | [DefiLlama – Base](https://defillama.com/chain/Base) · `api.llama.fi/v2/historicalChainTvl/{chain}`, `/v2/chains` |
| Categories, protocols, movers, full table | Protocol list with per-chain TVL, categories, changes, market cap | [DefiLlama Protocols](https://defillama.com/protocols/Base) · `api.llama.fi/protocols` |
| Fees & revenue | Chain and protocol fees / revenue (daily, 24h, 7d, 30d) | [DefiLlama Fees](https://defillama.com/fees/chain/base) · `api.llama.fi/overview/fees/Base` |
| Stablecoins KPI | Circulating stablecoins on Base | [DefiLlama Stablecoins](https://defillama.com/stablecoins/Base) · `stablecoins.llama.fi` |
| Protocol analyzer | Per-protocol TVL history and token breakdown on Base | `api.llama.fi/protocol/{slug}` |
| Yield pools (optional) | Pool APY and TVL | DefiLlama Yields · `yields.llama.fi/pools` (Pro key may be required) |
| Derived metrics | Concentration (top-N share, HHI), fee yield, indexed comparison, Base share | Calculated in this app |
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
