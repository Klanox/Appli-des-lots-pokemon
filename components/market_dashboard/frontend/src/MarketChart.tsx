import { useMemo, useState } from "react";
import type React from "react";
import type { MarketPeriod, MarketSeries, MarketSnapshot } from "./types";

interface Props {
  series: MarketSeries[];
  snapshots: MarketSnapshot[];
  visibleSeriesIds: string[];
  selectedPeriod: MarketPeriod;
  onSelectSeries: (seriesId: string) => void;
}

const PERIOD_DAYS: Record<MarketPeriod, number | null> = {
  "1m": 31,
  "3m": 92,
  "6m": 183,
  "1y": 366,
  all: null,
};

function snapshotDate(snapshot: MarketSnapshot): Date | null {
  const raw = snapshot.captured_at || snapshot.date;
  if (!raw) return null;
  const dt = new Date(raw);
  return Number.isNaN(dt.valueOf()) ? null : dt;
}

function filterPeriod(snapshots: MarketSnapshot[], period: MarketPeriod): MarketSnapshot[] {
  const days = PERIOD_DAYS[period];
  if (!days) return snapshots;
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return snapshots.filter((snap) => {
    const dt = snapshotDate(snap);
    return dt ? dt.valueOf() >= cutoff : false;
  });
}

function niceTicks(min: number, max: number, count: number): number[] {
  if (!Number.isFinite(min) || !Number.isFinite(max) || min === max) return [];
  const step = (max - min) / Math.max(1, count - 1);
  return Array.from({ length: count }, (_, index) => min + step * index);
}

export function MarketChart({ series, snapshots, visibleSeriesIds, selectedPeriod, onSelectSeries }: Props) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState(0);
  const width = 1200;
  const height = 620;
  const pad = { left: 58, right: 62, top: 18, bottom: 44 };
  const innerW = width - pad.left - pad.right;
  const innerH = height - pad.top - pad.bottom;

  const traces = useMemo(() => {
    const filtered = filterPeriod(snapshots, selectedPeriod);
    return series
      .filter((item) => visibleSeriesIds.includes(item.set_id))
      .map((item) => {
        const points = filtered
          .filter((snap) => (snap.set_id || "").toUpperCase() === item.set_id.toUpperCase() && snap.vmc_eur != null)
          .map((snap) => ({ date: snapshotDate(snap), value: Number(snap.vmc_eur) }))
          .filter((point) => point.date && Number.isFinite(point.value))
          .sort((a, b) => (a.date as Date).valueOf() - (b.date as Date).valueOf());
        return { series: item, points };
      })
      .filter((trace) => trace.points.length > 0);
  }, [series, snapshots, visibleSeriesIds, selectedPeriod]);

  const domain = useMemo(() => {
    const allPoints = traces.flatMap((trace) => trace.points);
    if (!allPoints.length) return null;
    const minT = Math.min(...allPoints.map((point) => (point.date as Date).valueOf()));
    const maxT = Math.max(...allPoints.map((point) => (point.date as Date).valueOf()));
    const minY = Math.min(...allPoints.map((point) => point.value));
    const maxY = Math.max(...allPoints.map((point) => point.value));
    const yPad = Math.max(0.2, (maxY - minY) * 0.12);
    const span = Math.max(1, maxT - minT);
    const visibleSpan = span / zoom;
    const panMax = span - visibleSpan;
    const offset = Math.max(0, Math.min(panMax, pan * span));
    return {
      minT: minT + offset,
      maxT: minT + offset + visibleSpan,
      minY: Math.max(0, minY - yPad),
      maxY: maxY + yPad,
    };
  }, [traces, zoom, pan]);

  const hasData = traces.length > 0 && domain;

  const xScale = (time: number) => {
    if (!domain) return pad.left;
    return pad.left + ((time - domain.minT) / Math.max(1, domain.maxT - domain.minT)) * innerW;
  };
  const yScale = (value: number) => {
    if (!domain) return pad.top + innerH;
    return pad.top + innerH - ((value - domain.minY) / Math.max(0.01, domain.maxY - domain.minY)) * innerH;
  };

  const handleWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    if (!hasData) return;
    event.preventDefault();
    setZoom((current) => Math.max(1, Math.min(8, current + (event.deltaY < 0 ? 0.25 : -0.25))));
  };

  const handlePointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    if (!hasData || event.buttons !== 1) return;
    setPan((current) => Math.max(0, Math.min(1, current - event.movementX / innerW / Math.max(1, zoom))));
  };

  const yTicks = domain ? niceTicks(domain.minY, domain.maxY, 7) : [];
  const xTicks = domain ? niceTicks(domain.minT, domain.maxT, 7) : [];

  return (
    <div className="mk-chart">
      <svg viewBox={`0 0 ${width} ${height}`} onWheel={handleWheel} onPointerMove={handlePointerMove} role="img">
        <rect x="0" y="0" width={width} height={height} rx="0" fill="#171b2a" />
        {hasData ? (
          <>
            {yTicks.map((tick) => (
              <g key={`y-${tick}`}>
                <line x1={pad.left} x2={width - pad.right} y1={yScale(tick)} y2={yScale(tick)} className="mk-grid-line" />
                <text x={pad.left - 10} y={yScale(tick) + 4} className="mk-axis-label" textAnchor="end">
                  {tick.toFixed(2)} €
                </text>
                <text x={width - pad.right + 10} y={yScale(tick) + 4} className="mk-axis-label" textAnchor="start">
                  {tick.toFixed(2)} €
                </text>
              </g>
            ))}
            {xTicks.map((tick) => {
              const dt = new Date(tick);
              const label = `${String(dt.getMonth() + 1).padStart(2, "0")}/${String(dt.getFullYear()).slice(2)}`;
              return (
                <g key={`x-${tick}`}>
                  <line x1={xScale(tick)} x2={xScale(tick)} y1={pad.top} y2={height - pad.bottom} className="mk-grid-line" />
                  <text x={xScale(tick)} y={height - 14} className="mk-axis-label" textAnchor="middle">
                    {label}
                  </text>
                </g>
              );
            })}
            {traces.map((trace) => {
              const points = trace.points
                .filter((point) => (point.date as Date).valueOf() >= domain.minT && (point.date as Date).valueOf() <= domain.maxT)
                .map((point) => [xScale((point.date as Date).valueOf()), yScale(point.value), point.value] as const);
              if (points.length < 2) return null;
              const path = points.map(([x, y], index) => `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
              const last = points[points.length - 1];
              return (
                <g key={trace.series.set_id} onClick={() => onSelectSeries(trace.series.set_id)} className="mk-series-path">
                  <path d={path} fill="none" stroke={trace.series.color} strokeWidth="2.5" />
                  {points.map(([x, y], index) => (
                    <circle key={index} cx={x} cy={y} r="3.4" fill={trace.series.color} stroke="#dbeafe" strokeWidth="0.8" />
                  ))}
                  <text x={last[0] + 8} y={last[1] + 4} fill={trace.series.color} className="mk-end-label">
                    {last[2].toFixed(2)}
                  </text>
                </g>
              );
            })}
          </>
        ) : (
          <g>
            <text x={width / 2} y={height / 2 - 10} className="mk-empty-title" textAnchor="middle">
              Aucune VMC calculable pour le moment
            </text>
            <text x={width / 2} y={height / 2 + 18} className="mk-empty-subtitle" textAnchor="middle">
              Configure les pull rates et une source de prix fiable pour commencer l’historique.
            </text>
          </g>
        )}
      </svg>
    </div>
  );
}
