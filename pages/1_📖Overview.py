import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import requests
from datetime import datetime, timedelta, timezone

# ============================================================
# --- Page Config ---
# ============================================================
st.set_page_config(
    page_title="Base Chain - Overview",
    page_icon="🔵",
    layout="wide"
)

CHAIN_NAME = "Base"      # chain key as used by DefiLlama
CHAIN_ID = 8453          # Base chain ID
ACCENT = "#0000fe"       # main chart colour
BOX_BG = "#E5F2FF"

# Blue spectrum built around #0000fe (dark -> light), used for categorical charts
BLUE_SPECTRUM = [
    "#00007a", "#0000b0", "#0000fe", "#3333ff", "#6666ff",
    "#8c8cff", "#b3b3ff", "#ccccff", "#e0e0ff", "#f0f0ff",
]

# Categories DefiLlama tracks but does NOT count toward a chain's headline TVL
EXCLUDED_FROM_CHAIN_TVL = {
    "Liquid Staking",
    "Bridge",
    "Onchain Capital Allocator",
    "Risk Curators",
}

# Optional Blockscout PRO API key (free at dev.blockscout.com).
# Put it in .streamlit/secrets.toml as:  BLOCKSCOUT_API_KEY = "proapi_xxx"
try:
    BLOCKSCOUT_KEY = st.secrets.get("BLOCKSCOUT_API_KEY", None)
except Exception:
    BLOCKSCOUT_KEY = None

errors = []  # data warnings collected while loading


# ============================================================
# --- Small UI helpers ---
# ============================================================
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


def fmt_num(x):
    if x is None or pd.isna(x):
        return "N/A"
    if abs(x) >= 1e9:
        return f"{x/1e9:,.2f}B"
    if abs(x) >= 1e6:
        return f"{x/1e6:,.2f}M"
    if abs(x) >= 1e3:
        return f"{x/1e3:,.2f}K"
    return f"{x:,.0f}"


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


def safe_call(fn, *args, default=None, label=""):
    try:
        return fn(*args)
    except Exception as e:  # keep the page alive if one source fails
        errors.append(f"{label or fn.__name__}: {e}")
        return default


def empty_ts():
    return pd.DataFrame(columns=["date", "value"])


# ============================================================
# --- Sidebar ---
# ============================================================
st.sidebar.markdown("### Base Dashboard")
if st.sidebar.button("🔄 Refresh data"):
    st.cache_data.clear()
    st.rerun()
st.sidebar.caption("Data is cached: live stats ~1 min, charts ~1 hour.")

# ============================================================
# --- Title ---
# ============================================================
st.markdown(
    f"""
<div style="display:flex; align-items:center; gap:15px;">
<div style="width:56px; height:56px; border-radius:50%; background:{ACCENT};"></div>
<h1 style="margin:0;">Base Chain — Overview</h1>
</div>
""",
    unsafe_allow_html=True
)

st.markdown(
    f"""
<div style="
background-color:{BOX_BG}; border-left:6px solid {ACCENT};
padding:15px; border-radius:10px; margin-top:10px;
color:#1a1a1a; font-size:16px; line-height:1.6;">
A high-level view of the <b>Base</b> network: network activity (transactions, addresses, gas,
blocks), DeFi (TVL, DEX volume, fees, stablecoins) and the latest blocks.
All data comes from free public APIs — see the <b>Sources</b> section at the bottom of the page.
</div>
""",
    unsafe_allow_html=True
)
st.markdown("")


# ============================================================
# --- Data fetchers: Blockscout (on-chain stats) ---
# ============================================================
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


@st.cache_data(ttl=60, show_spinner=False)
def get_bs_stats() -> dict:
    return bs_request("/api/v2/stats")


@st.cache_data(ttl=3600, show_spinner=False)
def get_bs_tx_chart() -> pd.DataFrame:
    j = bs_request("/api/v2/stats/charts/transactions")
    df = pd.DataFrame(j.get("chart_data", []))
    if df.empty or "date" not in df.columns:
        return empty_ts()
    val_col = next((c for c in df.columns if c != "date"), None)
    out = pd.DataFrame({
        "date": pd.to_datetime(df["date"]),
        "value": pd.to_numeric(df[val_col], errors="coerce"),
    })
    # drop today's incomplete day
    today = datetime.now(timezone.utc).date()
    out = out[out["date"].dt.date < today]
    return out.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=15, show_spinner=False)
def get_latest_blocks() -> pd.DataFrame:
    j = bs_request("/api/v2/blocks")
    rows = []
    for b in j.get("items", [])[:15]:
        gas_used = safe_float(b.get("gas_used"))
        gas_limit = safe_float(b.get("gas_limit"))
        base_fee = safe_float(b.get("base_fee_per_gas"))
        tx_count = b.get("transaction_count", b.get("transactions_count", b.get("tx_count")))
        rows.append({
            "Block": b.get("height"),
            "Time (UTC)": pd.to_datetime(b.get("timestamp")).strftime("%Y-%m-%d %H:%M:%S")
            if b.get("timestamp") else None,
            "Txs": tx_count,
            "Gas Used": gas_used,
            "Gas Used (%)": round(gas_used / gas_limit * 100, 2) if gas_used is not None and gas_limit else None,
            "Base Fee (gwei)": round(base_fee / 1e9, 6) if base_fee is not None else None,
        })
    return pd.DataFrame(rows)


# ============================================================
# --- Data fetchers: DefiLlama (DeFi metrics) ---
# ============================================================
def llama_series(arr) -> pd.DataFrame:
    """[[timestamp, value], ...] -> DataFrame(date, value)"""
    if not arr:
        return empty_ts()
    df = pd.DataFrame(arr, columns=["date", "value"][:len(arr[0])])
    df["date"] = pd.to_datetime(df["date"], unit="s")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_historical_chain_tvl(chain: str) -> pd.DataFrame:
    r = requests.get(f"https://api.llama.fi/v2/historicalChainTvl/{chain}", timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json())
    df["date"] = pd.to_datetime(df["date"], unit="s")
    df = df.rename(columns={"tvl": "value"})
    return df[["date", "value"]].sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=3600, show_spinner=False)
def get_all_chains_tvl() -> pd.DataFrame:
    r = requests.get("https://api.llama.fi/v2/chains", timeout=30)
    r.raise_for_status()
    df = pd.DataFrame(r.json()).sort_values("tvl", ascending=False).reset_index(drop=True)
    df["rank"] = df.index + 1
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def get_protocols_on_chain(chain: str) -> pd.DataFrame:
    r = requests.get("https://api.llama.fi/protocols", timeout=60)
    r.raise_for_status()
    rows = []
    for p in r.json():
        tvl_on_chain = (p.get("chainTvls", {}) or {}).get(chain, 0) or 0
        if tvl_on_chain > 0:
            rows.append({
                "Protocol": p.get("name"),
                "Category": p.get("category") or "Other",
                "TVL": tvl_on_chain,
                "Change 1d (%)": p.get("change_1d"),
                "Change 7d (%)": p.get("change_7d"),
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Counted in Chain TVL"] = ~df["Category"].isin(EXCLUDED_FROM_CHAIN_TVL)
        df = df.sort_values("TVL", ascending=False).reset_index(drop=True)
    return df


@st.cache_data(ttl=3600, show_spinner=False)
def get_overview_metric(kind: str, chain: str) -> dict:
    """kind = 'dexs' (DEX volume) or 'fees' (chain fees). Returns summary + daily series."""
    url = f"https://api.llama.fi/overview/{kind}/{chain}"
    r = requests.get(url, params={
        "excludeTotalDataChart": "false",
        "excludeTotalDataChartBreakdown": "true",
    }, timeout=30)
    r.raise_for_status()
    j = r.json()
    return {
        "total24h": j.get("total24h"),
        "total7d": j.get("total7d"),
        "total30d": j.get("total30d"),
        "change_1d": j.get("change_1d"),
        "series": llama_series(j.get("totalDataChart")),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def get_stablecoin_supply(chain: str) -> pd.DataFrame:
    r = requests.get(f"https://stablecoins.llama.fi/stablecoincharts/{chain}", timeout=30)
    r.raise_for_status()
    rows = []
    for d in r.json():
        usd = (d.get("totalCirculatingUSD") or {}).get("peggedUSD")
        rows.append({"date": pd.to_datetime(int(d["date"]), unit="s"), "value": usd})
    df = pd.DataFrame(rows)
    if df.empty:
        return empty_ts()
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


# ============================================================
# --- Load data (each source degrades gracefully) ---
# ============================================================
with st.spinner("Loading Base data..."):
    stats = safe_call(get_bs_stats, default={}, label="Blockscout stats")
    tx_df = safe_call(get_bs_tx_chart, default=empty_ts(), label="Blockscout tx chart")
    blocks_df = safe_call(get_latest_blocks, default=pd.DataFrame(), label="Blockscout blocks")
    tvl_df = safe_call(get_historical_chain_tvl, CHAIN_NAME, default=empty_ts(), label="DefiLlama TVL")
    chains_df = safe_call(get_all_chains_tvl, default=pd.DataFrame(), label="DefiLlama chains")
    protocols_df = safe_call(get_protocols_on_chain, CHAIN_NAME, default=pd.DataFrame(), label="DefiLlama protocols")
    dex = safe_call(get_overview_metric, "dexs", CHAIN_NAME, default={}, label="DefiLlama DEX volume")
    fees = safe_call(get_overview_metric, "fees", CHAIN_NAME, default={}, label="DefiLlama fees")
    stable_df = safe_call(get_stablecoin_supply, CHAIN_NAME, default=empty_ts(), label="DefiLlama stablecoins")

dex_df = dex.get("series", empty_ts()) if dex else empty_ts()
fees_df = fees.get("series", empty_ts()) if fees else empty_ts()

# ============================================================
# --- KPI calculations ---
# ============================================================
stats = stats or {}
eth_price = safe_float(stats.get("coin_price"))
total_txs = safe_float(stats.get("total_transactions"))
total_addresses = safe_float(stats.get("total_addresses"))
total_blocks = safe_float(stats.get("total_blocks"))
avg_block_ms = safe_float(stats.get("average_block_time"))
txs_today = safe_float(stats.get("transactions_today"))
utilization = safe_float(stats.get("network_utilization_percentage"))
gas_prices = stats.get("gas_prices") or {}
gas_avg = safe_float(gas_prices.get("average")) if isinstance(gas_prices, dict) else None

current_tvl = tvl_df.iloc[-1]["value"] if not tvl_df.empty else None
tvl_date = tvl_df.iloc[-1]["date"] if not tvl_df.empty else None
tvl_1d, tvl_7d, tvl_30d = pct_change(tvl_df, 1), pct_change(tvl_df, 7), pct_change(tvl_df, 30)

chain_rank, dominance = None, None
if not chains_df.empty and current_tvl:
    row = chains_df[chains_df["name"] == CHAIN_NAME]
    chain_rank = int(row["rank"].values[0]) if not row.empty else None
    total_defi = chains_df["tvl"].sum()
    dominance = current_tvl / total_defi * 100 if total_defi else None

ath_tvl, ath_date, from_ath = None, None, None
if not tvl_df.empty:
    ath_row = tvl_df.loc[tvl_df["value"].idxmax()]
    ath_tvl, ath_date = ath_row["value"], ath_row["date"]
    from_ath = (current_tvl - ath_tvl) / ath_tvl * 100 if ath_tvl else None

counted_df = (protocols_df[protocols_df["Counted in Chain TVL"]]
              if not protocols_df.empty else protocols_df)
num_protocols = len(protocols_df)

stable_now = stable_df.iloc[-1]["value"] if not stable_df.empty else None
stable_7d = pct_change(stable_df, 7)

# ============================================================
# --- KPI rows ---
# ============================================================
if tvl_date is not None:
    st.markdown(f"##### DeFi data as of {tvl_date.strftime('%Y-%m-%d')}")

st.markdown("**Network**")
n1, n2, n3, n4 = st.columns(4)
n1.metric("ETH Price", fmt_usd(eth_price))
n2.metric("Total Transactions", fmt_num(total_txs))
n3.metric("Total Addresses", fmt_num(total_addresses))
n4.metric("Total Blocks", fmt_num(total_blocks))

n5, n6, n7, n8 = st.columns(4)
n5.metric("Transactions Today (UTC)", fmt_num(txs_today))
n6.metric("Avg Block Time", f"{avg_block_ms/1000:.2f}s" if avg_block_ms else "N/A")
n7.metric("Avg Gas Price", f"{gas_avg:.4f} gwei" if gas_avg is not None else "N/A")
n8.metric("Network Utilization", f"{utilization:.2f}%" if utilization is not None else "N/A")

st.markdown("**DeFi**")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Total TVL", fmt_usd(current_tvl), fmt_pct(tvl_1d))
d2.metric("TVL Change (7d)", fmt_pct(tvl_7d))
d3.metric("TVL Change (30d)", fmt_pct(tvl_30d))
d4.metric("Chain Rank by TVL", f"#{chain_rank}" if chain_rank else "N/A")

d5, d6, d7, d8 = st.columns(4)
d5.metric("DEX Volume (24h)", fmt_usd(dex.get("total24h")) if dex else "N/A",
          fmt_pct(dex.get("change_1d")) if dex else None)
d6.metric("Chain Fees (24h)", fmt_usd(fees.get("total24h")) if fees else "N/A",
          fmt_pct(fees.get("change_1d")) if fees else None)
d7.metric("Stablecoins Supply", fmt_usd(stable_now), fmt_pct(stable_7d) + " (7d)" if stable_7d is not None else None)
d8.metric("DeFi TVL Dominance", fmt_pct(dominance).replace("+", "") if dominance is not None else "N/A")

d9, d10, d11, d12 = st.columns(4)
d9.metric("All-Time High TVL", fmt_usd(ath_tvl), ath_date.strftime("%Y-%m-%d") if ath_date is not None else None)
d10.metric("Down From ATH", fmt_pct(from_ath))
d11.metric("DEX Volume (7d)", fmt_usd(dex.get("total7d")) if dex else "N/A")
d12.metric("Protocols on Base", f"{num_protocols}" if num_protocols else "N/A")

st.markdown("---")

# ============================================================
# --- Time-series charts ---
# ============================================================
range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}
range_choice = st.radio("Range", list(range_map.keys()), horizontal=True, index=2,
                        label_visibility="collapsed")
days = range_map[range_choice]


def in_range(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or days is None:
        return df
    return df[df["date"] >= df["date"].max() - timedelta(days=days)]


def area_chart(df, title, y_title):
    df = in_range(df)
    fig = go.Figure(go.Scatter(
        x=df["date"], y=df["value"], mode="lines", fill="tozeroy",
        line=dict(color=ACCENT, width=2), fillcolor="rgba(0,0,254,0.12)", name=title
    ))
    fig.update_layout(title=title, height=380, margin=dict(l=10, r=10, t=50, b=10),
                      yaxis_title=y_title, xaxis_title=None,
                      hovermode="x unified", plot_bgcolor="white")
    return fig


def bar_chart(df, title, y_title):
    df = in_range(df)
    fig = go.Figure(go.Bar(x=df["date"], y=df["value"], marker_color=ACCENT, name=title))
    fig.update_layout(title=title, height=380, margin=dict(l=10, r=10, t=50, b=10),
                      yaxis_title=y_title, xaxis_title=None,
                      hovermode="x unified", plot_bgcolor="white")
    return fig


if not tvl_df.empty:
    show_chart(area_chart(tvl_df, "Historical TVL", "TVL (USD)"))
else:
    st.info("TVL history is unavailable right now.")

c_left, c_right = st.columns(2)
with c_left:
    if not tx_df.empty:
        show_chart(bar_chart(tx_df, "Daily Transactions", "Transactions"))
    else:
        st.info("Daily transactions chart is unavailable right now.")
with c_right:
    if not stable_df.empty:
        show_chart(area_chart(stable_df, "Stablecoins Circulating on Base", "Supply (USD)"))
    else:
        st.info("Stablecoin supply chart is unavailable right now.")

c_left, c_right = st.columns(2)
with c_left:
    if not dex_df.empty:
        show_chart(bar_chart(dex_df, "Daily DEX Volume", "Volume (USD)"))
    else:
        st.info("DEX volume chart is unavailable right now.")
with c_right:
    if not fees_df.empty:
        show_chart(bar_chart(fees_df, "Daily Chain Fees", "Fees (USD)"))
    else:
        st.info("Fees chart is unavailable right now.")

st.markdown("---")

# ============================================================
# --- TVL by category & top protocols ---
# ============================================================
include_excluded = st.checkbox(
    "Also include categories excluded from headline Chain TVL "
    "(Liquid Staking, Bridge, Onchain Capital Allocator, Risk Curators)",
    value=False
)
src_df = protocols_df if include_excluded else counted_df

col_l, col_r = st.columns(2)
with col_l:
    if not src_df.empty:
        cat_df = (src_df.groupby("Category", as_index=False)["TVL"].sum()
                  .sort_values("TVL", ascending=False))
        fig = px.pie(cat_df, names="Category", values="TVL", hole=0.5,
                     color_discrete_sequence=BLUE_SPECTRUM, title="TVL by Category")
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
        show_chart(fig)
    else:
        st.info("Protocol-level data is unavailable right now.")

with col_r:
    if not src_df.empty:
        top10 = src_df.sort_values("TVL", ascending=False).head(10).sort_values("TVL")
        fig = go.Figure(go.Bar(
            x=top10["TVL"], y=top10["Protocol"], orientation="h",
            marker_color=ACCENT, text=[fmt_usd(v) for v in top10["TVL"]],
            textposition="outside"
        ))
        fig.update_layout(title="Top 10 Protocols by TVL", height=420,
                          margin=dict(l=10, r=40, t=50, b=10),
                          xaxis_title="TVL (USD)", yaxis_title=None)
        show_chart(fig)
    else:
        st.info("Protocol-level data is unavailable right now.")

st.markdown("---")

# ============================================================
# --- Latest blocks ---
# ============================================================
st.subheader("Latest Blocks")
if not blocks_df.empty:
    disp = blocks_df.copy()
    disp["Gas Used"] = disp["Gas Used"].apply(fmt_num)
    show_table(disp)
    st.caption("Latest blocks from Blockscout (cached for ~15 seconds; use the sidebar button to refresh).")
else:
    st.info("Latest blocks are unavailable right now.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| Network KPIs | ETH price, total transactions/addresses/blocks, block time, gas price, utilization | [Blockscout – Base](https://base.blockscout.com) · REST API `/api/v2/stats` |
| Daily Transactions | Transactions per day | [Blockscout – Base](https://base.blockscout.com) · `/api/v2/stats/charts/transactions` |
| Latest Blocks | Height, time, txs, gas used, base fee | [Blockscout – Base](https://base.blockscout.com) · `/api/v2/blocks` |
| TVL, rank, dominance, ATH | Historical chain TVL and all-chains TVL | [DefiLlama](https://defillama.com/chain/Base) · `api.llama.fi` |
| TVL by category, top protocols | Protocol-level TVL on Base | [DefiLlama](https://defillama.com/chains) · `/protocols` |
| DEX volume | Daily and 24h/7d DEX volume on Base | [DefiLlama DEX Volumes](https://defillama.com/dexs/chain/base) |
| Chain fees | Daily fees paid on Base | [DefiLlama Fees](https://defillama.com/fees/chain/base) |
| Stablecoins | Circulating stablecoin supply on Base | [DefiLlama Stablecoins](https://defillama.com/stablecoins/Base) |
"""
)
st.caption(
    "Notes: TVL by DefiLlama's methodology excludes some categories (Liquid Staking, Bridge, "
    "Onchain Capital Allocator, Risk Curators) from the headline chain total to avoid double counting. "
    "Today's partial day is removed from the daily transactions chart. "
    "Third-party APIs may change limits or availability at any time."
)

if errors:
    with st.expander("⚠️ Data warnings"):
        for e in errors:
            st.write(f"- {e}")

st.markdown(
    f"""
<div style="margin-top:25px; font-size:13px; color:gray;">
Last refreshed: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
</div>
""",
    unsafe_allow_html=True
)
