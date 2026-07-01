"""Streamlit dashboard for Orlando Land Detector."""

from __future__ import annotations

from pathlib import Path

import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
import yaml


ROOT = Path(__file__).resolve().parent


@st.cache_data(show_spinner=False)
def _load_config() -> dict:
    path = ROOT / "config.yaml"
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


@st.cache_data(show_spinner=False)
def _load_csv(path: str) -> pd.DataFrame:
    csv_path = ROOT / path
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_csv(csv_path)


def _money(value) -> str:
    try:
        return f"US$ {float(value):,.0f}"
    except (TypeError, ValueError):
        return "n/d"


def _pct(value) -> str:
    try:
        return f"{float(value):.1%}"
    except (TypeError, ValueError):
        return "n/d"


def _is_truthy(value) -> bool:
    return str(value).lower() in {"yes", "true", "1"}


def _infer_review_status(row: pd.Series) -> str:
    if _is_truthy(row.get("is_viable", "")):
        return "viavel"
    reasons = str(row.get("reasons", "") or "").lower()
    fatal_parts = [part.strip() for part in reasons.split("|") if part.strip().startswith("✗")]
    allowed_zone = "zoneamento desconhecido"
    disallowed = [part for part in fatal_parts if allowed_zone not in part]
    margin = row.get("margin", "")
    profit = row.get("profit", "")
    try:
        numbers_ok = float(margin) > 0 and float(profit) > 0
    except (TypeError, ValueError):
        numbers_ok = False
    if numbers_ok and "zoneamento desconhecido" in reasons and not disallowed:
        return "radar_zoneamento_pendente"
    if numbers_ok and ("análise manual" in reasons or "analise manual" in reasons) and not disallowed:
        return "radar_analise_manual"
    return "reprovado"


def _with_review_status(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    if "review_status" not in work.columns:
        work["review_status"] = ""
    inferred = work.apply(_infer_review_status, axis=1)
    work["review_status"] = work["review_status"].fillna("").astype(str)
    work.loc[work["review_status"].str.strip() == "", "review_status"] = inferred
    if "review_reason" not in work.columns:
        work["review_reason"] = ""
    return work


def _filtered(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    priorities = sorted(p for p in work.get("market_priority", pd.Series(dtype=str)).dropna().unique() if p)
    tiers = sorted(t for t in work.get("tier", pd.Series(dtype=str)).dropna().unique() if t)
    zips = sorted(str(z) for z in work.get("zip_code", pd.Series(dtype=str)).dropna().unique() if str(z))
    statuses = sorted(s for s in work.get("review_status", pd.Series(dtype=str)).dropna().unique() if s)

    cols = st.columns(5)
    with cols[0]:
        priority = st.multiselect("Mercado", priorities, default=priorities)
    with cols[1]:
        tier = st.multiselect("Segmento", tiers, default=tiers)
    with cols[2]:
        zip_code = st.multiselect("ZIP", zips, default=zips)
    with cols[3]:
        only_viable = st.toggle("Somente viáveis", value=False)
    with cols[4]:
        status = st.multiselect("Status", statuses, default=statuses)

    if priority and "market_priority" in work:
        work = work[work["market_priority"].fillna("").isin(priority)]
    if tier and "tier" in work:
        work = work[work["tier"].fillna("").isin(tier)]
    if zip_code and "zip_code" in work:
        work = work[work["zip_code"].fillna("").astype(str).isin(zip_code)]
    if only_viable and "is_viable" in work:
        work = work[work["is_viable"].fillna("").astype(str).str.lower().isin(["yes", "true", "1"])]
    if status and "review_status" in work:
        work = work[work["review_status"].fillna("").isin(status)]
    return work


def _render_map(df: pd.DataFrame) -> None:
    if df.empty:
        st.info("Ainda não há dados para mapa.")
        return
    if "lat" not in df.columns or "lng" not in df.columns:
        st.info("O CSV atual ainda não tem lat/lng para mapa. As próximas avaliações serão exibidas na tabela.")
        return
    points = df.dropna(subset=["lat", "lng"])
    if points.empty:
        st.info("Nenhuma linha com coordenadas válidas para mapa.")
        return

    center = [points["lat"].astype(float).mean(), points["lng"].astype(float).mean()]
    fmap = folium.Map(location=center, zoom_start=9, tiles="CartoDB positron")
    for _, row in points.iterrows():
        review_status = str(row.get("review_status", ""))
        viable = _is_truthy(row.get("is_viable", "yes"))
        color = "green" if viable else "orange" if review_status.startswith("radar_") else "red"
        popup = "<br>".join([
            f"<b>{row.get('address', row.get('id', ''))}</b>",
            f"Status: {row.get('review_status', 'n/d')}",
            f"Mercado: {row.get('market_priority', 'n/d')}",
            f"ZIP: {row.get('zip_code', 'n/d')}",
            f"Terreno: {_money(row.get('land_price'))}",
            f"Lucro: {_money(row.get('profit'))}",
            f"Margem: {_pct(row.get('margin'))}",
            f"Atenções: {row.get('risk_flags', '')}",
            f"Motivos: {row.get('reasons', '')}",
        ])
        folium.CircleMarker(
            location=[float(row["lat"]), float(row["lng"])],
            radius=7,
            color=color,
            fill=True,
            fill_opacity=0.75,
            popup=folium.Popup(popup, max_width=420),
        ).add_to(fmap)
    components.html(fmap._repr_html_(), height=620)


def main() -> None:
    st.set_page_config(page_title="Orlando Land Detector", layout="wide")
    st.title("Orlando Land Detector")

    cfg = _load_config()
    output = cfg.get("output", {})
    opportunities = _load_csv(output.get("csv_path", "opportunities.csv"))
    evaluations = _load_csv(output.get("evaluations_csv_path", "evaluations.csv"))
    dataset = _with_review_status(evaluations if not evaluations.empty else opportunities)

    if dataset.empty:
        st.info("Ainda não há avaliações registradas. Rode uma varredura para alimentar o painel.")
        return

    total = len(dataset)
    viable = 0
    if "is_viable" in dataset:
        viable = int(dataset["is_viable"].fillna("").astype(str).str.lower().isin(["yes", "true", "1"]).sum())
    elif not opportunities.empty:
        viable = len(opportunities)
    radar = int(dataset.get("review_status", pd.Series(dtype=str)).fillna("").astype(str).str.startswith("radar_").sum())
    rejected = max(total - viable - radar, 0)

    cols = st.columns(5)
    cols[0].metric("Avaliações", total)
    cols[1].metric("Viáveis", viable)
    cols[2].metric("Radar", radar)
    cols[3].metric("Reprovadas", rejected)
    cols[4].metric("Maior margem", _pct(dataset.get("margin", pd.Series(dtype=float)).max()))

    filtered = _filtered(dataset)
    tab_map, tab_radar, tab_table, tab_rejected = st.tabs(["Mapa", "Radar", "Tabela", "Reprovações"])
    with tab_map:
        _render_map(filtered)
    with tab_radar:
        radar_df = filtered[
            filtered.get("review_status", pd.Series(dtype=str)).fillna("").astype(str).str.startswith("radar_")
        ]
        if radar_df.empty:
            st.info("Nenhum candidato no Radar para o filtro atual.")
        else:
            columns = [
                c for c in [
                    "found_at", "review_status", "review_reason", "address", "zip_code",
                    "market_priority", "tier", "land_price", "arv", "profit", "margin",
                    "risk_flags", "reasons", "url",
                ] if c in radar_df.columns
            ]
            st.dataframe(radar_df[columns], width="stretch", hide_index=True)
    with tab_table:
        columns = [
            c for c in [
                "found_at", "is_viable", "review_status", "address", "zip_code", "market_priority",
                "market_region", "tier", "land_price", "arv", "profit", "margin",
                "risk_flags", "url",
            ] if c in filtered.columns
        ]
        st.dataframe(filtered[columns], width="stretch", hide_index=True)
    with tab_rejected:
        if "is_viable" in filtered.columns:
            rejected_df = filtered[
                ~filtered["is_viable"].fillna("").astype(str).str.lower().isin(["yes", "true", "1"])
            ]
            if "review_status" in rejected_df.columns:
                rejected_df = rejected_df[
                    ~rejected_df["review_status"].fillna("").astype(str).str.startswith("radar_")
                ]
        else:
            rejected_df = pd.DataFrame()
        if rejected_df.empty:
            st.info("Nenhuma reprovação registrada no filtro atual.")
        else:
            columns = [
                c for c in [
                    "found_at", "review_status", "review_reason", "address", "zip_code", "market_priority", "tier",
                    "land_price", "margin", "risk_flags", "reasons",
                ] if c in rejected_df.columns
            ]
            st.dataframe(rejected_df[columns], width="stretch", hide_index=True)


if __name__ == "__main__":
    main()
