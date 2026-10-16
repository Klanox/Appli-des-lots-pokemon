"""Suivi de progression d'une analyse de photos (Drop Vinted).

Module volontairement sans Streamlit : le moteur appelle un simple callback
``callback(phase, done, total)`` et ce suivi en tire une fraction, un temps écoulé
et une estimation du temps restant. L'interface n'a plus qu'à afficher le résultat.

Le callback n'a aucune influence sur l'analyse : il ne reçoit que des compteurs.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time
from typing import Callable

PHASE_LABELS = {
    "lecture": "Lecture des photos",
    "regroupement": "Regroupement des annonces",
    "reconnaissance": "Reconnaissance des cartes",
    # « Actualiser les cartes du Drop » (phases en une seule étape, sans compteur de photos)
    "candidats": "Lecture du stock et des cartes du Drop",
    "enregistrement": "Enregistrement de l'analyse",
    "statuts": "Mise à jour des statuts du Drop",
    # Regeneration des titres et descriptions (une annonce a la fois)
    "textes": "Régénération des textes",
}

# Unite affichee dans « Libelle · Unite X / N » (« Photo » par defaut).
PHASE_UNITS = {"textes": "Annonce"}

# Phases qui comptent UNE étape (done/total = 0/1 puis 1/1) : texte « Libellé… · écoulé X ».
STEP_PHASES = frozenset({"regroupement", "candidats", "enregistrement", "statuts"})

# Répartition de la barre quand plusieurs phases s'enchaînent (actualisation des cartes du Drop) :
# fraction globale = début + (fin - début) x avancement de la phase.
REFRESH_PHASE_RANGES = {
    "candidats": (0.0, 0.10),
    "reconnaissance": (0.10, 0.85),
    "enregistrement": (0.85, 0.93),
    "statuts": (0.93, 1.0),
}
REFRESH_PHASE_LABELS = {"reconnaissance": "Recalcul de l'analyse"}

DEFAULT_WINDOW = 8        # nombre d'échantillons de la moyenne glissante
DEFAULT_WARMUP = 3        # éléments traités avant d'afficher une estimation
DEFAULT_MIN_INTERVAL = 0.15  # secondes entre deux mises à jour d'affichage


def format_duration(seconds: float | None) -> str:
    """« 45 s », « 1 min 10 s » (arrondi à la seconde)."""
    if seconds is None:
        return ""
    total = max(0, int(round(float(seconds))))
    minutes, secs = divmod(total, 60)
    if minutes <= 0:
        return f"{secs} s"
    return f"{minutes} min {secs:02d} s"


@dataclass(frozen=True)
class ProgressSnapshot:
    phase: str
    label: str
    done: int
    total: int
    fraction: float
    elapsed: float
    eta_seconds: float | None
    estimating: bool
    finished: bool
    text: str


class AnalysisProgress:
    """Callback de progression : ``progress(phase, done, total)``.

    * ``done`` / ``total`` comptent des photos (ou une étape unique pour le regroupement) ;
    * l'estimation = moyenne glissante du temps par photo des dernières photos x photos restantes ;
    * pendant les ``warmup`` premières photos d'une phase : « estimation en cours… ».
    """

    def __init__(
        self,
        on_update: Callable[[ProgressSnapshot], None] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        window: int = DEFAULT_WINDOW,
        warmup: int = DEFAULT_WARMUP,
        min_interval: float = DEFAULT_MIN_INTERVAL,
        phase_ranges: dict[str, tuple[float, float]] | None = None,
        phase_labels: dict[str, str] | None = None,
    ):
        self.phase_ranges = dict(phase_ranges or {})
        self.phase_labels = dict(phase_labels or {})
        self.on_update = on_update
        self.clock = clock
        self.window = max(1, int(window))
        self.warmup = max(0, int(warmup))
        self.min_interval = max(0.0, float(min_interval))
        self.started = clock()
        self.calls = 0
        self.snapshots: list[ProgressSnapshot] = []
        self._phase = ""
        self._phase_started = self.started
        self._last_done = 0
        self._last_time = self.started
        self._samples: deque[float] = deque(maxlen=self.window)
        self._last_emit = None
        self.finished = False

    # ------------------------------------------------------------------ helpers
    def elapsed(self) -> float:
        return max(0.0, self.clock() - self.started)

    def _average(self) -> float | None:
        if not self._samples:
            return None
        return sum(self._samples) / len(self._samples)

    def _snapshot(self, phase: str, done: int, total: int, *, finished=False) -> ProgressSnapshot:
        label = self.phase_labels.get(phase) or PHASE_LABELS.get(phase, phase or "Analyse")
        total = max(0, int(total))
        done = max(0, min(int(done), total)) if total else max(0, int(done))
        fraction = (done / total) if total else 0.0
        elapsed = self.elapsed()
        average = self._average()
        estimating = done < self.warmup or average is None
        eta = None
        if not estimating and total and done < total:
            eta = average * (total - done)
        if finished:
            text = f"Analyse terminée en {format_duration(elapsed)}"
        elif phase in STEP_PHASES:
            text = f"{label}… · écoulé {format_duration(elapsed)}"
        else:
            parts = [f"{label} · {PHASE_UNITS.get(phase, 'Photo')} {done} / {total}"]
            if eta is not None:
                parts.append(f"reste environ {format_duration(eta)}")
            elif done < total:
                parts.append("estimation en cours…")
            parts.append(f"écoulé {format_duration(elapsed)}")
            text = " · ".join(parts)
        if phase in self.phase_ranges:  # plusieurs phases : la barre avance de façon continue sur l'ensemble
            start, end = self.phase_ranges[phase]
            fraction = start + (end - start) * (fraction if done < total or not total else 1.0)
        return ProgressSnapshot(
            phase=phase,
            label=label,
            done=done,
            total=total,
            fraction=min(1.0, max(0.0, fraction)),
            elapsed=elapsed,
            eta_seconds=eta,
            estimating=estimating and not finished,
            finished=finished,
            text=text,
        )

    def _emit(self, snapshot: ProgressSnapshot, *, force=False) -> None:
        self.snapshots.append(snapshot)
        if self.on_update is None:
            return
        now = self.clock()
        if (
            not force
            and self._last_emit is not None
            and (now - self._last_emit) < self.min_interval
        ):
            return
        self._last_emit = now
        self.on_update(snapshot)

    # ------------------------------------------------------------------ callback
    def __call__(self, phase: str, done: int, total: int) -> None:
        self.calls += 1
        now = self.clock()
        if phase != self._phase:
            self._phase = phase
            self._phase_started = now
            self._last_done = 0
            self._last_time = now
            self._samples.clear()
        delta = int(done) - self._last_done
        if delta > 0:
            per_item = max(0.0, now - self._last_time) / delta
            for _ in range(min(delta, self.window)):
                self._samples.append(per_item)
            self._last_done = int(done)
            self._last_time = now
        snapshot = self._snapshot(phase, done, total)
        self._emit(snapshot, force=bool(total) and int(done) >= int(total))

    def finish(self) -> ProgressSnapshot:
        """Dernier message : « Analyse terminée en X min Y s »."""
        self.finished = True
        snapshot = self._snapshot(self._phase, self._last_done, max(self._last_done, 0), finished=True)
        snapshot = ProgressSnapshot(**{**snapshot.__dict__, "fraction": 1.0})
        self._emit(snapshot, force=True)
        return snapshot
