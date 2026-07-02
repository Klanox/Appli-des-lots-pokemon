import type { MarketSeries, VariationSort } from "./types";
import { VariationList } from "./VariationList";

interface Props {
  series?: MarketSeries;
  sort: VariationSort;
  hasExactSource: boolean;
  onSortChange: (sort: VariationSort) => void;
}

export function SeriesPanel({ series, sort, hasExactSource, onSortChange }: Props) {
  if (!series) {
    return (
      <aside className="mk-side-panel">
        <div className="mk-panel-title">Survoler une série</div>
        <p className="mk-panel-help">Passez la souris sur une courbe ou choisissez une série dans la légende.</p>
      </aside>
    );
  }

  return (
    <aside className="mk-side-panel">
      <div className="mk-panel-header">
        <div className="mk-panel-name">
          <span className="mk-dot" style={{ background: series.color, color: series.color }} />
          <strong>{series.name_fr || series.set_id}</strong>
        </div>
        <span>Aucune période disponible</span>
      </div>
      <div className="mk-panel-vmc">
        <div className="mk-label">VMC indisponible</div>
        <div className="mk-panel-big">--</div>
        <div className="mk-panel-muted">
          {hasExactSource
            ? "Pull rates ou couverture de prix manquants."
            : "Source de prix exacte indisponible."}
        </div>
        <div className="mk-panel-meta">
          <span>Set {series.set_id || "-"}</span>
          <span>{series.cards_count || 0} cartes connues</span>
        </div>
      </div>
      <VariationList sort={sort} onSortChange={onSortChange} />
    </aside>
  );
}
