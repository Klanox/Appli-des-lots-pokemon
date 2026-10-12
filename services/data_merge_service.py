"""Fusion a 3 voies de data.json pour proteger les modifications entre sessions.

Contexte : chaque session Streamlit garde sa propre copie en memoire de data.json et
sd() reecrit le fichier entier. Sans protection, une session peut ecraser silencieusement
la modification faite par une autre (PC + telephone, deux onglets...).

merge3(base, mine, theirs) combine :
  - base   : contenu du fichier tel que la session l'a charge / ecrit pour la derniere fois ;
  - mine   : la copie de la session (avec la modification en cours) ;
  - theirs : contenu actuel du fichier (modifie entre-temps par une autre session).

Regles :
  - ce qu'une seule des deux parties a change est conserve (les deux modifications sont gardees) ;
  - les listes d'objets portant un identifiant (lot_uid, card_uid, ...) sont fusionnees element par
    element ; les autres listes sont traitees comme une valeur unique ;
  - si les DEUX parties ont change la meme valeur differemment, c'est un conflit : la valeur de la
    session qui sauvegarde (la plus recente) est gardee et le conflit est renvoye pour etre signale.
"""

from __future__ import annotations

from typing import Any

MISSING = object()
ID_KEYS = ("card_uid", "lot_uid", "drop_item_id", "sale_id", "uid", "id")


def _list_id_key(*lists):
    """Cle d'identite commune a tous les elements de toutes les listes (ou None)."""
    non_empty = [lst for lst in lists if lst]
    if not non_empty:
        return None
    for key in ID_KEYS:
        ok = True
        for lst in non_empty:
            seen = set()
            for item in lst:
                if not isinstance(item, dict):
                    ok = False
                    break
                value = item.get(key)
                if value in (None, "") or value in seen:
                    ok = False
                    break
                seen.add(value)
            if not ok:
                break
        if ok:
            return key
    return None


def _label(*items) -> str:
    for item in items:
        if isinstance(item, dict):
            for field in ("nom", "name"):
                if item.get(field):
                    return str(item[field])
    return ""


def _short(value) -> str:
    if value is MISSING:
        return "(supprimé)"
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


class _Merger:
    def __init__(self):
        self.conflicts: list[dict[str, Any]] = []
        self.merged_changes = 0  # nombre de zones ou les deux cotes avaient change des choses differentes

    def conflict(self, path, mine, theirs):
        readable = [p for p in path if p and p not in ("lots", "cards")]
        self.conflicts.append({"path": " › ".join(readable), "mine": _short(mine), "theirs": _short(theirs)})
        return mine

    def value(self, base, mine, theirs, path):
        if mine == theirs:
            return mine
        if mine == base:
            return theirs
        if theirs == base:
            return mine
        # les trois differents
        if isinstance(mine, dict) and isinstance(theirs, dict):
            return self.dict(base if isinstance(base, dict) else {}, mine, theirs, path)
        if isinstance(mine, list) and isinstance(theirs, list):
            return self.list(base if isinstance(base, list) else [], mine, theirs, path)
        return self.conflict(path, mine, theirs)

    def dict(self, base, mine, theirs, path):
        self.merged_changes += 1
        out = {}
        keys = list(mine.keys()) + [k for k in theirs.keys() if k not in mine]
        for key in keys:
            b = base.get(key, MISSING)
            m = mine.get(key, MISSING)
            t = theirs.get(key, MISSING)
            result = self.value(b, m, t, path + [str(key)])
            if result is not MISSING:
                out[key] = result
        return out

    def list(self, base, mine, theirs, path):
        key = _list_id_key(base, mine, theirs)
        if key is None:
            return self.conflict(path, mine, theirs)
        self.merged_changes += 1
        b = {item[key]: item for item in base}
        m = {item[key]: item for item in mine}
        t = {item[key]: item for item in theirs}
        order = [item[key] for item in mine] + [item[key] for item in theirs if item[key] not in m]
        out = []
        for ident in order:
            bx, mx, tx = b.get(ident, MISSING), m.get(ident, MISSING), t.get(ident, MISSING)
            label = _label(None if mx is MISSING else mx, None if tx is MISSING else tx, None if bx is MISSING else bx) or str(ident)
            result = self.value(bx, mx, tx, path + [label])
            if result is not MISSING:
                out.append(result)
        return out


def merge3(base, mine, theirs):
    """Retourne (fusion, conflits). `mine` et `theirs` ne sont pas modifies."""
    merger = _Merger()
    merged = merger.value(base, mine, theirs, [])
    return merged, merger.conflicts
