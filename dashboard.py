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


def _filtered(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    work = df.copy()
    priorities = sorted(p for p in work.get("market_priority", pd.Series(dtype=str)).dropna().unique() if p)
    tiers = sorted(t for t in work.get("tier", pd.Series(dtype=str)).dropna().unique() if t)
    zips = sorted(str(z) for z in work.get("zip_code", pd.Series(dtype=str)).dropna().unique() if str(z))

    cols = st.columns(4)
    with cols[0]:
        priority = st.multiselect("Mercado", priorities, default=priorities)
    with cols[1]:
        tier = st.multiselect("Segmento", tiers, default=tiers)
    with cols[2]:
        zip_code = st.multiselect("ZIP", zips, default=zips)
    with cols[3]:
        only_viable = st.toggle("Somente viáveis", value=False)

    if priority and "market_priority" in work:
        work = work[work["market_priority"].fillna("").isin(priority)]
    if tier and "tier" in work:
        work = work[work["tier"].fillna("").isin(tier)]
    if zip_code and "zip_code" in work:
        work = work[work["zip_code"].fillna("").astype(str).isin(zip_code)]
    if only_viable and "is_viable" in work:
        work = work[work["is_viable"].fillna("").astype(str).str.lower().isin(["yes", "true", "1"])]
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
        viable = str(row.get("is_viable", "yes")).lower() in {"yes", "true", "1"}
        color = "green" if viable else "red"
        popup = "<br>".join([
            f"<b>{row.get('address', row.get('id', ''))}</b>",
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
    dataset = evaluations if not evaluations.empty else opportunities

    if dataset.empty:
        st.info("Ainda não há avaliações registradas. Rode uma varredura para alimentar o painel.")
        return

    total = len(dataset)
    viable = 0
    if "is_viable" in dataset:
        viable = int(dataset["is_viable"].fillna("").astype(str).str.lower().isin(["yes", "true", "1"]).sum())
    elif not opportunities.empty:
        viable = len(opportunities)
    rejected = max(total - viable, 0)

    cols = st.columns(5)
    cols[0].metric("Avaliações", total)
    cols[1].metric("Viáveis", viable)
    cols[2].metric("Reprovadas", rejected)
    cols[3].metric("Maior lucro", _money(dataset.get("profit", pd.Series(dtype=float)).max()))
    cols[4].metric("Maior margem", _pct(dataset.get("margin", pd.Series(dtype=float)).max()))

    filtered = _filtered(dataset)
    tab_map, tab_table, tab_rejected = st.tabs(["Mapa", "Tabela", "Reprovações"])
    with tab_map:
        _render_map(filtered)
    with tab_table:
        columns = [
            c for c in [
                "found_at", "is_viable", "address", "zip_code", "market_priority",
                "market_region", "tier", "land_price", "arv", "profit", "margin",
                "risk_flags", "url",
            ] if c in filtered.columns
        ]
        st.dataframe(filtered[columns], use_container_width=True, hide_index=True)
    with tab_rejected:
        if "is_viable" in filtered.columns:
            rejected_df = filtered[
                ~filtered["is_viable"].fillna("").astype(str).str.lower().isin(["yes", "true", "1"])
            ]
        else:
            rejected_df = pd.DataFrame()
        if rejected_df.empty:
            st.info("Nenhuma reprovação registrada no filtro atual.")
        else:
            columns = [
                c for c in [
                    "found_at", "address", "zip_code", "market_priority", "tier",
                    "land_price", "margin", "risk_flags", "reasons",
                ] if c in rejected_df.columns
            ]
            st.dataframe(rejected_df[columns], use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
