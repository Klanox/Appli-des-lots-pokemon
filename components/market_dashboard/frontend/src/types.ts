export type MarketPeriod = "1m" | "3m" | "6m" | "1y" | "all";
export type MarketView = "vmc" | "cards";
export type VariationSort = "eur" | "pct";

export interface MarketSeries {
  set_id: string;
  name_fr: string;
  name_en?: string;
  release_date?: string;
  block?: string;
  color: string;
  active_market?: boolean;
  active_vmc?: boolean;
  is_promo_set?: boolean;
  cards_count?: number;
  pull_rate_status?: "missing" | "incomplete" | "review" | "ready";
  pull_rate_label?: string;
  pull_rate_ready?: boolean;
}

export interface MarketSnapshot {
  set_id?: string;
  captured_at?: string;
  date?: string;
  vmc_eur?: number;
}

export interface MarketCard {
  card_key: string;
  source_card_id?: string;
  name: string;
  number?: string;
  set_id?: string;
  set_name?: string;
  language?: string;
  rarity?: string;
  variant?: string;
  is_promo?: boolean;
  image_url?: string;
  cardmarket_url?: string;
}

export interface SourceAudit {
  exact_cardmarket_fr_nm_available?: boolean;
  status_label?: string;
  explanation?: string;
}

export interface MarketDashboardData {
  series: MarketSeries[];
  snapshots: MarketSnapshot[];
  cards: MarketCard[];
  watchlist_keys: string[];
  source_audit: SourceAudit;
  initial_state?: Partial<MarketDashboardState>;
}

export interface MarketDashboardState {
  view: MarketView;
  selected_period: MarketPeriod;
  visible_series_ids: string[];
  selected_series_id: string;
  variation_sort: VariationSort;
  open_card_id: string;
  open_series_id: string;
  search_query: string;
  search_language: "fr" | "ja";
  watchlist_action?: {
    id: string;
    action: "add";
    card_key: string;
  };
}
