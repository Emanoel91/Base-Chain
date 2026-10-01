import time
import requests
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
from datetime import datetime, timezone

from common import (
    ACCENT, BLUE_SPECTRUM, BLOCKSCOUT_KEY,
    bs_request, safe_call, show_chart, show_table, page_header, sidebar_controls,
    fmt_usd, fmt_num, fmt_pct, safe_float,
)

st.set_page_config(page_title="Base Chain - Tokens", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Tokens",
    "ERC-20 tokens on <b>Base</b>: a token leaderboard (market cap, holders, volume) and a token analyzer with "
    "market data, liquidity pools, price chart, holder distribution and recent transfers. "
    "On-chain token data comes from Blockscout, market and pool data from GeckoTerminal. "
    "See the <b>Sources</b> section at the bottom."
)

DOWN_COLOR = "#ef4444"
GT = "https://api.geckoterminal.com/api/v2"
NETWORK = "base"


# ============================================================
# --- Helpers ---
# ============================================================
def short(addr):
    return f"{addr[:8]}…{addr[-6:]}" if isinstance(addr, str) and len(addr) > 16 else addr


def price_text(p):
    if p is None or pd.isna(p):
        return "N/A"
    return f"${p:,.2f}" if p >= 1 else f"${p:.8g}"


def to_int(x, default=None):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


def scaled(raw, decimals):
    v = safe_float(raw)
    if v is None:
        return None
    try:
        return v / (10 ** int(decimals if decimals is not None else 18))
    except (TypeError, ValueError):
        return None


def age_text(h):
    if h is None or pd.isna(h):
        return "N/A"
    if h < 1:
        return f"{h * 60:.0f}m"
    if h < 48:
        return f"{h:.1f}h"
    return f"{h / 24:.1f}d"


# ============================================================
# --- Fetchers: Blockscout ---
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def get_token_list(sort: str, q: str, pages: int) -> pd.DataFrame:
    base = {"type": "ERC-20", "sort": sort, "order": "desc"}
    if q:
        base["q"] = q
    params, rows = dict(base), []
    for _ in range(pages):
        j = bs_request("/api/v2/tokens", params)
        for t in j.get("items", []):
            dec = to_int(t.get("decimals"), 18)
            supply = scaled(t.get("total_supply"), dec)
            price = safe_float(t.get("exchange_rate"))
            rows.append({
                "Token": t.get("name"),
                "Symbol": t.get("symbol"),
                "Address": t.get("address_hash") or t.get("address"),
                "Price USD": price,
                "Mcap": safe_float(t.get("circulating_market_cap")),
                "Vol 24h": safe_float(t.get("volume_24h")),
                "Holders": to_int(t.get("holders_count") or t.get("holders")),
                "Supply": supply,
                "FDV (est.)": price * supply if price is not None and supply is not None else None,
                "Decimals": dec,
            })
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = {**base, **nxt}
    df = pd.DataFrame(rows)
    if not df.empty:
        df["Vol/Mcap"] = df.apply(
            lambda r: r["Vol 24h"] / r["Mcap"] if r["Vol 24h"] is not None and r["Mcap"] else None, axis=1)
    return df


@st.cache_data(ttl=300, show_spinner=False)
def get_token_details(addr: str) -> dict:
    t = bs_request(f"/api/v2/tokens/{addr}")
    try:
        c = bs_request(f"/api/v2/tokens/{addr}/counters")
    except Exception:
        c = {}
    dec = to_int(t.get("decimals"), 18)
    return {
        "name": t.get("name"), "symbol": t.get("symbol"), "type": t.get("type"), "decimals": dec,
        "supply": scaled(t.get("total_supply"), dec),
        "holders": to_int(t.get("holders_count") or t.get("holders") or c.get("token_holders_count")),
        "transfers": to_int(c.get("transfers_count")),
        "price": safe_float(t.get("exchange_rate")),
        "mcap": safe_float(t.get("circulating_market_cap")),
        "vol24": safe_float(t.get("volume_24h")),
        "icon": t.get("icon_url"),
    }


@st.cache_data(ttl=300, show_spinner=False)
def get_holders(addr: str, decimals: int, pages: int) -> pd.DataFrame:
    params, rows = {}, []
    for _ in range(pages):
        j = bs_request(f"/api/v2/tokens/{addr}/holders", params)
        for h in j.get("items", []):
            a = h.get("address") or {}
            rows.append({
                "Holder": a.get("hash"),
                "Label": a.get("name") or a.get("ens_domain_name") or "",
                "Type": "Contract" if a.get("is_contract") else "Wallet",
                "Balance": scaled(h.get("value"), decimals),
            })
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = nxt
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def get_transfers(addr: str, decimals: int, pages: int) -> pd.DataFrame:
    params, rows = {}, []
    for _ in range(pages):
        j = bs_request(f"/api/v2/tokens/{addr}/transfers", params)
        for t in j.get("items", []):
            fr, to = t.get("from") or {}, t.get("to") or {}
            tot = t.get("total") or {}
            rows.append({
                "Time (UTC)": pd.to_datetime(t.get("timestamp"), utc=True, errors="coerce"),
                "Type": (t.get("type") or "").replace("token_", "").capitalize(),
                "From": fr.get("hash"), "From Label": fr.get("name") or "",
                "To": to.get("hash"), "To Label": to.get("name") or "",
                "Amount": scaled(tot.get("value"), tot.get("decimals") if tot.get("decimals") is not None else decimals),
                "Tx": t.get("transaction_hash") or t.get("tx_hash"),
            })
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = nxt
    return pd.DataFrame(rows)


# ============================================================
# --- Fetchers: GeckoTerminal ---
# ============================================================
def gt_get(path: str, params: dict | None = None) -> dict:
    headers = {"Accept": "application/json;version=20230302"}
    for attempt in range(3):
        r = requests.get(GT + path, params=params, headers=headers, timeout=30)
        if r.status_code == 429:
            time.sleep(2 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("GeckoTerminal rate limit reached (HTTP 429). Wait a minute and refresh.")


@st.cache_data(ttl=120, show_spinner=False)
def get_gt_token(addr: str) -> dict:
    j = gt_get(f"/networks/{NETWORK}/tokens/{addr}")
    a = ((j.get("data") or {}).get("attributes")) or {}
    vol = a.get("volume_usd") or {}
    return {
        "price": safe_float(a.get("price_usd")), "fdv": safe_float(a.get("fdv_usd")),
        "mcap": safe_float(a.get("market_cap_usd")), "reserve": safe_float(a.get("total_reserve_in_usd")),
        "vol24": safe_float(vol.get("h24")),
    }


@st.cache_data(ttl=120, show_spinner=False)
def get_gt_token_pools(addr: str) -> pd.DataFrame:
    j = gt_get(f"/networks/{NETWORK}/tokens/{addr}/pools",
               {"include": "base_token,quote_token,dex", "sort": "h24_volume_usd_desc"})
    inc = {(i.get("type"), i.get("id")): (i.get("attributes") or {}) for i in j.get("included", [])}
    now = pd.Timestamp.now(tz="UTC")
    rows = []
    for p in j.get("data", []):
        a = p.get("attributes") or {}
        rel = p.get("relationships") or {}
        dex_id = ((rel.get("dex") or {}).get("data") or {}).get("id")
        t24 = (a.get("transactions") or {}).get("h24") or {}
        created = pd.to_datetime(a.get("pool_created_at"), utc=True, errors="coerce")
        chg = a.get("price_change_percentage") or {}
        rows.append({
            "Pool": a.get("name"), "Address": a.get("address"),
            "DEX": (inc.get(("dex", dex_id)) or {}).get("name") or dex_id or "unknown",
            "Price USD": safe_float(a.get("base_token_price_usd")),
            "Liquidity": safe_float(a.get("reserve_in_usd")),
            "Vol 24h": safe_float((a.get("volume_usd") or {}).get("h24")),
            "Chg 24h": safe_float(chg.get("h24")),
            "Txs 24h": (t24.get("buys") or 0) + (t24.get("sells") or 0),
            "Age (h)": (now - created).total_seconds() / 3600 if pd.notna(created) else None,
        })
    return pd.DataFrame(rows)


@st.cache_data(ttl=120, show_spinner=False)
def get_ohlcv(pool: str, timeframe: str, aggregate: int, limit: int) -> pd.DataFrame:
    j = gt_get(f"/networks/{NETWORK}/pools/{pool}/ohlcv/{timeframe}",
               {"aggregate": aggregate, "limit": limit, "currency": "usd"})
    rows = (((j.get("data") or {}).get("attributes") or {}).get("ohlcv_list")) or []
    df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
    if df.empty:
        return df
    df["date"] = pd.to_datetime(df["ts"], unit="s")
    return df.sort_values("date").reset_index(drop=True)


# ============================================================
# --- Section 1: Token leaderboard ---
# ============================================================
st.subheader("Token Leaderboard")
if not BLOCKSCOUT_KEY:
    st.caption("Tip: Blockscout is moving per-instance endpoints to its PRO API. If token data fails to load, "
               "add a free `BLOCKSCOUT_API_KEY` to `.streamlit/secrets.toml`.")

l1, l2, l3, l4 = st.columns([2, 2, 3, 2])
with l1:
    sort_key = st.selectbox(
        "Rank by", ["circulating_market_cap", "holders_count", "fiat_value"],
        format_func=lambda x: {"circulating_market_cap": "Market cap", "holders_count": "Holders",
                               "fiat_value": "Fiat value"}[x])
with l2:
    n_tokens = st.selectbox("Tokens to load", [50, 100, 150], index=1)
with l3:
    q = st.text_input("Search by name or symbol", "", key="tok_q")
with l4:
    min_mcap = st.number_input("Min market cap (USD)", min_value=0, value=0, step=100_000)

tok_df = sc(get_token_list, sort_key, q.strip(), max(1, n_tokens // 50), default=pd.DataFrame(),
            label="Blockscout token list")
if tok_df is None:
    tok_df = pd.DataFrame()

if tok_df.empty:
    st.info("Token list is unavailable right now (see data warnings at the bottom).")
else:
    view = tok_df[tok_df["Mcap"].fillna(0) >= min_mcap].copy() if min_mcap else tok_df.copy()

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Tokens Shown", f"{len(view)}")
    k2.metric("Combined Market Cap", fmt_usd(view["Mcap"].sum()))
    k3.metric("Combined 24h Volume", fmt_usd(view["Vol 24h"].sum()))
    k4.metric("Median Holders", fmt_num(view["Holders"].median()))

    priced = view[view["Mcap"].fillna(0) > 0]
    cl, cr = st.columns(2)
    with cl:
        if not priced.empty:
            top15 = priced.sort_values("Mcap", ascending=False).head(15).sort_values("Mcap")
            fig = go.Figure(go.Bar(x=top15["Mcap"], y=top15["Symbol"], orientation="h", marker_color=ACCENT,
                                   text=[fmt_usd(v) for v in top15["Mcap"]], textposition="outside"))
            fig.update_layout(title="Top 15 Tokens by Market Cap", height=470,
                              margin=dict(l=10, r=70, t=50, b=10), xaxis_title="USD", plot_bgcolor="white")
            show_chart(fig)
        else:
            st.info("No priced tokens in this selection.")
    with cr:
        if not priced.empty:
            top = priced.sort_values("Mcap", ascending=False)
            pie = top.head(10)[["Symbol", "Mcap"]].copy()
            rest = top.iloc[10:]["Mcap"].sum()
            if rest > 0:
                pie = pd.concat([pie, pd.DataFrame([{"Symbol": "Others", "Mcap": rest}])], ignore_index=True)
            fig = px.pie(pie, names="Symbol", values="Mcap", hole=0.5,
                         color_discrete_sequence=BLUE_SPECTRUM, title="Market Cap Share (loaded tokens)")
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(height=470, margin=dict(l=10, r=10, t=50, b=10))
            show_chart(fig)

    cl, cr = st.columns(2)
    with cl:
        sc_df = priced[priced["Holders"].fillna(0) > 0]
        if not sc_df.empty:
            fig = px.scatter(sc_df, x="Holders", y="Mcap", hover_name="Symbol", log_x=True, log_y=True,
                             size=sc_df["Vol 24h"].fillna(0).clip(lower=1), size_max=34,
                             color_discrete_sequence=[ACCENT], title="Holders vs Market Cap (bubble = 24h volume)")
            fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10), plot_bgcolor="white",
                              yaxis_title="Market cap (USD)")
            show_chart(fig)
    with cr:
        h = view[view["Holders"].fillna(0) > 0]
        if not h.empty:
            fig = go.Figure(go.Histogram(x=h["Holders"], nbinsx=30, marker_color=ACCENT))
            fig.update_layout(title="Distribution of Holder Counts", height=420,
                              margin=dict(l=10, r=10, t=50, b=10), xaxis_title="Holders (log scale)",
                              xaxis_type="log", yaxis_title="Tokens", plot_bgcolor="white")
            show_chart(fig)

    disp = view.copy()
    disp["Price"] = disp["Price USD"].apply(price_text)
    disp = disp[["Token", "Symbol", "Price", "Mcap", "FDV (est.)", "Vol 24h", "Vol/Mcap", "Holders", "Supply", "Address"]]
    C = st.column_config
    show_table(disp, column_config={
        "Mcap": C.NumberColumn("Market Cap", format="$%.0f"), "FDV (est.)": C.NumberColumn(format="$%.0f"),
        "Vol 24h": C.NumberColumn("Volume 24h", format="$%.0f"), "Vol/Mcap": C.NumberColumn(format="%.3f"),
        "Holders": C.NumberColumn(format="%d"), "Supply": C.NumberColumn("Total Supply", format="%.0f"),
    })
    st.caption("Prices, market caps and volumes come from Blockscout's token index and are only available for tokens "
               "it has market data for. 'FDV (est.)' = price × total supply. Spam and scam tokens exist on every "
               "chain — verify a token before interacting with it. Not financial advice.")

st.markdown("---")

# ============================================================
# --- Section 2: Token analyzer ---
# ============================================================
st.subheader("Token Analyzer")

options = {}
if not tok_df.empty:
    for _, r in tok_df.iterrows():
        if r["Address"]:
            options[f"{r['Symbol'] or '?'} — {r['Token'] or 'Unnamed'} · {short(r['Address'])}"] = r["Address"]
MANUAL = "✏️ Enter a token address manually"
choice = st.selectbox("Choose a token", list(options.keys()) + [MANUAL])
if choice == MANUAL:
    addr = st.text_input("Token contract address (0x…)", "").strip() or None
else:
    addr = options[choice]

if addr:
    det = sc(get_token_details, addr, default=None, label="Blockscout token details")
    gt = sc(get_gt_token, addr, default={}, label="GeckoTerminal token") or {}

    if not det:
        st.info("Token details are unavailable. Check the address, or see the data warnings at the bottom.")
    else:
        dec = det["decimals"] if det["decimals"] is not None else 18
        st.markdown(f"**{det['name'] or 'Unnamed'}** ({det['symbol'] or '?'}) · {det['type'] or 'ERC-20'} · "
                    f"decimals {dec}  ·  `{addr}`")

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Price (GeckoTerminal)", price_text(gt.get("price")))
        m2.metric("Price (Blockscout)", price_text(det["price"]))
        m3.metric("Market Cap", fmt_usd(gt.get("mcap") or det["mcap"]))
        m4.metric("FDV", fmt_usd(gt.get("fdv")))
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Holders", fmt_num(det["holders"]))
        m6.metric("Total Transfers", fmt_num(det["transfers"]))
        m7.metric("Total Supply", fmt_num(det["supply"]))
        m8.metric("24h Volume", fmt_usd(gt.get("vol24") if gt.get("vol24") is not None else det["vol24"]))
        if gt.get("reserve") is not None:
            st.caption(f"Total liquidity across pools (GeckoTerminal): {fmt_usd(gt['reserve'])}")

        view_choice = st.radio("View", ["Market & Pools", "Holders", "Transfers"], horizontal=True, key="tok_view")

        # ------------------------------------------------------------
        if view_choice == "Market & Pools":
            pools = sc(get_gt_token_pools, addr, default=pd.DataFrame(), label="GeckoTerminal token pools")
            if pools is not None and not pools.empty:
                pl, pr = st.columns(2)
                with pl:
                    by_dex = pools.groupby("DEX", as_index=False)["Liquidity"].sum().sort_values("Liquidity", ascending=False)
                    by_dex = by_dex[by_dex["Liquidity"] > 0]
                    if not by_dex.empty:
                        fig = px.pie(by_dex, names="DEX", values="Liquidity", hole=0.5,
                                     color_discrete_sequence=BLUE_SPECTRUM, title="Liquidity by DEX")
                        fig.update_traces(textposition="inside", textinfo="percent+label")
                        fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
                        show_chart(fig)
                with pr:
                    top_p = pools.sort_values("Vol 24h", ascending=False).head(10).sort_values("Vol 24h")
                    fig = go.Figure(go.Bar(x=top_p["Vol 24h"], y=top_p["Pool"], orientation="h", marker_color=ACCENT))
                    fig.update_layout(title="Top Pools by 24h Volume", height=380,
                                      margin=dict(l=10, r=20, t=50, b=10), plot_bgcolor="white")
                    show_chart(fig)

                tbl = pools.copy()
                tbl["Price"] = tbl["Price USD"].apply(price_text)
                tbl["Age"] = tbl["Age (h)"].apply(age_text)
                tbl = tbl[["Pool", "DEX", "Price", "Liquidity", "Vol 24h", "Chg 24h", "Txs 24h", "Age", "Address"]]
                C = st.column_config
                show_table(tbl, column_config={
                    "Liquidity": C.NumberColumn(format="$%.0f"), "Vol 24h": C.NumberColumn("Volume 24h", format="$%.0f"),
                    "Chg 24h": C.NumberColumn("Change 24h", format="%.2f%%"), "Txs 24h": C.NumberColumn(format="%d")})

                # price chart from the deepest pool
                deepest = pools.sort_values("Liquidity", ascending=False).iloc[0]
                pool_labels = {f"{r['Pool']} · {r['DEX']} · {short(r['Address'])}": r["Address"]
                               for _, r in pools.sort_values("Liquidity", ascending=False).iterrows()}
                sel = st.selectbox("Price chart pool (default: deepest liquidity)", list(pool_labels.keys()))
                tf_map = {"Daily": ("day", 1, 180), "4 hours": ("hour", 4, 200), "1 hour": ("hour", 1, 200),
                          "15 minutes": ("minute", 15, 200)}
                tf_label = st.radio("Timeframe", list(tf_map.keys()), horizontal=True, index=1, key="tok_tf")
                tf, agg, lim = tf_map[tf_label]
                ohlc = sc(get_ohlcv, pool_labels[sel], tf, agg, lim, default=pd.DataFrame(), label="GeckoTerminal OHLCV")
                if ohlc is not None and not ohlc.empty:
                    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.03)
                    fig.add_trace(go.Candlestick(
                        x=ohlc["date"], open=ohlc["open"], high=ohlc["high"], low=ohlc["low"], close=ohlc["close"],
                        increasing_line_color=ACCENT, increasing_fillcolor=ACCENT,
                        decreasing_line_color=DOWN_COLOR, decreasing_fillcolor=DOWN_COLOR, name="Price"), row=1, col=1)
                    fig.add_trace(go.Bar(x=ohlc["date"], y=ohlc["volume"], marker_color="#8c8cff", name="Volume"), row=2, col=1)
                    fig.update_layout(title=f"{det['symbol'] or 'Token'} Price & Volume ({tf_label})", height=540,
                                      margin=dict(l=10, r=10, t=50, b=10), xaxis_rangeslider_visible=False,
                                      showlegend=False, plot_bgcolor="white")
                    fig.update_yaxes(title_text="Price (USD)", row=1, col=1)
                    fig.update_yaxes(title_text="Volume (USD)", row=2, col=1)
                    show_chart(fig)
                else:
                    st.info("No price history returned for this pool.")
            else:
                st.info("No trading pools found for this token on Base.")

        # ------------------------------------------------------------
        elif view_choice == "Holders":
            hp = st.selectbox("Holders to load", [50, 100, 150], index=1, key="hold_n")
            hdf = sc(get_holders, addr, dec, hp // 50, default=pd.DataFrame(), label="Blockscout holders")
            if hdf is not None and not hdf.empty and hdf["Balance"].notna().any():
                supply = det["supply"]
                hdf = hdf.sort_values("Balance", ascending=False).reset_index(drop=True)
                hdf["% of Supply"] = hdf["Balance"] / supply * 100 if supply else None

                if supply:
                    t1 = hdf.head(1)["% of Supply"].sum()
                    t10 = hdf.head(10)["% of Supply"].sum()
                    tall = hdf["% of Supply"].sum()
                    h1, h2, h3, h4 = st.columns(4)
                    h1.metric("Top Holder", f"{t1:.2f}%")
                    h2.metric("Top 10 Holders", f"{t10:.2f}%")
                    h3.metric(f"Top {len(hdf)} Holders", f"{tall:.2f}%")
                    h4.metric("Contracts in Top 10", f"{int((hdf.head(10)['Type'] == 'Contract').sum())}")

                hl, hr = st.columns(2)
                with hl:
                    top10 = hdf.head(10).copy()
                    top10["Name"] = top10.apply(lambda r: r["Label"] or short(r["Holder"]), axis=1)
                    top10 = top10.sort_values("Balance")
                    fig = go.Figure(go.Bar(x=top10["Balance"], y=top10["Name"], orientation="h", marker_color=ACCENT))
                    fig.update_layout(title="Top 10 Holders (token balance)", height=420,
                                      margin=dict(l=10, r=20, t=50, b=10), plot_bgcolor="white")
                    show_chart(fig)
                with hr:
                    if supply:
                        top_share = hdf.head(10)["Balance"].sum()
                        mid_share = hdf.iloc[10:]["Balance"].sum()
                        other = max(supply - top_share - mid_share, 0)
                        pie = pd.DataFrame({"Group": ["Top 10", f"Next {max(len(hdf) - 10, 0)}", "All other holders"],
                                            "Tokens": [top_share, mid_share, other]})
                    else:
                        pie = hdf.groupby("Type", as_index=False)["Balance"].sum().rename(columns={"Type": "Group", "Balance": "Tokens"})
                    fig = px.pie(pie, names="Group", values="Tokens", hole=0.5,
                                 color_discrete_sequence=BLUE_SPECTRUM, title="Supply Concentration")
                    fig.update_traces(textposition="inside", textinfo="percent+label")
                    fig.update_layout(height=420, margin=dict(l=10, r=10, t=50, b=10))
                    show_chart(fig)

                tcnt = hdf.groupby("Type", as_index=False).agg(Holders=("Holder", "count"), Balance=("Balance", "sum"))
                tl, tr = st.columns([1, 2])
                with tl:
                    fig = px.pie(tcnt, names="Type", values="Balance", hole=0.5,
                                 color_discrete_sequence=BLUE_SPECTRUM, title="Balance: Wallets vs Contracts")
                    fig.update_traces(textposition="inside", textinfo="percent+label")
                    fig.update_layout(height=340, margin=dict(l=10, r=10, t=50, b=10))
                    show_chart(fig)
                with tr:
                    t = hdf.copy()
                    t["Holder"] = t["Holder"].apply(lambda a: a)
                    show_table(t, column_config={
                        "Balance": st.column_config.NumberColumn(format="%.4f"),
                        "% of Supply": st.column_config.NumberColumn(format="%.3f%%")})
                st.caption("Large holders are often liquidity pools, bridges, exchanges, vesting or burn addresses — "
                           "a high concentration is not automatically a red flag. Only the top holders are loaded.")
            else:
                st.info("Holder data is unavailable for this token.")

        # ------------------------------------------------------------
        else:
            tp = st.selectbox("Transfers to load", [50, 100, 150], index=1, key="tr_n")
            tdf = sc(get_transfers, addr, dec, tp // 50, default=pd.DataFrame(), label="Blockscout transfers")
            if tdf is not None and not tdf.empty:
                amt = tdf["Amount"].dropna()
                span = (tdf["Time (UTC)"].max() - tdf["Time (UTC)"].min()).total_seconds()
                s1, s2, s3, s4 = st.columns(4)
                s1.metric("Transfers Loaded", f"{len(tdf)}", f"over {span / 60:,.1f} min" if span else None, delta_color="off")
                s2.metric("Unique Senders", f"{tdf['From'].nunique()}")
                s3.metric("Unique Receivers", f"{tdf['To'].nunique()}")
                s4.metric("Largest Transfer", fmt_num(amt.max(), 2) if not amt.empty else "N/A")
                n_mint = int((tdf["Type"] == "Minting").sum())
                n_burn = int((tdf["Type"] == "Burning").sum())
                if n_mint or n_burn:
                    st.caption(f"In this sample: {n_mint} mint(s), {n_burn} burn(s).")

                tl, tr = st.columns(2)
                with tl:
                    pos = amt[amt > 0]
                    if not pos.empty:
                        fig = go.Figure(go.Histogram(x=pos, nbinsx=30, marker_color=ACCENT))
                        fig.update_layout(title="Transfer Size Distribution", height=380,
                                          margin=dict(l=10, r=10, t=50, b=10), xaxis_title="Amount (tokens, log scale)",
                                          xaxis_type="log", yaxis_title="Transfers", plot_bgcolor="white")
                        show_chart(fig)
                with tr:
                    cnt = tdf["From"].value_counts().head(10).sort_values().reset_index()
                    cnt.columns = ["Address", "Transfers"]
                    cnt["Address"] = cnt["Address"].apply(short)
                    fig = go.Figure(go.Bar(x=cnt["Transfers"], y=cnt["Address"], orientation="h", marker_color=ACCENT))
                    fig.update_layout(title="Most Active Senders (in sample)", height=380,
                                      margin=dict(l=10, r=20, t=50, b=10), xaxis_title="Transfers", plot_bgcolor="white")
                    show_chart(fig)

                disp = tdf.copy()
                disp["Time (UTC)"] = disp["Time (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S")
                disp["From"] = disp.apply(lambda r: r["From Label"] or short(r["From"]), axis=1)
                disp["To"] = disp.apply(lambda r: r["To Label"] or short(r["To"]), axis=1)
                disp["Tx"] = disp["Tx"].apply(short)
                disp = disp[["Time (UTC)", "Type", "From", "To", "Amount", "Tx"]]
                show_table(disp, column_config={"Amount": st.column_config.NumberColumn(format="%.4f")})
                st.caption("A snapshot of the most recent transfers, not the full history.")
            else:
                st.info("Transfer data is unavailable for this token.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| Token leaderboard | ERC-20 list: price, market cap, 24h volume, holders, total supply | [Blockscout – Base](https://base.blockscout.com/tokens) · `/api/v2/tokens` (filters: `type`, `sort`, `order`, `q`) · [docs](https://docs.blockscout.com) |
| Token analyzer — details | Name, symbol, decimals, supply, holders, transfer count | Blockscout · `/api/v2/tokens/{address}` and `/counters` |
| Holders | Top holder balances and labels | Blockscout · `/api/v2/tokens/{address}/holders` |
| Transfers | Latest token transfers | Blockscout · `/api/v2/tokens/{address}/transfers` |
| Market, pools, price chart | Price, FDV, liquidity, volume, pools, OHLCV | [GeckoTerminal – Base](https://www.geckoterminal.com/base) · API v2 `/networks/base/tokens/{address}`, `/pools`, `/ohlcv/{timeframe}` · [docs](https://apiguide.geckoterminal.com) |
| Derived metrics | FDV estimate, Vol/Mcap, supply concentration, wallet vs contract split | Calculated in this app |
"""
)
st.caption(
    "Notes: Blockscout market data covers only tokens it has prices for, and GeckoTerminal covers tokens traded "
    "in DEX pools it indexes, so the two sources can disagree. Holder and transfer sections load only the "
    "first pages of results. Third-party APIs may change limits or availability at any time."
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
