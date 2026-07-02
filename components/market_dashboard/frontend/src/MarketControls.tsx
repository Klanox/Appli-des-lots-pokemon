import type { MarketPeriod, MarketView } from "./types";

interface Props {
  view: MarketView;
  period: MarketPeriod;
  onViewChange: (view: MarketView) => void;
  onPeriodChange: (period: MarketPeriod) => void;
}

const periods: Array<[MarketPeriod, string]> = [
  ["1m", "1 mois"],
  ["3m", "3 mois"],
  ["6m", "6 mois"],
  ["1y", "1 an"],
  ["all", "Depuis le début"],
];

export function MarketControls({ view, period, onViewChange, onPeriodChange }: Props) {
  return (
    <div className="mk-topbar">
      <div className="mk-title-block">
        <div className="mk-kicker">Marché</div>
        <div className="mk-view-tabs" role="tablist" aria-label="Sous-menu Marché">
          <button className={view === "vmc" ? "active" : ""} onClick={() => onViewChange("vmc")}>
            VMC par série
          </button>
          <button className={view === "cards" ? "active" : ""} onClick={() => onViewChange("cards")}>
            Suivi des cartes
          </button>
        </div>
      </div>
      <div className="mk-periods" aria-label="Période">
        {periods.map(([value, label]) => (
          <button key={value} className={period === value ? "active" : ""} onClick={() => onPeriodChange(value)}>
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
