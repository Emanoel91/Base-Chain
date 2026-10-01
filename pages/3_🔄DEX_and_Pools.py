import time
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, BLUE_SPECTRUM, show_chart, show_table, page_header, sidebar_controls,
    safe_call, fmt_usd, fmt_num, fmt_pct, safe_float,
)

st.set_page_config(page_title="Base Chain - DEX & Pools", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — DEX & Pools",
    "DEX trading on <b>Base</b>: volume and market share by DEX, the biggest liquidity pools, "
    "trending and newly created pools, plus a pool analyzer with price chart and recent trades. "
    "DEX-level numbers come from DefiLlama, pool-level numbers from GeckoTerminal. "
    "See the <b>Sources</b> section at the bottom."
)

DOWN_COLOR = "#ef4444"
GT = "https://api.geckoterminal.com/api/v2"
NETWORK = "base"


# ============================================================
# --- Fetchers: GeckoTerminal (pool level) ---
# ============================================================
def gt_get(path: str, params: dict | None = None) -> dict:
    headers = {"Accept": "application/json;version=20230302"}
    for attempt in range(3):
        r = requests.get(GT + path, params=params, headers=headers, timeout=30)
        if r.status_code == 429:  # free tier is rate limited
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("GeckoTerminal rate limit reached (HTTP 429). Wait a minute and refresh.")


def parse_pools(j: dict) -> pd.DataFrame:
    data = j.get("data", [])
    if isinstance(data, dict):
        data = [data]
    inc = {(i.get("type"), i.get("id")): (i.get("attributes") or {}) for i in j.get("included", [])}
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for p in data:
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}

        def rid(key):
            return ((rel.get(key) or {}).get("data") or {}).get("id")

        dex_id = rid("dex")
        dex = (inc.get(("dex", dex_id)) or {}).get("name") or dex_id or "unknown"
        base_tok = inc.get(("token", rid("base_token"))) or {}
        vol, chg = a.get("volume_usd") or {}, a.get("price_change_percentage") or {}
        t24 = (a.get("transactions") or {}).get("h24") or {}
        buys, sells = t24.get("buys"), t24.get("sells")
        created = pd.to_datetime(a.get("pool_created_at"), utc=True, errors="coerce")
        rows.append({
            "Pool": a.get("name"),
            "Address": a.get("address"),
            "DEX": dex,
            "Token": base_tok.get("symbol"),
            "Price USD": safe_float(a.get("base_token_price_usd")),
            "Liquidity": safe_float(a.get("reserve_in_usd")),
            "FDV": safe_float(a.get("fdv_usd")),
            "Mcap": safe_float(a.get("market_cap_usd")),
            "Vol 5m": safe_float(vol.get("m5")), "Vol 1h": safe_float(vol.get("h1")),
            "Vol 6h": safe_float(vol.get("h6")), "Vol 24h": safe_float(vol.get("h24")),
            "Chg 5m": safe_float(chg.get("m5")), "Chg 1h": safe_float(chg.get("h1")),
            "Chg 6h": safe_float(chg.get("h6")), "Chg 24h": safe_float(chg.get("h24")),
            "Buys 24h": buys, "Sells 24h": sells,
            "Txs 24h": (buys or 0) + (sells or 0) if (buys is not None or sells is not None) else None,
            "Buyers 24h": t24.get("buyers"), "Sellers 24h": t24.get("sellers"),
            "Age (h)": (now - created).total_seconds() / 3600 if pd.notna(created) else None,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Vol/Liq"] = df.apply(
            lambda r: r["Vol 24h"] / r["Liquidity"] if r["Vol 24h"] is not None and r["Liquidity"] else None,
            axis=1)
    return df


INCLUDE = "base_token,quote_token,dex"


@st.cache_data(ttl=300, show_spinner=False)
def get_top_pools(pages: int) -> pd.DataFrame:
    frames = []
    for pg in range(1, pages + 1):
        j = gt_get(f"/networks/{NETWORK}/pools",
                   {"page": pg, "include": INCLUDE, "sort": "h24_volume_usd_desc",
                    "order": "h24_volume_usd_desc"})
        frames.append(parse_pools(j))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=300, show_spinner=False)
def get_trending_pools(duration: str) -> pd.DataFrame:
    j = gt_get(f"/networks/{NETWORK}/trending_pools", {"include": INCLUDE, "duration": duration})
    return parse_pools(j)


@st.cache_data(ttl=120, show_spinner=False)
def get_new_pools(pages: int) -> pd.DataFrame:
    frames = [parse_pools(gt_get(f"/networks/{NETWORK}/new_pools", {"page": pg, "include": INCLUDE}))
              for pg in range(1, pages + 1)]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


@st.cache_data(ttl=120, show_spinner=False)
def get_pool(address: str) -> pd.DataFrame:
    return parse_pools(gt_get(f"/networks/{NETWORK}/pools/{address}", {"include": INCLUDE}))


@st.cache_data(ttl=120, show_spinner=False)
def get_ohlcv(address: str, timeframe: str, aggregate: int, limit: int) -> pd.DataFrame:
    j = gt_get(f"/networks/{NETWORK}/pools/{address}/ohlcv/{timeframe}",
               {"aggregate": aggregate, "limit": limit, "currency": "usd"})
    rows = (((j.get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    return df.sort_values("date").reset_index(drop=True)


@st.cache_data(ttl=60, show_spinner=False)
def get_trades(address: str) -> pd.DataFrame:
    j = gt_get(f"/networks/{NETWORK}/pools/{address}/trades")
    rows = []
    for t in j.get("data", []):
        a = t.get("attributes") or {}
        rows.append({
            "Time (UTC)": pd.to_datetime(a.get("block_timestamp"), utc=True, errors="coerce"),
            "Side": (a.get("kind") or "").capitalize(),
            "Volume (USD)": safe_float(a.get("volume_in_usd")),
            "Wallet": a.get("tx_from_address"),
            "Tx": a.get("tx_hash"),
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=120, show_spinner=False)
def search_pools(query: str) -> pd.DataFrame:
    j = gt_get("/search/pools", {"query": query, "network": NETWORK, "include": INCLUDE})
    return parse_pools(j)


# ============================================================
# --- Fetchers: DefiLlama (DEX level) ---
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_dex_overview() -> dict:
    r = requests.get("https://api.llama.fi/overview/dexs/Base", params={
        "excludeTotalDataChart": "false",
        "excludeTotalDataChartBreakdown": "false",
    }, timeout=60)
    r.raise_for_status()
    j = r.json()

    prot = pd.DataFrame(j.get("protocols") or [])
    if not prot.empty:
        prot["Name"] = prot["displayName"] if "displayName" in prot.columns else prot.get("name")
        for c in ["total24h", "total7d", "total30d", "change_1d", "change_7d", "change_1m"]:
            if c not in prot.columns:
                prot[c] = None
            prot[c] = pd.to_numeric(prot[c], errors="coerce")
        if "category" not in prot.columns:
            prot["category"] = None

    rows = []
    for item in j.get("totalDataChartBreakdown") or []:
        ts, d = item[0], item[1]
        rec = {"date": pd.to_datetime(ts, unit="s")}
        rec.update({k: v for k, v in (d or {}).items()})
        rows.append(rec)
    brk = pd.DataFrame(rows)
    if not brk.empty:
        brk = brk.sort_values("date").set_index("date").apply(pd.to_numeric, errors="coerce").fillna(0)

    return {
        "total24h": j.get("total24h"), "total7d": j.get("total7d"), "total30d": j.get("total30d"),
        "change_1d": j.get("change_1d"), "change_7d": j.get("change_7d"), "change_1m": j.get("change_1m"),
        "protocols": prot, "breakdown": brk,
    }


# ============================================================
# --- Load data ---
# ============================================================
col_a, col_b = st.columns([1, 3])
with col_a:
    pool_count = st.selectbox("Pools to load (top by 24h volume)", [20, 60, 100], index=2)

with st.spinner("Loading DEX and pool data..."):
    dex = sc(get_dex_overview, default={}, label="DefiLlama DEX volumes") or {}
    top_df = sc(get_top_pools, pool_count // 20, default=pd.DataFrame(), label="GeckoTerminal top pools")

prot_df = dex.get("protocols", pd.DataFrame()) if dex else pd.DataFrame()
brk_df = dex.get("breakdown", pd.DataFrame()) if dex else pd.DataFrame()
if top_df is None:
    top_df = pd.DataFrame()

# ============================================================
# --- KPIs ---
# ============================================================
st.markdown("**DEX activity (all DEXes on Base)**")
k1, k2, k3, k4 = st.columns(4)
k1.metric("DEX Volume (24h)", fmt_usd(dex.get("total24h")) if dex else "N/A",
          fmt_pct(dex.get("change_1d")) if dex and dex.get("change_1d") is not None else None)
k2.metric("DEX Volume (7d)", fmt_usd(dex.get("total7d")) if dex else "N/A",
          fmt_pct(dex.get("change_7d")) if dex and dex.get("change_7d") is not None else None)
k3.metric("DEX Volume (30d)", fmt_usd(dex.get("total30d")) if dex else "N/A",
          fmt_pct(dex.get("change_1m")) if dex and dex.get("change_1m") is not None else None)

top_dex_name, top_dex_share = "N/A", None
active_dexes = None
if not prot_df.empty and prot_df["total24h"].notna().any():
    tot = prot_df["total24h"].sum()
    best = prot_df.sort_values("total24h", ascending=False).iloc[0]
    top_dex_name = best["Name"]
    top_dex_share = best["total24h"] / tot * 100 if tot else None
    active_dexes = int((prot_df["total24h"] > 0).sum())
k4.metric("Top DEX (24h)", top_dex_name,
          f"{top_dex_share:.1f}% share" if top_dex_share is not None else None, delta_color="off")

st.markdown(f"**Pools (top {len(top_df) if not top_df.empty else 0} by 24h volume, GeckoTerminal)**")
p1, p2, p3, p4 = st.columns(4)
if not top_df.empty:
    buys, sells = top_df["Buys 24h"].fillna(0).sum(), top_df["Sells 24h"].fillna(0).sum()
    p1.metric("Liquidity in These Pools", fmt_usd(top_df["Liquidity"].sum()))
    p2.metric("24h Volume in These Pools", fmt_usd(top_df["Vol 24h"].sum()))
    p3.metric("24h Transactions", fmt_num(top_df["Txs 24h"].fillna(0).sum()))
    p4.metric("Buy Share (24h txs)", f"{buys / (buys + sells) * 100:.1f}%" if (buys + sells) else "N/A")
else:
    p1.metric("Liquidity in These Pools", "N/A")
    p2.metric("24h Volume in These Pools", "N/A")
    p3.metric("24h Transactions", "N/A")
    p4.metric("Buy Share (24h txs)", "N/A")
if active_dexes is not None:
    st.caption(f"{active_dexes} DEX protocols had volume on Base in the last 24h (DefiLlama).")

st.markdown("---")

# ============================================================
# --- Section 1: DEX market share ---
# ============================================================
st.subheader("DEX Volume & Market Share")

if not prot_df.empty:
    period = st.radio("Period", ["24h", "7d", "30d"], horizontal=True, key="share_period")
    pcol = {"24h": "total24h", "7d": "total7d", "30d": "total30d"}[period]
    share_df = prot_df[["Name", "category", pcol]].dropna(subset=[pcol])
    share_df = share_df[share_df[pcol] > 0].sort_values(pcol, ascending=False)

    top_n = share_df.head(8).copy()
    others = share_df.iloc[8:][pcol].sum()
    if others > 0:
        top_n = pd.concat([top_n, pd.DataFrame([{"Name": "Others", "category": None, pcol: others}])],
                          ignore_index=True)

    cl, cr = st.columns(2)
    with cl:
        fig = px.pie(top_n, names="Name", values=pcol, hole=0.5,
                     color_discrete_sequence=BLUE_SPECTRUM, title=f"DEX Market Share ({period} volume)")
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
        show_chart(fig)
    with cr:
        bar = share_df.head(10).sort_values(pcol)
        fig = go.Figure(go.Bar(x=bar[pcol], y=bar["Name"], orientation="h", marker_color=ACCENT,
                               text=[fmt_usd(v) for v in bar[pcol]], textposition="outside"))
        fig.update_layout(title=f"Top 10 DEXes by {period} Volume", height=420,
                          margin=dict(l=10, r=60, t=50, b=10), xaxis_title="Volume (USD)",
                          yaxis_title=None, plot_bgcolor="white")
        show_chart(fig)

    tbl = prot_df.copy()
    tot24 = tbl["total24h"].sum()
    tbl["Share 24h (%)"] = tbl["total24h"] / tot24 * 100 if tot24 else None
    tbl = tbl.sort_values("total24h", ascending=False)[
        ["Name", "category", "total24h", "total7d", "total30d", "change_1d", "change_7d", "change_1m", "Share 24h (%)"]
    ].rename(columns={"category": "Category", "total24h": "Volume 24h", "total7d": "Volume 7d",
                      "total30d": "Volume 30d", "change_1d": "Change 1d (%)",
                      "change_7d": "Change 7d (%)", "change_1m": "Change 30d (%)"})
    C = st.column_config
    show_table(tbl, column_config={
        "Volume 24h": C.NumberColumn(format="$%.0f"), "Volume 7d": C.NumberColumn(format="$%.0f"),
        "Volume 30d": C.NumberColumn(format="$%.0f"),
        "Change 1d (%)": C.NumberColumn(format="%.2f%%"), "Change 7d (%)": C.NumberColumn(format="%.2f%%"),
        "Change 30d (%)": C.NumberColumn(format="%.2f%%"), "Share 24h (%)": C.NumberColumn(format="%.2f%%"),
    })
else:
    st.info("DEX protocol data is unavailable right now.")

# Daily volume by DEX (stacked)
if not brk_df.empty:
    range_map = {"30D": 30, "90D": 90, "180D": 180, "1Y": 365, "All": None}
    rc = st.radio("Range", list(range_map.keys()), horizontal=True, index=1, key="brk_range")
    d = range_map[rc]
    b = brk_df if d is None else brk_df[brk_df.index >= brk_df.index.max() - timedelta(days=d)]
    ranking = b.sum().sort_values(ascending=False)
    keep = list(ranking.head(8).index)
    plot = b[keep].copy()
    rest = [c for c in b.columns if c not in keep]
    if rest:
        plot["Others"] = b[rest].sum(axis=1)
    fig = go.Figure()
    for i, col in enumerate(plot.columns):
        fig.add_trace(go.Bar(x=plot.index, y=plot[col], name=col,
                             marker_color=BLUE_SPECTRUM[i % len(BLUE_SPECTRUM)]))
    fig.update_layout(barmode="stack", title="Daily DEX Volume by DEX", height=420,
                      margin=dict(l=10, r=10, t=50, b=10), yaxis_title="Volume (USD)",
                      hovermode="x unified", plot_bgcolor="white",
                      legend=dict(orientation="h", y=-0.15))
    show_chart(fig)

st.markdown("---")

# ============================================================
# --- Section 2: Top pools ---
# ============================================================
st.subheader("Top Pools")


def short(addr):
    return f"{addr[:8]}…{addr[-6:]}" if isinstance(addr, str) and len(addr) > 16 else addr


def age_text(h):
    if h is None or pd.isna(h):
        return "N/A"
    if h < 1:
        return f"{h * 60:.0f}m"
    if h < 48:
        return f"{h:.1f}h"
    return f"{h / 24:.1f}d"


def price_text(p):
    if p is None or pd.isna(p):
        return "N/A"
    return f"${p:,.2f}" if p >= 1 else f"${p:.8g}"


def pool_table(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["Price"] = out["Price USD"].apply(price_text)
    out["Age"] = out["Age (h)"].apply(age_text)
    out["Address"] = out["Address"].apply(lambda a: a)  # keep full address (copyable)
    return out[["Pool", "DEX", "Price", "Liquidity", "Vol 24h", "Vol/Liq", "Chg 1h", "Chg 24h",
                "Txs 24h", "Buys 24h", "Sells 24h", "FDV", "Age", "Address"]]


def pool_cfg(cols):
    C = st.column_config
    cfg = {
        "Liquidity": C.NumberColumn(format="$%.0f"), "Vol 24h": C.NumberColumn("Volume 24h", format="$%.0f"),
        "Vol/Liq": C.NumberColumn("Vol/Liq (24h)", format="%.2f"),
        "Chg 1h": C.NumberColumn("Change 1h", format="%.2f%%"), "Chg 24h": C.NumberColumn("Change 24h", format="%.2f%%"),
        "Txs 24h": C.NumberColumn("Txs 24h", format="%d"), "Buys 24h": C.NumberColumn("Buys 24h", format="%d"),
        "Sells 24h": C.NumberColumn("Sells 24h", format="%d"), "FDV": C.NumberColumn(format="$%.0f"),
    }
    return {k: v for k, v in cfg.items() if k in cols}


if not top_df.empty:
    f1, f2, f3, f4 = st.columns([2, 2, 3, 3])
    with f1:
        sort_by = st.selectbox("Sort by", ["Vol 24h", "Liquidity", "Txs 24h", "Vol/Liq", "Chg 24h"],
                               format_func=lambda x: {"Vol 24h": "24h Volume", "Liquidity": "Liquidity",
                                                      "Txs 24h": "24h Transactions", "Vol/Liq": "Volume / Liquidity",
                                                      "Chg 24h": "24h Price Change"}[x])
    with f2:
        min_liq = st.number_input("Min liquidity (USD)", min_value=0, value=10000, step=1000)
    with f3:
        dex_opts = sorted(top_df["DEX"].dropna().unique().tolist())
        dex_sel = st.multiselect("DEX filter (empty = all)", dex_opts)
    with f4:
        q = st.text_input("Search pool / token", "")

    fdf = top_df[top_df["Liquidity"].fillna(0) >= min_liq].copy()
    if dex_sel:
        fdf = fdf[fdf["DEX"].isin(dex_sel)]
    if q:
        fdf = fdf[fdf["Pool"].str.contains(q, case=False, na=False)]
    fdf = fdf.sort_values(sort_by, ascending=False, na_position="last")

    if fdf.empty:
        st.info("No pools match these filters.")
    else:
        cl, cr = st.columns(2)
        with cl:
            bar = fdf.head(15).sort_values(sort_by)
            fig = go.Figure(go.Bar(x=bar[sort_by], y=bar["Pool"], orientation="h", marker_color=ACCENT))
            fig.update_layout(title=f"Top 15 Pools by {sort_by}", height=480,
                              margin=dict(l=10, r=20, t=50, b=10), yaxis_title=None, plot_bgcolor="white")
            show_chart(fig)
        with cr:
            sc_df = fdf[(fdf["Liquidity"] > 0) & (fdf["Vol 24h"] > 0)].copy()
            if not sc_df.empty:
                sc_df["Txs"] = sc_df["Txs 24h"].fillna(1).clip(lower=1)
                fig = px.scatter(sc_df, x="Liquidity", y="Vol 24h", size="Txs", color="DEX",
                                 hover_name="Pool", log_x=True, log_y=True, size_max=36,
                                 color_discrete_sequence=BLUE_SPECTRUM[:7],
                                 title="Liquidity vs 24h Volume (bubble = 24h transactions)")
                fig.update_layout(height=480, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white")
                show_chart(fig)

        liq_by_dex = fdf.groupby("DEX", as_index=False)["Liquidity"].sum().sort_values("Liquidity", ascending=False)
        c1, c2 = st.columns(2)
        with c1:
            fig = px.pie(liq_by_dex, names="DEX", values="Liquidity", hole=0.5,
                         color_discrete_sequence=BLUE_SPECTRUM, title="Liquidity by DEX (filtered pools)")
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
            show_chart(fig)
        with c2:
            vol_by_dex = fdf.groupby("DEX", as_index=False)["Vol 24h"].sum().sort_values("Vol 24h", ascending=False)
            fig = px.pie(vol_by_dex, names="DEX", values="Vol 24h", hole=0.5,
                         color_discrete_sequence=BLUE_SPECTRUM, title="24h Volume by DEX (filtered pools)")
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
            show_chart(fig)

        tbl = pool_table(fdf)
        show_table(tbl, column_config=pool_cfg(tbl.columns))
        st.caption(f"{len(tbl)} pools shown. High volume relative to liquidity (Vol/Liq) can reflect wash "
                   "trading or bots — treat extreme values with caution.")
else:
    st.info("Top pools are unavailable right now (GeckoTerminal may be rate limiting — try again in a minute).")

st.markdown("---")

# ============================================================
# --- Section 3: Trending & new pools ---
# ============================================================
st.subheader("Trending & New Pools")
tab_trend, tab_new = st.tabs(["🔥 Trending", "🆕 New Pools"])

with tab_trend:
    dur = st.radio("Trending window", ["5m", "1h", "6h", "24h"], horizontal=True, index=3, key="trend_dur")
    tdf = sc(get_trending_pools, dur, default=pd.DataFrame(), label="GeckoTerminal trending pools")
    if tdf is not None and not tdf.empty:
        t = pool_table(tdf)
        show_table(t, column_config=pool_cfg(t.columns))
    else:
        st.info("Trending pools are unavailable right now.")

with tab_new:
    n1, n2 = st.columns([1, 1])
    with n1:
        new_liq = st.number_input("Min liquidity (USD)", min_value=0, value=1000, step=500, key="new_liq")
    with n2:
        new_pages = st.selectbox("Pools to load", [20, 40], index=1, key="new_pages")
    ndf = sc(get_new_pools, new_pages // 20, default=pd.DataFrame(), label="GeckoTerminal new pools")
    if ndf is not None and not ndf.empty:
        ndf = ndf[ndf["Liquidity"].fillna(0) >= new_liq]
        if ndf.empty:
            st.info("No new pools above the liquidity threshold.")
        else:
            t = pool_table(ndf.sort_values("Age (h)"))
            show_table(t, column_config=pool_cfg(t.columns))
            st.caption("New pools are unvetted and often illiquid or malicious. Always verify a token before trading.")
    else:
        st.info("New pools are unavailable right now.")

st.markdown("---")

# ============================================================
# --- Section 4: Pool analyzer ---
# ============================================================
st.subheader("Pool Analyzer")

options = {}
if not top_df.empty:
    for _, r in top_df.iterrows():
        options[f"{r['Pool']} · {r['DEX']} · {short(r['Address'])}"] = r["Address"]
MANUAL = "✏️ Enter a pool address manually"
choice = st.selectbox("Choose a pool", list(options.keys()) + [MANUAL])
address = None
if choice == MANUAL:
    manual = st.text_input("Pool address (0x…)", "")
    address = manual.strip() or None
else:
    address = options[choice]

if address:
    pdf_ = sc(get_pool, address, default=pd.DataFrame(), label="GeckoTerminal pool")
    if pdf_ is not None and not pdf_.empty:
        r = pdf_.iloc[0]
        st.markdown(f"**{r['Pool']}** on {r['DEX']}  ·  `{address}`")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Price", price_text(r["Price USD"]), fmt_pct(r["Chg 24h"]) if pd.notna(r["Chg 24h"]) else None)
        m2.metric("Liquidity", fmt_usd(r["Liquidity"]))
        m3.metric("Volume 24h", fmt_usd(r["Vol 24h"]))
        m4.metric("FDV", fmt_usd(r["FDV"]))
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Volume 1h", fmt_usd(r["Vol 1h"]), fmt_pct(r["Chg 1h"]) if pd.notna(r["Chg 1h"]) else None)
        m6.metric("Txs 24h", fmt_num(r["Txs 24h"]))
        m7.metric("Buys / Sells (24h)", f"{fmt_num(r['Buys 24h'])} / {fmt_num(r['Sells 24h'])}")
        m8.metric("Pool Age", age_text(r["Age (h)"]))

    tf_map = {
        "Daily": ("day", 1, 180), "4 hours": ("hour", 4, 200), "1 hour": ("hour", 1, 200),
        "15 minutes": ("minute", 15, 200), "5 minutes": ("minute", 5, 200),
    }
    tf_label = st.radio("Timeframe", list(tf_map.keys()), horizontal=True, index=2)
    tf, agg, lim = tf_map[tf_label]
    ohlc = sc(get_ohlcv, address, tf, agg, lim, default=pd.DataFrame(), label="GeckoTerminal OHLCV")
    if ohlc is not None and not ohlc.empty:
        fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
        fig.add_trace(go.Candlestick(
            x=ohlc["date"], open=ohlc["open"], high=ohlc["high"], low=ohlc["low"], close=ohlc["close"],
            increasing_line_color=ACCENT, increasing_fillcolor=ACCENT,
            decreasing_line_color=DOWN_COLOR, decreasing_fillcolor=DOWN_COLOR, name="Price"), row=1, col=1)
        fig.add_trace(go.Bar(x=ohlc["date"], y=ohlc["volume"], marker_color="#8c8cff", name="Volume"), row=2, col=1)
        fig.update_layout(title=f"Price & Volume ({tf_label})", height=560, margin=dict(l=10, r=10, t=50, b=10),
                          xaxis_rangeslider_visible=False, showlegend=False, plot_bgcolor="white")
        fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
        fig.update_yaxes(title_text="Volume (USD)", row=2, col=1)
        show_chart(fig)
    else:
        st.info("No price history returned for this pool and timeframe.")

    trades = sc(get_trades, address, default=pd.DataFrame(), label="GeckoTerminal trades")
    if trades is not None and not trades.empty:
        st.markdown("**Recent trades**")
        g = trades.groupby("Side", as_index=False).agg(Trades=("Side", "size"), Volume=("Volume (USD)", "sum"))
        cc1, cc2 = st.columns([1, 2])
        with cc1:
            fig = go.Figure(go.Bar(x=g["Side"], y=g["Volume"], marker_color=[ACCENT if s == "Buy" else DOWN_COLOR for s in g["Side"]],
                                   text=[fmt_usd(v) for v in g["Volume"]], textposition="outside"))
            fig.update_layout(title="Buy vs Sell Volume (recent trades)", height=340,
                              margin=dict(l=10, r=10, t=50, b=10), yaxis_title="USD", plot_bgcolor="white")
            show_chart(fig)
        with cc2:
            disp = trades.copy()
            disp["Time (UTC)"] = disp["Time (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S")
            disp["Wallet"] = disp["Wallet"].apply(short)
            disp["Tx"] = disp["Tx"].apply(short)
            show_table(disp.head(30), column_config={"Volume (USD)": st.column_config.NumberColumn(format="$%.2f")})
    else:
        st.caption("No recent trades returned for this pool.")

st.markdown("---")

# ============================================================
# --- Section 5: Search ---
# ============================================================
st.subheader("Search Pools on Base")
query = st.text_input("Search by token name, symbol or address", "", key="pool_search")
if query.strip():
    sdf = sc(search_pools, query.strip(), default=pd.DataFrame(), label="GeckoTerminal search")
    if sdf is not None and not sdf.empty:
        t = pool_table(sdf)
        show_table(t, column_config=pool_cfg(t.columns))
        st.caption("Copy a pool address from the table and paste it into the Pool Analyzer above.")
    else:
        st.info("No pools found.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| DEX KPIs, market share, daily volume by DEX | 24h/7d/30d DEX volume, per-DEX volume and changes | [DefiLlama DEX Volumes – Base](https://defillama.com/dexs/chain/base) · `api.llama.fi/overview/dexs/Base` |
| Top, trending and new pools | Liquidity, volume, price change, transactions, age, FDV | [GeckoTerminal – Base](https://www.geckoterminal.com/base/pools) · API v2 `/networks/base/pools`, `/trending_pools`, `/new_pools` · [docs](https://apiguide.geckoterminal.com) |
| Pool analyzer | Pool details, OHLCV candles, recent trades | GeckoTerminal API v2 · `/networks/base/pools/{address}`, `/ohlcv/{timeframe}`, `/trades` |
| Search | Pools by token name, symbol or address | GeckoTerminal API v2 · `/search/pools` |
| Derived metrics | Volume/Liquidity, buy share, liquidity & volume by DEX, market share % | Calculated in this app |
"""
)
st.caption(
    "Notes: pool metrics cover only the pools loaded (top by 24h volume), not every pool on Base, so they are "
    "not equal to DefiLlama's chain-wide DEX volume. GeckoTerminal's free API is rate limited, so results are "
    "cached for a few minutes. Not financial advice. Third-party APIs may change limits or availability."
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
