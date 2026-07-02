import React, { useEffect, useMemo, useState } from "react";
import { createRoot } from "react-dom/client";
import { Streamlit, withStreamlitConnection, ComponentProps } from "streamlit-component-lib";
import { MarketChart } from "./MarketChart";
import { MarketControls } from "./MarketControls";
import { SeriesLegend } from "./SeriesLegend";
import { SeriesPanel } from "./SeriesPanel";
import type { MarketCard, MarketDashboardData, MarketDashboardState, MarketPeriod, MarketView, VariationSort } from "./types";
import "./market-dashboard.css";

function defaultState(data: MarketDashboardData): MarketDashboardState {
  const seriesIds = (data.series || []).slice(0, 6).map((item) => item.set_id);
  return {
    view: data.initial_state?.view || "vmc",
    selected_period: data.initial_state?.selected_period || "all",
    visible_series_ids: data.initial_state?.visible_series_ids?.length ? data.initial_state.visible_series_ids : seriesIds,
    selected_series_id: data.initial_state?.selected_series_id || seriesIds[0] || "",
    variation_sort: data.initial_state?.variation_sort || "eur",
    open_card_id: data.initial_state?.open_card_id || "",
    open_series_id: data.initial_state?.open_series_id || "",
    search_query: data.initial_state?.search_query || "",
    search_language: data.initial_state?.search_language || "fr",
  };
}

function MarketDashboardBase(props: ComponentProps) {
  const data = (props.args?.data || {}) as MarketDashboardData;
  const [state, setState] = useState<MarketDashboardState>(() => defaultState(data));

  useEffect(() => {
    Streamlit.setFrameHeight();
  });

  useEffect(() => {
    Streamlit.setComponentValue(state);
  }, [state]);

  const series = data.series || [];
  const selectedSeries = series.find((item) => item.set_id === state.selected_series_id) || series[0];
  const hasExactSource = Boolean(data.source_audit?.exact_cardmarket_fr_nm_available);

  const setPartial = (patch: Partial<MarketDashboardState>) => {
    setState((current) => ({ ...current, ...patch }));
  };

  const showAll = () => {
    setPartial({ visible_series_ids: series.slice(0, 6).map((item) => item.set_id) });
  };

  const hideAll = () => {
    setPartial({ visible_series_ids: [] });
  };

  const toggleSeries = (seriesId: string) => {
    setState((current) => {
      const visible = current.visible_series_ids.includes(seriesId);
      const nextIds = visible
        ? current.visible_series_ids.filter((item) => item !== seriesId)
        : [...current.visible_series_ids, seriesId].slice(-6);
      return { ...current, visible_series_ids: nextIds, selected_series_id: seriesId, open_series_id: seriesId };
    });
  };

  const filteredCards = useMemo(() => {
    const query = state.search_query.trim().toLowerCase();
    const language = state.search_language;
    return (data.cards || [])
      .filter((card) => (card.language || "fr").toLowerCase() === language)
      .filter((card) => {
        if (!query) return true;
        return [card.name, card.number, card.set_id, card.set_name, card.rarity, card.variant]
          .filter(Boolean)
          .join(" ")
          .toLowerCase()
          .includes(query);
      })
      .slice(0, 12);
  }, [data.cards, state.search_language, state.search_query]);

  const addToWatchlist = (card: MarketCard) => {
    setPartial({
      open_card_id: card.card_key,
      watchlist_action: { id: `${Date.now()}-${card.card_key}`, action: "add", card_key: card.card_key },
    });
  };

  return (
    <div className="mk-shell">
      <MarketControls
        view={state.view}
        period={state.selected_period}
        onViewChange={(view: MarketView) => setPartial({ view })}
        onPeriodChange={(selected_period: MarketPeriod) => setPartial({ selected_period })}
      />

      {state.view === "vmc" ? (
        <section className="mk-dashboard" id="market_layout_target">
          <div className="mk-main-card">
            <div className="mk-chart-head">
              <div>
                <h2>Évolution VMC <span>€ / booster · molette pour zoomer</span></h2>
                <p>Valeur moyenne contenue estimée par booster standard.</p>
              </div>
            </div>
            <MarketChart
              series={series}
              snapshots={data.snapshots || []}
              visibleSeriesIds={state.visible_series_ids}
              selectedPeriod={state.selected_period}
              onSelectSeries={(selected_series_id) => setPartial({ selected_series_id, open_series_id: selected_series_id })}
            />
            <SeriesLegend
              series={series}
              visibleSeriesIds={state.visible_series_ids}
              selectedSeriesId={state.selected_series_id}
              onToggleSeries={toggleSeries}
              onIsolateSeries={(seriesId) =>
                setPartial({ visible_series_ids: [seriesId], selected_series_id: seriesId, open_series_id: seriesId })
              }
              onShowAll={showAll}
              onHideAll={hideAll}
            />
          </div>
          <SeriesPanel
            series={selectedSeries}
            sort={state.variation_sort}
            hasExactSource={hasExactSource}
            onSortChange={(variation_sort: VariationSort) => setPartial({ variation_sort })}
          />
        </section>
      ) : (
        <section className="mk-card-tracking">
          <div className="mk-card-top">
            <div>
              <h2>Top 10 des plus grosses variations</h2>
              <p>Aucun classement réel tant qu’aucun historique fiable n’existe.</p>
            </div>
            <div className="mk-search">
              <div className="mk-lang-toggle">
                <button className={state.search_language === "fr" ? "active" : ""} onClick={() => setPartial({ search_language: "fr" })}>
                  FR
                </button>
                <button className={state.search_language === "ja" ? "active" : ""} onClick={() => setPartial({ search_language: "ja" })}>
                  JP
                </button>
              </div>
              <input
                value={state.search_query}
                onChange={(event) => setPartial({ search_query: event.target.value })}
                placeholder="Nom, numéro, série, rareté ou promo..."
              />
            </div>
          </div>
          <div className="mk-card-layout">
            <div className="mk-results">
              {filteredCards.length ? (
                filteredCards.map((card) => (
                  <button
                    key={card.card_key}
                    className={`mk-card-result ${state.open_card_id === card.card_key ? "active" : ""}`}
                    onClick={() => setPartial({ open_card_id: card.card_key })}
                  >
                    {card.image_url ? <img src={card.image_url} alt="" /> : <span className="mk-card-placeholder">Image indisponible</span>}
                    <span>
                      <strong>{card.name}</strong>
                      <small>
                        #{card.number || "-"} · {card.set_name || card.set_id || "-"} · {card.rarity || "Rareté inconnue"}
                      </small>
                    </span>
                  </button>
                ))
              ) : (
                <div className="mk-empty-box">Aucune carte éligible trouvée dans le registre local.</div>
              )}
            </div>
            <div className="mk-card-detail">
              {filteredCards[0] ? (
                <>
                  <div className="mk-detail-visual">
                    {filteredCards[0].image_url ? <img src={filteredCards[0].image_url} alt="" /> : <div>Image indisponible</div>}
                  </div>
                  <div className="mk-detail-chart">
                    <h3>{filteredCards[0].name}</h3>
                    <p>
                      #{filteredCards[0].number || "-"} · {filteredCards[0].set_name || filteredCards[0].set_id || "-"} ·{" "}
                      {filteredCards[0].rarity || "Rareté inconnue"}
                    </p>
                    <div className="mk-empty-chart">Aucun historique de prix exact disponible.</div>
                    <button onClick={() => addToWatchlist(filteredCards[0])}>Surveiller</button>
                  </div>
                </>
              ) : (
                <div className="mk-empty-box">Recherche une carte pour ouvrir sa fiche marché.</div>
              )}
            </div>
          </div>
        </section>
      )}
    </div>
  );
}

const Connected = withStreamlitConnection(MarketDashboardBase);
const root = createRoot(document.getElementById("root") as HTMLElement);
root.render(
  <React.StrictMode>
    <Connected />
  </React.StrictMode>,
);
