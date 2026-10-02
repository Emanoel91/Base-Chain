import json
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta, timezone

from common import (
    ACCENT, ACCENT_FILL, MA_COLOR, BLUE_SPECTRUM, BLOCKSCOUT_KEY,
    bs_request, safe_call, empty_ts, show_chart, show_table, page_header, sidebar_controls,
    fmt_num, fmt_pct, safe_float,
)

st.set_page_config(page_title="Base Chain - Smart Contracts", page_icon="🔵", layout="wide")

errors = []


def sc(fn, *args, **kwargs):
    return safe_call(errors, fn, *args, **kwargs)


sidebar_controls()
page_header(
    "Base Chain — Smart Contracts",
    "Contract deployment and verification trends on <b>Base</b>, an explorer for verified contracts "
    "(languages, compilers, activity), and a contract analyzer with metadata, source code, ABI and "
    "recent on-chain activity. All data comes from Blockscout. See the <b>Sources</b> section at the bottom."
)

START = "2023-08-01"  # Base mainnet launch month
TODAY_STR = datetime.now(timezone.utc).date().isoformat()


def short(addr):
    return f"{addr[:8]}…{addr[-6:]}" if isinstance(addr, str) and len(addr) > 16 else addr


def to_int(x, default=None):
    try:
        return int(float(x))
    except (TypeError, ValueError):
        return default


# ============================================================
# --- Fetchers: stats service (deployment trends) ---
# ============================================================
@st.cache_data(ttl=3600, show_spinner=False)
def get_available_lines() -> dict:
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
    j = bs_request(f"/stats-service/api/v1/lines/{name}",
                   {"from": start, "to": end, "resolution": "DAY"})
    df = pd.DataFrame(j.get("chart", []))
    info = j.get("info", {}) or {}
    if df.empty or "date" not in df.columns:
        return empty_ts(), "", name
    out = pd.DataFrame({"date": pd.to_datetime(df["date"]),
                        "value": pd.to_numeric(df["value"], errors="coerce")}).dropna()
    out = out[out["date"].dt.date < datetime.now(timezone.utc).date()]  # drop today's partial day
    return out.sort_values("date").reset_index(drop=True), info.get("units") or "", info.get("title") or name


# ============================================================
# --- Fetchers: verified contracts & contract details ---
# ============================================================
@st.cache_data(ttl=600, show_spinner=False)
def get_verified_contracts(sort: str, language: str, q: str, pages: int) -> pd.DataFrame:
    base = {"sort": sort, "order": "desc"}
    if language != "all":
        base["filter"] = language
    if q:
        base["q"] = q
    params, rows = dict(base), []
    for _ in range(pages):
        j = bs_request("/api/v2/smart-contracts", params)
        for c in j.get("items", []):
            a = c.get("address") or {}
            bal = safe_float(c.get("coin_balance"))
            txc = None
            for k in ("transactions_count", "transaction_count", "tx_count"):
                if c.get(k) is not None:
                    txc = to_int(c.get(k))
                    break
            comp = c.get("compiler_version") or ""
            rows.append({
                "Contract": a.get("name") or "(unnamed)",
                "Address": a.get("hash") or c.get("address_hash"),
                "Language": (c.get("language") or "unknown").capitalize(),
                "Compiler": comp.split("+")[0].lstrip("v") if comp else "unknown",
                "Optimized": bool(c.get("optimization_enabled")),
                "Txs": txc,
                "Balance (ETH)": bal / 1e18 if bal is not None else None,
                "Verified At": pd.to_datetime(c.get("verified_at"), utc=True, errors="coerce"),
                "Certified": bool(c.get("certified")),
            })
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = {**base, **nxt}
    return pd.DataFrame(rows)


@st.cache_data(ttl=300, show_spinner=False)
def get_contract(addr: str) -> dict:
    out = {"sc": None, "addr": None, "counters": None}
    try:
        out["sc"] = bs_request(f"/api/v2/smart-contracts/{addr}")
    except Exception as e:
        out["sc_error"] = str(e)
    try:
        out["addr"] = bs_request(f"/api/v2/addresses/{addr}")
    except Exception as e:
        out["addr_error"] = str(e)
    try:
        out["counters"] = bs_request(f"/api/v2/addresses/{addr}/counters")
    except Exception:
        pass
    return out


@st.cache_data(ttl=60, show_spinner=False)
def get_contract_txs(addr: str, pages: int) -> pd.DataFrame:
    params, rows = {"filter": "to"}, []
    for _ in range(pages):
        j = bs_request(f"/api/v2/addresses/{addr}/transactions", params)
        for t in j.get("items", []):
            fee = safe_float((t.get("fee") or {}).get("value"))
            rows.append({
                "Time (UTC)": pd.to_datetime(t.get("timestamp"), utc=True, errors="coerce"),
                "Method": t.get("method") or "unknown",
                "Status": "Success" if t.get("status") == "ok" else "Failed",
                "From": (t.get("from") or {}).get("hash"),
                "Value (ETH)": (safe_float(t.get("value")) or 0) / 1e18,
                "Fee (ETH)": fee / 1e18 if fee is not None else None,
                "Gas Used": safe_float(t.get("gas_used")),
                "Tx": t.get("hash"),
            })
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = {"filter": "to", **nxt}
    return pd.DataFrame(rows)


@st.cache_data(ttl=60, show_spinner=False)
def get_contract_logs(addr: str, pages: int) -> pd.DataFrame:
    params, rows = {}, []
    for _ in range(pages):
        j = bs_request(f"/api/v2/addresses/{addr}/logs", params)
        for lg in j.get("items", []):
            dec = lg.get("decoded") or {}
            call = dec.get("method_call")
            topics = lg.get("topics") or []
            name = call.split("(")[0] if call else (f"topic {short(topics[0])}" if topics and topics[0] else "unknown")
            rows.append({"Event": name, "Block": lg.get("block_number"), "Tx": lg.get("transaction_hash"),
                         "Decoded": bool(call)})
        nxt = j.get("next_page_params")
        if not nxt:
            break
        params = nxt
    return pd.DataFrame(rows)


# ============================================================
# --- ABI helpers ---
# ============================================================
def abi_type(i: dict) -> str:
    t = i.get("type", "")
    if t.startswith("tuple"):
        return "(" + ",".join(abi_type(c) for c in i.get("components", [])) + ")" + t[5:]
    return t


def parse_abi(abi: list):
    funcs, events, errs = [], [], 0
    for e in abi or []:
        et = e.get("type")
        if et == "function":
            ins = e.get("inputs") or []
            outs = e.get("outputs") or []
            mut = e.get("stateMutability") or ("view" if e.get("constant") else "nonpayable")
            funcs.append({
                "Function": e.get("name"),
                "Signature": f"{e.get('name')}({','.join(abi_type(i) for i in ins)})",
                "Mutability": mut,
                "Kind": "Read" if mut in ("view", "pure") else "Write",
                "Inputs": len(ins), "Outputs": len(outs),
            })
        elif et == "event":
            ins = e.get("inputs") or []
            events.append({
                "Event": e.get("name"),
                "Signature": f"{e.get('name')}({','.join(abi_type(i) for i in ins)})",
                "Params": len(ins),
                "Indexed": sum(1 for i in ins if i.get("indexed")),
                "Anonymous": bool(e.get("anonymous")),
            })
        elif et == "error":
            errs += 1
    return pd.DataFrame(funcs), pd.DataFrame(events), errs


# Heuristic keyword scan of state-changing functions (NOT an audit)
PRIVILEGE_KEYWORDS = {
    "Ownership / roles": ["owner", "admin", "grantrole", "revokerole", "setrole", "operator", "governance"],
    "Upgradeability": ["upgrade", "implementation", "initialize", "setimplementation"],
    "Supply control": ["mint", "burn"],
    "Pause / blocklist": ["pause", "unpause", "blacklist", "blocklist", "freeze", "ban"],
    "Funds control": ["withdraw", "rescue", "sweep", "emergency", "recover", "drain"],
    "Fees / parameters": ["setfee", "settax", "setrate", "setparam", "setconfig", "setlimit"],
}


def privilege_scan(funcs: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, f in funcs[funcs["Kind"] == "Write"].iterrows():
        name = (f["Function"] or "").lower()
        for cat, kws in PRIVILEGE_KEYWORDS.items():
            if any(k in name for k in kws):
                rows.append({"Category": cat, "Function": f["Signature"], "Mutability": f["Mutability"]})
                break
    return pd.DataFrame(rows)


# ============================================================
# --- Section 1: deployment & verification trends ---
# ============================================================
st.subheader("Deployment & Verification Trends")

LINE_IDS = {
    "newContracts": "New Contracts",
    "newVerifiedContracts": "New Verified Contracts",
    "contractsGrowth": "Total Contracts",
    "verifiedContractsGrowth": "Total Verified Contracts",
}
avail = sc(get_available_lines, default={}, label="Blockscout stats-service (chart list)")
series = {}
if avail:
    for sid in LINE_IDS:
        if sid in avail:
            res = sc(get_line, sid, START, TODAY_STR, default=None, label=f"chart {sid}")
            if res and not res[0].empty:
                series[sid] = res[0]
missing = [LINE_IDS[s] for s in LINE_IDS if s not in series]

if not series:
    st.warning(
        "Contract trend charts need Blockscout's stats-service"
        + ("" if BLOCKSCOUT_KEY else ", which usually requires a free API key")
        + ". Add `BLOCKSCOUT_API_KEY` to `.streamlit/secrets.toml` (free from dev.blockscout.com). "
          "The explorer and analyzer below still work."
    )
else:
    def last_vs_prev(df):
        if df is None or len(df) < 2:
            return None, None
        last, prev = df.iloc[-1]["value"], df.iloc[-2]["value"]
        return last, ((last - prev) / prev * 100 if prev else None)

    def window_avg(df, n):
        if df is None or len(df) < 2 * n:
            return None, None
        v = df["value"]
        cur, prv = v.tail(n).mean(), v.iloc[-2 * n:-n].mean()
        return cur, ((cur - prv) / prv * 100 if prv else None)

    nc, nv = series.get("newContracts"), series.get("newVerifiedContracts")
    tc, tv = series.get("contractsGrowth"), series.get("verifiedContractsGrowth")

    k1, k2, k3, k4 = st.columns(4)
    v, ch = last_vs_prev(nc)
    k1.metric("New Contracts (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
    v7, ch7 = window_avg(nc, 7)
    k2.metric("7D Avg New Contracts / Day", fmt_num(v7), fmt_pct(ch7) if ch7 is not None else None)
    v, ch = last_vs_prev(nv)
    k3.metric("New Verified (last day)", fmt_num(v), fmt_pct(ch) if ch is not None else None)
    if nc is not None and nv is not None and len(nc) and len(nv):
        m = nc.merge(nv, on="date", suffixes=("_c", "_v"))
        rate = (m.iloc[-1]["value_v"] / m.iloc[-1]["value_c"] * 100) if len(m) and m.iloc[-1]["value_c"] else None
        k4.metric("Verification Rate (last day)", f"{rate:.2f}%" if rate is not None else "N/A")
    else:
        k4.metric("Verification Rate (last day)", "N/A")

    k5, k6, k7, k8 = st.columns(4)
    k5.metric("Total Contracts", fmt_num(tc.iloc[-1]["value"]) if tc is not None and len(tc) else "N/A")
    k6.metric("Total Verified Contracts", fmt_num(tv.iloc[-1]["value"]) if tv is not None and len(tv) else "N/A")
    if tc is not None and tv is not None and len(tc) and len(tv):
        mm = tc.merge(tv, on="date", suffixes=("_c", "_v"))
        all_rate = mm.iloc[-1]["value_v"] / mm.iloc[-1]["value_c"] * 100 if len(mm) and mm.iloc[-1]["value_c"] else None
        k7.metric("Verified Share (all-time)", f"{all_rate:.2f}%" if all_rate is not None else "N/A")
    else:
        k7.metric("Verified Share (all-time)", "N/A")
    if nc is not None and len(nc):
        pk = nc.loc[nc["value"].idxmax()]
        k8.metric("Peak Daily Deployments", fmt_num(pk["value"]), pk["date"].strftime("%Y-%m-%d"), delta_color="off")
    else:
        k8.metric("Peak Daily Deployments", "N/A")

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

    def aggregate(df, agg):
        if gran == "Daily" or df is None or df.empty:
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
        return out[out["date"].map(span_end) <= df["date"].max()].reset_index(drop=True)

    def in_range(df):
        if df is None or df.empty or days is None:
            return df
        return df[df["date"] >= df["date"].max() - timedelta(days=days)]

    def bar_chart(df, title, ma=True, y_title=None):
        df = in_range(df)
        t = title if gran == "Daily" else f"{title} — {gran}"
        fig = go.Figure(go.Bar(x=df["date"], y=df["value"], marker_color=ACCENT, name=title))
        if show_ma and ma and len(df) > MA_WINDOW:
            fig.add_trace(go.Scatter(x=df["date"], y=df["value"].rolling(MA_WINDOW).mean(), mode="lines",
                                     line=dict(color=MA_COLOR, width=2), name=f"{MA_WINDOW}-period MA"))
        fig.update_layout(title=t, height=360, margin=dict(l=10, r=10, t=50, b=10), yaxis_title=y_title,
                          hovermode="x unified", plot_bgcolor="white", showlegend=bool(show_ma and ma),
                          legend=dict(orientation="h", y=1.12, x=0))
        return fig

    def area_chart(df, title, y_title=None):
        df = in_range(aggregate(df, "last"))
        fig = go.Figure(go.Scatter(x=df["date"], y=df["value"], mode="lines", fill="tozeroy",
                                   line=dict(color=ACCENT, width=2), fillcolor=ACCENT_FILL))
        fig.update_layout(title=title if gran == "Daily" else f"{title} — {gran}", height=360,
                          margin=dict(l=10, r=10, t=50, b=10), yaxis_title=y_title,
                          hovermode="x unified", plot_bgcolor="white")
        return fig

    c1, c2 = st.columns(2)
    with c1:
        if nc is not None:
            show_chart(bar_chart(aggregate(nc, "sum"), "New Contracts Deployed", y_title="Contracts"))
    with c2:
        if nv is not None:
            show_chart(bar_chart(aggregate(nv, "sum"), "New Contracts Verified", y_title="Contracts"))

    c1, c2 = st.columns(2)
    with c1:
        if nc is not None and nv is not None:
            a_c, a_v = aggregate(nc, "sum"), aggregate(nv, "sum")
            mrg = a_c.merge(a_v, on="date", suffixes=("_c", "_v"))
            mrg = mrg[mrg["value_c"] > 0]
            if not mrg.empty:
                rate_df = pd.DataFrame({"date": mrg["date"], "value": mrg["value_v"] / mrg["value_c"] * 100})
                rate_df = in_range(rate_df)
                fig = go.Figure(go.Scatter(x=rate_df["date"], y=rate_df["value"], mode="lines",
                                           line=dict(color=ACCENT, width=2)))
                fig.update_layout(title="Verification Rate of New Contracts (%)", height=360,
                                  margin=dict(l=10, r=10, t=50, b=10), yaxis_title="%",
                                  hovermode="x unified", plot_bgcolor="white")
                show_chart(fig)
    with c2:
        if tc is not None and tv is not None:
            fig = go.Figure()
            a, b = in_range(aggregate(tc, "last")), in_range(aggregate(tv, "last"))
            fig.add_trace(go.Scatter(x=a["date"], y=a["value"], mode="lines", name="All contracts",
                                     line=dict(color=ACCENT, width=2)))
            fig.add_trace(go.Scatter(x=b["date"], y=b["value"], mode="lines", name="Verified",
                                     line=dict(color=MA_COLOR, width=2)))
            fig.update_layout(title="Cumulative Contracts", height=360, margin=dict(l=10, r=10, t=50, b=10),
                              hovermode="x unified", plot_bgcolor="white", legend=dict(orientation="h", y=1.12, x=0))
            show_chart(fig)
        elif tc is not None:
            show_chart(area_chart(tc, "Cumulative Contracts"))

    if missing:
        st.caption("Not available from this data source: " + ", ".join(missing))
    st.caption("Counts include every contract creation, including contracts deployed automatically by factories "
               "(for example smart-wallet and token-launcher deployments), so they can be much larger than the number "
               "of distinct projects.")

st.markdown("---")

# ============================================================
# --- Section 2: verified contracts explorer ---
# ============================================================
st.subheader("Verified Contracts Explorer")
e1, e2, e3, e4 = st.columns([2, 2, 3, 2])
with e1:
    sort_key = st.selectbox("Sort by", ["transactions_count", "balance"],
                            format_func=lambda x: {"transactions_count": "Transactions", "balance": "ETH balance"}[x])
with e2:
    lang = st.selectbox("Language", ["all", "solidity", "vyper", "yul"],
                        format_func=lambda x: "All" if x == "all" else x.capitalize())
with e3:
    q = st.text_input("Search by name or address", "", key="sc_q")
with e4:
    n_load = st.selectbox("Contracts to load", [50, 100, 150], index=1)

cdf = sc(get_verified_contracts, sort_key, lang, q.strip(), max(1, n_load // 50), default=pd.DataFrame(),
         label="Blockscout verified contracts")
if cdf is None:
    cdf = pd.DataFrame()

if cdf.empty:
    st.info("Verified contracts are unavailable right now (see data warnings at the bottom).")
else:
    s1, s2, s3, s4 = st.columns(4)
    s1.metric("Contracts in Sample", f"{len(cdf)}")
    s2.metric("Solidity Share", f"{(cdf['Language'] == 'Solidity').mean() * 100:.1f}%")
    s3.metric("Optimizer Enabled", f"{cdf['Optimized'].mean() * 100:.1f}%")
    s4.metric("Median Transactions", fmt_num(cdf["Txs"].median()) if cdf["Txs"].notna().any() else "N/A")

    cl, cr = st.columns(2)
    with cl:
        lg = cdf["Language"].value_counts().reset_index()
        lg.columns = ["Language", "Contracts"]
        fig = px.pie(lg, names="Language", values="Contracts", hole=0.5,
                     color_discrete_sequence=BLUE_SPECTRUM, title="Contracts by Language (sample)")
        fig.update_traces(textposition="inside", textinfo="percent+label")
        fig.update_layout(height=380, margin=dict(l=10, r=10, t=50, b=10))
        show_chart(fig)
    with cr:
        cv = cdf["Compiler"].value_counts().head(10).sort_values().reset_index()
        cv.columns = ["Compiler", "Contracts"]
        fig = go.Figure(go.Bar(x=cv["Contracts"], y=cv["Compiler"], orientation="h", marker_color=ACCENT))
        fig.update_layout(title="Top 10 Compiler Versions (sample)", height=380,
                          margin=dict(l=10, r=20, t=50, b=10), xaxis_title="Contracts",
                          yaxis_type="category", plot_bgcolor="white")
        show_chart(fig)

    cl, cr = st.columns(2)
    with cl:
        top = cdf[cdf["Txs"].notna()].sort_values("Txs", ascending=False).head(15).sort_values("Txs")
        if not top.empty:
            fig = go.Figure(go.Bar(x=top["Txs"], y=top["Contract"], orientation="h", marker_color=ACCENT))
            fig.update_layout(title="Top 15 Contracts by Transaction Count", height=440,
                              margin=dict(l=10, r=20, t=50, b=10), xaxis_title="Transactions", plot_bgcolor="white")
            show_chart(fig)
    with cr:
        vt = cdf.dropna(subset=["Verified At"]).copy()
        if not vt.empty:
            vt["Month"] = vt["Verified At"].dt.tz_localize(None).dt.to_period("M").dt.to_timestamp()
            vm = vt.groupby("Month", as_index=False).size()
            fig = go.Figure(go.Bar(x=vm["Month"], y=vm["size"], marker_color=ACCENT))
            fig.update_layout(title="When Sampled Contracts Were Verified (by month)", height=440,
                              margin=dict(l=10, r=10, t=50, b=10), yaxis_title="Contracts", plot_bgcolor="white")
            show_chart(fig)

    disp = cdf.copy()
    disp["Verified At"] = disp["Verified At"].dt.strftime("%Y-%m-%d")
    disp["Optimized"] = disp["Optimized"].map({True: "Yes", False: "No"})
    disp["Certified"] = disp["Certified"].map({True: "Yes", False: "No"})
    C = st.column_config
    show_table(disp, column_config={
        "Txs": C.NumberColumn("Transactions", format="%d"),
        "Balance (ETH)": C.NumberColumn(format="%.4f"),
    })
    st.caption("This is a sample of verified contracts ordered by the selected field, not every contract on Base. "
               "A contract being verified means its source code matches the deployed bytecode — it does not mean the "
               "code is safe or audited.")

st.markdown("---")

# ============================================================
# --- Section 3: contract analyzer ---
# ============================================================
st.subheader("Contract Analyzer")

options = {}
if not cdf.empty:
    for _, r in cdf.iterrows():
        if r["Address"]:
            options[f"{r['Contract']} · {short(r['Address'])}"] = r["Address"]
MANUAL = "✏️ Enter a contract address manually"
choice = st.selectbox("Choose a contract", list(options.keys()) + [MANUAL])
if choice == MANUAL:
    addr = st.text_input("Contract address (0x…)", "", key="sc_manual").strip() or None
else:
    addr = options[choice]

if addr:
    info = sc(get_contract, addr, default=None, label="Blockscout contract")
    smart = (info or {}).get("sc") or {}
    ainfo = (info or {}).get("addr") or {}
    counters = (info or {}).get("counters") or {}

    if not smart and not ainfo:
        st.info("No data returned for this address. Check that it is a valid Base address.")
    else:
        is_contract = ainfo.get("is_contract", True)
        verified = bool(smart)
        name = smart.get("name") or ainfo.get("name") or "(unnamed)"
        st.markdown(f"**{name}**  ·  `{addr}`")
        if not is_contract:
            st.warning("This address is not a contract (it looks like a regular wallet).")
        elif not verified:
            st.warning("This contract is **not verified** on Blockscout: its source code is not publicly "
                       "available here, so ABI and source views are empty.")

        bal = safe_float(ainfo.get("coin_balance"))
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Verified", "Yes" if verified else "No")
        m2.metric("Transactions", fmt_num(to_int(counters.get("transactions_count"))))
        m3.metric("Token Transfers", fmt_num(to_int(counters.get("token_transfers_count"))))
        m4.metric("ETH Balance", f"{bal / 1e18:,.4f}" if bal is not None else "N/A")

        view = st.radio("View", ["Overview & Source", "ABI", "Recent Activity"], horizontal=True, key="sc_view")

        # ------------------------------------------------------------
        if view == "Overview & Source":
            rows = []
            if smart:
                rows += [
                    ("Language", (smart.get("language") or "N/A").capitalize()),
                    ("Compiler", smart.get("compiler_version") or "N/A"),
                    ("EVM version", smart.get("evm_version") or "N/A"),
                    ("Optimization", ("Enabled" + (f" ({smart.get('optimization_runs')} runs)"
                                                  if smart.get("optimization_runs") is not None else ""))
                     if smart.get("optimization_enabled") else "Disabled"),
                    ("License", smart.get("license_type") or "N/A"),
                    ("Verified at", (smart.get("verified_at") or "N/A")[:10]),
                    ("Verified via Sourcify", "Yes" if smart.get("is_verified_via_sourcify") else "No"),
                    ("Fully verified", "Yes" if smart.get("is_fully_verified") else
                     ("Partially" if smart.get("is_partially_verified") else "N/A")),
                ]
            creator = ainfo.get("creator_address_hash")
            ctx = ainfo.get("creation_transaction_hash") or ainfo.get("creation_tx_hash")
            if creator:
                rows.append(("Creator", creator))
            if ctx:
                rows.append(("Creation transaction", ctx))
            proxy_type = ainfo.get("proxy_type") or smart.get("proxy_type")
            impls = ainfo.get("implementations") or smart.get("implementations") or []
            if proxy_type:
                rows.append(("Proxy type", str(proxy_type)))
            for im in impls:
                rows.append(("Implementation", f"{im.get('name') or ''} {im.get('address_hash') or im.get('address') or ''}".strip()))
            if rows:
                show_table(pd.DataFrame(rows, columns=["Property", "Value"]))
            if impls:
                st.info("This looks like a proxy contract. The logic lives in the implementation address(es) above, "
                        "which can be changed by whoever controls the proxy admin if the proxy is upgradeable.")

            if smart:
                files = []
                if smart.get("source_code"):
                    files.append((smart.get("file_path") or f"{name}.sol", smart["source_code"]))
                for f in smart.get("additional_sources") or []:
                    files.append((f.get("file_path") or "additional", f.get("source_code") or ""))
                if files:
                    st.markdown("**Source files**")
                    ftab = pd.DataFrame([{"File": p, "Lines": src.count("\n") + 1, "Characters": len(src)} for p, src in files])
                    show_table(ftab)
                    pick = st.selectbox("View file", [p for p, _ in files], key="sc_file")
                    code = dict(files)[pick]
                    limit = 80_000
                    lang_code = "solidity" if (smart.get("language") or "").lower() == "solidity" else "python"
                    st.code(code[:limit], language=lang_code)
                    if len(code) > limit:
                        st.caption(f"Showing the first {limit:,} characters of {len(code):,}.")
                if smart.get("decoded_constructor_args"):
                    with st.expander("Decoded constructor arguments"):
                        st.json(smart["decoded_constructor_args"])
                elif smart.get("constructor_args"):
                    with st.expander("Constructor arguments (raw)"):
                        st.code(smart["constructor_args"][:5000])

        # ------------------------------------------------------------
        elif view == "ABI":
            abi = smart.get("abi") if smart else None
            if abi:
                funcs, events, n_err = parse_abi(abi)
                a1, a2, a3, a4 = st.columns(4)
                a1.metric("Functions", f"{len(funcs)}")
                a2.metric("Read / Write", f"{int((funcs['Kind'] == 'Read').sum()) if not funcs.empty else 0} / "
                                          f"{int((funcs['Kind'] == 'Write').sum()) if not funcs.empty else 0}")
                a3.metric("Events", f"{len(events)}")
                a4.metric("Custom Errors", f"{n_err}")

                al, ar = st.columns(2)
                with al:
                    if not funcs.empty:
                        mut = funcs["Mutability"].value_counts().reset_index()
                        mut.columns = ["Mutability", "Functions"]
                        fig = px.pie(mut, names="Mutability", values="Functions", hole=0.5,
                                     color_discrete_sequence=BLUE_SPECTRUM, title="Functions by State Mutability")
                        fig.update_traces(textposition="inside", textinfo="percent+label")
                        fig.update_layout(height=360, margin=dict(l=10, r=10, t=50, b=10))
                        show_chart(fig)
                with ar:
                    scan = privilege_scan(funcs) if not funcs.empty else pd.DataFrame()
                    st.markdown("**Privileged-function keyword scan**")
                    if scan.empty:
                        st.caption("No state-changing functions matched the keyword list.")
                    else:
                        show_table(scan)
                    st.caption("A simple name-based heuristic over state-changing functions (owner, upgrade, mint, "
                               "pause, withdraw, …). It does NOT read the code or check who controls these "
                               "functions — it is not an audit.")

                if not funcs.empty:
                    st.markdown("**Functions**")
                    kind = st.multiselect("Show", ["Read", "Write"], default=["Read", "Write"], key="abi_kind")
                    show_table(funcs[funcs["Kind"].isin(kind)])
                if not events.empty:
                    st.markdown("**Events**")
                    show_table(events)
                st.download_button("⬇️ Download ABI (JSON)", json.dumps(abi, indent=2),
                                   file_name=f"{name}_abi.json", mime="application/json")
            else:
                st.info("No ABI is available (the contract is not verified, or Blockscout did not return one).")

        # ------------------------------------------------------------
        else:
            pcount = st.selectbox("Items to load", [50, 100], index=0, key="sc_act_n")
            tdf = sc(get_contract_txs, addr, pcount // 50, default=pd.DataFrame(), label="Blockscout contract transactions")
            if tdf is not None and not tdf.empty:
                span = (tdf["Time (UTC)"].max() - tdf["Time (UTC)"].min()).total_seconds()
                r1, r2, r3, r4 = st.columns(4)
                r1.metric("Calls Loaded", f"{len(tdf)}")
                r2.metric("Success Rate", f"{(tdf['Status'] == 'Success').mean() * 100:.1f}%")
                r3.metric("Unique Callers", f"{tdf['From'].nunique()}")
                r4.metric("Sample Time Span", f"{span / 60:,.1f} min" if span else "N/A")

                cl, cr = st.columns(2)
                with cl:
                    mm = tdf["Method"].value_counts().head(10).sort_values().reset_index()
                    mm.columns = ["Method", "Calls"]
                    fig = go.Figure(go.Bar(x=mm["Calls"], y=mm["Method"], orientation="h", marker_color=ACCENT))
                    fig.update_layout(title="Most Called Methods (in sample)", height=380,
                                      margin=dict(l=10, r=20, t=50, b=10), xaxis_title="Calls", plot_bgcolor="white")
                    show_chart(fig)
                with cr:
                    cc = tdf["From"].value_counts().head(10).sort_values().reset_index()
                    cc.columns = ["Caller", "Calls"]
                    cc["Caller"] = cc["Caller"].apply(short)
                    fig = go.Figure(go.Bar(x=cc["Calls"], y=cc["Caller"], orientation="h", marker_color=ACCENT))
                    fig.update_layout(title="Top Callers (in sample)", height=380,
                                      margin=dict(l=10, r=20, t=50, b=10), xaxis_title="Calls", plot_bgcolor="white")
                    show_chart(fig)

                disp = tdf.copy()
                disp["Time (UTC)"] = disp["Time (UTC)"].dt.strftime("%Y-%m-%d %H:%M:%S")
                disp["From"] = disp["From"].apply(short)
                disp["Tx"] = disp["Tx"].apply(short)
                show_table(disp.head(30), column_config={
                    "Value (ETH)": st.column_config.NumberColumn(format="%.6f"),
                    "Fee (ETH)": st.column_config.NumberColumn(format="%.8f"),
                    "Gas Used": st.column_config.NumberColumn(format="%d")})
            else:
                st.info("No recent transactions to this address were returned.")

            ldf = sc(get_contract_logs, addr, pcount // 50, default=pd.DataFrame(), label="Blockscout contract logs")
            if ldf is not None and not ldf.empty:
                ev = ldf["Event"].value_counts().head(10).sort_values().reset_index()
                ev.columns = ["Event", "Logs"]
                fig = go.Figure(go.Bar(x=ev["Logs"], y=ev["Event"], orientation="h", marker_color=ACCENT))
                fig.update_layout(title="Most Emitted Events (recent logs)", height=360,
                                  margin=dict(l=10, r=20, t=50, b=10), xaxis_title="Logs", plot_bgcolor="white")
                show_chart(fig)
            st.caption("Activity tables show only the most recent items, not the contract's full history.")

st.markdown("---")

# ============================================================
# --- Sources ---
# ============================================================
st.subheader("Sources")
st.markdown(
    """
| Section | Data | Source |
|---|---|---|
| Deployment & verification trends | Daily new contracts, new verified contracts, cumulative totals | [Blockscout – Base](https://base.blockscout.com) · stats service `/stats-service/api/v1/lines/{chart}` (`newContracts`, `newVerifiedContracts`, `contractsGrowth`, `verifiedContractsGrowth`) · [docs](https://docs.blockscout.com/devs/stats-dashboard) |
| Verified contracts explorer | Name, language, compiler, optimization, transactions, balance, verification date | Blockscout · `/api/v2/smart-contracts` (filters `sort`, `order`, `filter`, `q`) |
| Analyzer — overview, source, ABI | Verification metadata, creator, proxy info, source files, ABI | Blockscout · `/api/v2/smart-contracts/{address}`, `/api/v2/addresses/{address}` |
| Analyzer — activity | Counters, recent calls to the contract, recent event logs | Blockscout · `/api/v2/addresses/{address}/counters`, `/transactions`, `/logs` |
| Derived metrics | Verification rate, language / compiler mix, keyword scan of privileged functions | Calculated in this app |
"""
)
st.caption(
    "Notes: contract counts include factory-created contracts. Explorer and activity tables are samples. "
    "Verification is not an audit, and the keyword scan is only a rough hint. Never interact with a contract "
    "based on this dashboard alone. Third-party APIs may change limits or availability at any time."
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
