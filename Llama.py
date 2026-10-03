"""Shared DefiLlama fetchers for the TVL, Fees & Revenue and Protocol Analyzer pages."""
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timezone

from common import empty_ts

LLAMA = "https://api.llama.fi"   

# Categories DefiLlama tracks but does NOT count toward a chain's headline TVL
EXCLUDED_FROM_CHAIN_TVL = {"Liquid Staking", "Bridge", "Onchain Capital Allocator", "Risk Curators"}


def get_json(url, params=None, timeout=60):
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def llama_series(arr) -> pd.DataFrame:
    """[[timestamp, value], ...] -> DataFrame(date, value)"""
    if not arr:
        return empty_ts()
    df = pd.DataFrame(arr, columns=["date", "value"])
    df["date"] = pd.to_datetime(df["date"], unit="s")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.sort_values("date").reset_index(drop=True)


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


@st.cache_data(ttl=3600, show_spinner=False)
def get_fees(chain: str, data_type: str) -> dict:
    """data_type = 'dailyFees' or 'dailyRevenue'."""
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
