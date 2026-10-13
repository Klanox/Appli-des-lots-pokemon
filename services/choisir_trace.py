"""Chronometrage optionnel du clic « Choisir » (menu Estimations).

DESACTIVE PAR DEFAUT. Il ne fait rien (un test de fichier toutes les ~1,5 s au maximum) tant qu'il n'est pas active :
  - soit en creant un fichier vide `logs\\trace_choisir.on` (a supprimer pour desactiver, sans redemarrage) ;
  - soit avec la variable d'environnement POKESTOCK_TRACE_CHOISIR=1 (redemarrage du serveur).

Quand il est actif, les durees de chaque etape du clic (cote serveur) et les reperes cote navigateur (clic, carte visible, carte peinte,
application au repos) sont ecrits dans `logs\\choisir_timing.log` (dossier ignore par Git). Aucune donnee de carte n'est ecrite
en dehors du nom de la carte choisie ; rien n'est envoye sur Internet : le navigateur parle uniquement a 127.0.0.1.
"""

import os
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

APP_DIR = Path(__file__).resolve().parents[1]
LOG_DIR = APP_DIR / "logs"
LOG_FILE = LOG_DIR / "choisir_timing.log"
FLAG_FILE = LOG_DIR / "trace_choisir.on"
ENV_NAME = "POKESTOCK_TRACE_CHOISIR"
_MAX_LOG_BYTES = 1_500_000

_LOCK = threading.Lock()
_STATE = {"checked_at": 0.0, "enabled": False, "server": None, "port": 0, "seq": 0}


def enabled():
    now = time.monotonic()
    if now - _STATE["checked_at"] < 1.5:
        return _STATE["enabled"]
    _STATE["checked_at"] = now
    value = str(os.environ.get(ENV_NAME, "")).strip().lower() in {"1", "true", "yes", "on"}
    if not value:
        try:
            value = FLAG_FILE.exists()
        except OSError:
            value = False
    _STATE["enabled"] = value
    return value


def _stamp():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def write_line(text):
    """Ajoute une ligne au journal (ne leve jamais d'exception)."""
    try:
        with _LOCK:
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            if LOG_FILE.exists() and LOG_FILE.stat().st_size > _MAX_LOG_BYTES:
                LOG_FILE.replace(LOG_FILE.with_suffix(".log.1"))
            with open(LOG_FILE, "a", encoding="utf-8") as handle:
                handle.write(f"{_stamp()} {text}\n")
    except Exception:
        pass


class _BeaconHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - nom impose par http.server
        try:
            query = parse_qs(urlparse(self.path).query)
            event = str((query.get("e") or [""])[0])[:40]
            epoch = str((query.get("t") or [""])[0])[:20]
            delta = str((query.get("dt") or [""])[0])[:12]
            extra = str((query.get("x") or [""])[0])[:80]
            text = f"[navigateur] {event}"
            if delta:
                text += f" +{delta} ms depuis le clic"
            if extra:
                text += f" ({extra})"
            text += f" t={epoch}"
            write_line(text)
        except Exception:
            pass
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):  # noqa: N802
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def log_message(self, *args, **kwargs):
        return


def _ensure_server():
    if _STATE["server"] is not None:
        return _STATE["port"]
    try:
        server = ThreadingHTTPServer(("127.0.0.1", 0), _BeaconHandler)
    except Exception:
        return 0
    thread = threading.Thread(target=server.serve_forever, name="choisir-trace-beacon", daemon=True)
    thread.start()
    _STATE["server"] = server
    _STATE["port"] = int(server.server_address[1])
    write_line(f"=== chronometrage Choisir actif (reperes navigateur sur 127.0.0.1:{_STATE['port']}) ===")
    return _STATE["port"]


_BROWSER_SCRIPT = r"""
<script>
(function() {
    const PORT = __PORT__;
    const win = window.parent && window.parent !== window ? window.parent : window;
    const doc = win.document;
    if (win.__psChoisirTrace === PORT) return;
    win.__psChoisirTrace = PORT;
    const TAG = "[PokéStock] Choisir";
    function send(event, dt, extra) {
        try {
            let url = "http://127.0.0.1:" + PORT + "/m?e=" + encodeURIComponent(event) + "&t=" + Date.now();
            if (dt !== null && dt !== undefined) url += "&dt=" + Math.round(dt);
            if (extra) url += "&x=" + encodeURIComponent(extra);
            fetch(url, { mode: "no-cors", keepalive: true, cache: "no-store" }).catch(function() {});
        } catch (e) {}
    }
    function cardClasses() {
        return Array.prototype.map.call(doc.querySelectorAll('[class*="st-key-del_est_card_box_"]'), function(el) { return el.className; });
    }
    let session = null;
    function finish() {
        if (!session) return;
        try { session.observer.disconnect(); } catch (e) {}
        clearTimeout(session.timer);
        clearTimeout(session.idleTimer);
        session = null;
    }
    function onClick(ev) {
        const button = ev.target && ev.target.closest ? ev.target.closest("button") : null;
        if (!button || (button.innerText || "").trim() !== "Choisir") return;
        finish();
        const t0 = performance.now();
        const before = new Set(cardClasses());
        const app = doc.querySelector('[data-testid="stApp"]');
        session = { t0: t0, before: before, seenCard: false, lastState: app ? app.getAttribute("data-test-script-state") : null, observer: null, timer: null };
        send("clic Choisir", 0);
        console.log(TAG + " : clic");
        const check = function() {
            if (!session) return;
            const dt = performance.now() - session.t0;
            if (!session.seenCard) {
                const now = cardClasses();
                if (now.some(function(c) { return !session.before.has(c); })) {
                    session.seenCard = true;
                    send("nouvelle carte dans la page", dt, "cartes=" + now.length);
                    console.log(TAG + " : carte dans la page +" + Math.round(dt) + " ms");
                    const clickT0 = session.t0;
                    requestAnimationFrame(function() { requestAnimationFrame(function() {
                        const paintedDt = performance.now() - clickT0;
                        send("carte peinte (2 images plus tard)", paintedDt);
                        console.log(TAG + " : carte peinte +" + Math.round(paintedDt) + " ms");
                    }); });
                }
            }
            const appNow = doc.querySelector('[data-testid="stApp"]');
            const state = appNow ? appNow.getAttribute("data-test-script-state") : null;
            if (state && state !== session.lastState) {
                session.lastState = state;
                const label = state === "running" ? "application en calcul" : (state === "notRunning" ? "application au repos" : "etat " + state);
                send(label, dt);
                console.log(TAG + " : " + label + " +" + Math.round(dt) + " ms");
                clearTimeout(session.idleTimer);
                if (state === "notRunning") {
                    // Repos confirme (aucun nouveau calcul pendant 1,5 s) : le suivi de ce clic est termine.
                    session.idleTimer = setTimeout(function() {
                        if (!session) return;
                        const total = performance.now() - session.t0;
                        send("REPOS FINAL", total - 1500);
                        console.log(TAG + " : REPOS FINAL à +" + Math.round(total - 1500) + " ms");
                        finish();
                    }, 1500);
                }
            }
        };
        session.observer = new MutationObserver(check);
        session.observer.observe(doc.body, { childList: true, subtree: true, attributes: true, attributeFilter: ["data-test-script-state"] });
        session.timer = setTimeout(finish, 60000);
    }
    doc.addEventListener("click", onClick, true);
    console.log(TAG + " : chronométrage navigateur actif (port " + PORT + ")");
})();
</script>
"""


def browser_script():
    """Script a injecter dans la page quand le chronometrage est actif ; chaine vide sinon."""
    if not enabled():
        return ""
    port = _ensure_server()
    if not port:
        return ""
    return _BROWSER_SCRIPT.replace("__PORT__", str(int(port)))


# ---------------------------------------------------------------------------------------------------------------------
# Etapes cote serveur (l'etat d'un clic est garde dans st.session_state, partage entre le fragment et le rerun complet)
# ---------------------------------------------------------------------------------------------------------------------
def _session():
    import streamlit as st

    return st.session_state


def note_fragment_start():
    """Memorise l'heure de debut d'execution du fragment d'ajout (peu couteux ; sert a mesurer l'attente avant le clic detecte)."""
    if not enabled():
        return
    try:
        session = _session()
        session["_choisir_trace_fragment_start"] = time.perf_counter()
    except Exception:
        pass


def begin(label, **detail):
    if not enabled():
        return
    try:
        session = _session()
        now = time.perf_counter()
        _STATE["seq"] += 1
        started = session.get("_choisir_trace_fragment_start")
        info = {"id": _STATE["seq"], "t0": now, "last": now, "runs": 0, "label": label}
        session["_choisir_trace"] = info
        wait = f"{int((now - started) * 1000)} ms" if started else "?"
        extra = " ".join(f'{key}="{value}"' for key, value in detail.items() if value not in (None, ""))
        write_line(f"#{info['id']} [serveur] clic « {label} » detecte {extra} | le fragment d'ajout tournait depuis {wait} | t={int(time.time() * 1000)}")
    except Exception:
        pass


def step(name, **detail):
    if not enabled():
        return
    try:
        info = _session().get("_choisir_trace")
        if not info:
            return
        now = time.perf_counter()
        extra = " ".join(f"{key}={value}" for key, value in detail.items() if value not in (None, ""))
        write_line(f"#{info['id']} [serveur] +{int((now - info['t0']) * 1000)} ms (etape {int((now - info['last']) * 1000)} ms) {name} {extra}".rstrip())
        info["last"] = now
    except Exception:
        pass


def inject_browser_script(run_html_func):
    """Injecte le script navigateur (repere clic / carte / repos) quand le chronometrage est actif ; sans effet sinon."""
    if not enabled() or not callable(run_html_func):
        return
    try:
        script = browser_script()
        if script:
            run_html_func(script, height=0)
    except Exception:
        pass


def run_start():
    if not enabled():
        return
    try:
        info = _session().get("_choisir_trace")
        if not info:
            return
        if time.perf_counter() - info["t0"] > 60:
            _session().pop("_choisir_trace", None)
            return
        info["runs"] += 1
        step(f"rerun complet n°{info['runs']} : debut de la page Estimations")
    except Exception:
        pass


def run_end(note=""):
    if not enabled():
        return
    try:
        info = _session().get("_choisir_trace")
        if not info or not info.get("runs"):
            return
        step(f"rerun n°{info['runs']} : fin de la page Estimations {note}".strip())
        if info["runs"] >= 4:
            _session().pop("_choisir_trace", None)
    except Exception:
        pass
