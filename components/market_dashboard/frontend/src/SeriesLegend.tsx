import type { MarketSeries } from "./types";

interface Props {
  series: MarketSeries[];
  visibleSeriesIds: string[];
  selectedSeriesId: string;
  onToggleSeries: (seriesId: string) => void;
  onIsolateSeries: (seriesId: string) => void;
  onShowAll: () => void;
  onHideAll: () => void;
}

export function SeriesLegend({
  series,
  visibleSeriesIds,
  selectedSeriesId,
  onToggleSeries,
  onIsolateSeries,
  onShowAll,
  onHideAll,
}: Props) {
  return (
    <div className="mk-legend-wrap">
      <div className="mk-legend-actions">
        <span>Légende</span>
        <button onClick={onShowAll}>Toutes</button>
        <button onClick={onHideAll}>Aucune</button>
      </div>
      <div className="mk-legend-grid">
        {series.map((item) => {
          const visible = visibleSeriesIds.includes(item.set_id);
          const selected = selectedSeriesId === item.set_id;
          const pullStatus = item.pull_rate_status || "missing";
          return (
            <button
              key={item.set_id}
              className={`mk-legend-item ${visible ? "visible" : "muted"} ${selected ? "selected" : ""}`}
              onClick={() => onToggleSeries(item.set_id)}
              onDoubleClick={() => onIsolateSeries(item.set_id)}
              title="Cliquer pour afficher/masquer. Double-clic pour isoler."
            >
              <span className="mk-dot" style={{ background: item.color, color: item.color }} />
              <span className="mk-legend-name">{item.name_fr || item.set_id}</span>
              <span className="mk-legend-badges">
                <span className="mk-count">{item.cards_count ? `${item.cards_count} cartes` : "0 carte"}</span>
                <span className={`mk-rate-badge ${pullStatus}`}>{item.pull_rate_label || "Non renseigné"}</span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
