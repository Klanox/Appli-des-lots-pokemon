import type { VariationSort } from "./types";

interface Props {
  sort: VariationSort;
  onSortChange: (sort: VariationSort) => void;
}

export function VariationList({ sort, onSortChange }: Props) {
  return (
    <div className="mk-variations">
      <div className="mk-section-head">
        <span>Plus fortes variations 7 jours</span>
        <div className="mk-sort">
          <button className={sort === "eur" ? "active" : ""} onClick={() => onSortChange("eur")}>
            €
          </button>
          <button className={sort === "pct" ? "active" : ""} onClick={() => onSortChange("pct")}>
            %
          </button>
        </div>
      </div>
      <div className="mk-variation-list">
        <div className="mk-empty-line">
          <strong>Aucun historique de prix exact disponible.</strong>
          <span>Les variations apparaîtront ici quand les snapshots fiables existeront.</span>
        </div>
      </div>
    </div>
  );
}
