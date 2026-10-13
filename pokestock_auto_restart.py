# -*- coding: utf-8 -*-
"""Lanceur PokéStock avec redémarrage automatique.

Démarre Streamlit exactement comme le lanceur habituel
(python -m streamlit run app.py --server.headless true --server.port 8501, dossier de travail = dossier du projet),
puis le redémarre tout seul quand un fichier .py du projet change (après ~3 s sans nouvelle modification).

N'utilise que la bibliothèque standard. Ne modifie, ne crée et ne supprime aucun fichier du projet.
Arrêt : Ctrl+C dans cette fenêtre, ou fermer la fenêtre.
"""

import ctypes
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from datetime import datetime

# ----------------------------------------------------------------------------------------------------------------------
# Réglages (repris du lanceur Pokestock_launcher.vbs)
# ----------------------------------------------------------------------------------------------------------------------
PORT = int(os.environ.get("POKESTOCK_AUTO_PORT", "8501"))
QUIET_SECONDS = float(os.environ.get("POKESTOCK_AUTO_QUIET", "3"))   # calme requis après la dernière modification
POLL_SECONDS = 1.0                                                  # fréquence de surveillance
READY_TIMEOUT = 90                                                  # attente maximale du démarrage du serveur
STOP_GRACE_SECONDS = 10                                             # arrêt "propre" avant arrêt forcé
PORT_FREE_TIMEOUT = 20                                              # attente de la libération du port
APP_URL = f"http://localhost:{PORT}"
HEALTH_URL = f"http://localhost:{PORT}/_stcore/health"
SERVER_ARGS = ["-m", "streamlit", "run", "app.py", "--server.headless", "true", "--server.port", str(PORT)]

ROOT = os.path.dirname(os.path.abspath(__file__))
SELF_NAME = os.path.basename(__file__)
IS_WIN = os.name == "nt"

# Dossiers jamais surveillés (sauvegardes, journaux, caches, données, tests…).
IGNORED_DIRS = {
    "backups", "logs", "__pycache__", ".git", ".venv", "venv", "env", "node_modules", ".cache", "cache",
    "images", "card_images", "tests", "docs", "photo_recognition_poc", ".history", ".idea", ".vscode", ".gemini",
    ".pytest_cache", ".mypy_cache",
}
IGNORED_DIR_PREFIXES = ("backup", "appli des lots pokemon - backup")
EXTRA_WATCHED = {os.path.join(".streamlit", "config.toml")}   # la config Streamlit n'est lue qu'au démarrage


def log(message=""):
    print(f"[{datetime.now():%H:%M:%S}] {message}" if message else "", flush=True)


# ----------------------------------------------------------------------------------------------------------------------
# Surveillance des fichiers (simple comparaison date de modification + taille)
# ----------------------------------------------------------------------------------------------------------------------
def _is_watched_file(rel_path, name):
    if rel_path in EXTRA_WATCHED:
        return True
    if not name.endswith(".py"):
        return False
    if name == SELF_NAME and os.path.dirname(rel_path) == "":
        return False
    return not name.startswith(("~", ".#", "_tmp", "tmp_"))


def snapshot(root=ROOT):
    files = {}
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    lowered = entry.name.lower()
                    if lowered in IGNORED_DIRS or lowered.startswith(IGNORED_DIR_PREFIXES):
                        continue
                    stack.append(entry.path)
                elif entry.is_file(follow_symlinks=False):
                    rel = os.path.relpath(entry.path, root)
                    if _is_watched_file(rel, entry.name):
                        stat = entry.stat()
                        files[rel.replace("\\", "/")] = (stat.st_mtime_ns, stat.st_size)
            except OSError:
                continue
    return files


def diff_snapshots(old, new):
    return sorted({path for path in set(old) | set(new) if old.get(path) != new.get(path)})


def describe_files(paths, limit=4):
    shown = ", ".join(paths[:limit])
    return shown + (f" (+{len(paths) - limit} autres)" if len(paths) > limit else "")


def syntax_errors(paths, root=ROOT):
    """Compile (sans exécuter) les .py demandés ; renvoie {chemin: message}."""
    errors = {}
    for rel in paths:
        if not rel.endswith(".py"):
            continue
        full = os.path.join(root, rel)
        if not os.path.exists(full):
            continue
        try:
            with open(full, "rb") as handle:
                compile(handle.read(), full, "exec", dont_inherit=True)
        except SyntaxError as exc:
            errors[rel] = f"ligne {exc.lineno} : {exc.msg}"
        except (OSError, ValueError) as exc:
            errors[rel] = f"illisible ({exc})"
    return errors


# ----------------------------------------------------------------------------------------------------------------------
# Port / processus
# ----------------------------------------------------------------------------------------------------------------------
def parse_netstat_listening(text, port):
    """PID qui écoute sur `port` d'après `netstat -ano -p TCP`. Indépendant de la langue : une socket en écoute a une adresse distante en :0."""
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 5 or parts[0].upper() != "TCP":
            continue
        local, foreign, pid = parts[1], parts[2], parts[-1]
        if local.rsplit(":", 1)[-1] == str(port) and foreign.rsplit(":", 1)[-1] == "0" and pid.isdigit():
            return int(pid)
    return None


def _run_text(command, timeout=15):
    try:
        done = subprocess.run(command, capture_output=True, timeout=timeout)
    except Exception:
        return ""
    return (done.stdout or b"").decode("utf-8", errors="replace")


def _posix_listening_pid(port):
    inodes = set()
    for name in ("/proc/net/tcp", "/proc/net/tcp6"):
        try:
            with open(name) as handle:
                lines = handle.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) > 9 and parts[3] == "0A" and int(parts[1].rsplit(":", 1)[1], 16) == port:
                inodes.add(parts[9])
    if not inodes:
        return None
    for entry in os.listdir("/proc"):
        if not entry.isdigit():
            continue
        try:
            for fd in os.listdir(f"/proc/{entry}/fd"):
                target = os.readlink(f"/proc/{entry}/fd/{fd}")
                if target.startswith("socket:[") and target[8:-1] in inodes:
                    return int(entry)
        except OSError:
            continue
    return None


def find_listening_pid(port):
    if IS_WIN:
        return parse_netstat_listening(_run_text(["netstat", "-ano", "-p", "TCP"]), port)
    return _posix_listening_pid(port)


def get_command_line(pid):
    """Ligne de commande du processus, ou None si elle ne peut pas être lue (dans ce cas on n'arrête rien)."""
    if IS_WIN:
        text = _run_text(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                          f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"]).strip()
        if not text:
            text = _run_text(["wmic", "process", "where", f"ProcessId={int(pid)}", "get", "CommandLine", "/value"]).strip()
        return text or None
    try:
        with open(f"/proc/{int(pid)}/cmdline", "rb") as handle:
            return handle.read().replace(b"\0", b" ").decode("utf-8", errors="replace").strip() or None
    except OSError:
        return None


def is_pokestock_server(command_line):
    """Serveur Streamlit lancé sur app.py — jamais un autre programme Python."""
    lowered = (command_line or "").lower()
    return "streamlit" in lowered and "app.py" in lowered


def port_in_use(port):
    if find_listening_pid(port):
        return True
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            continue
    return False


def kill_process(pid, force=True):
    if IS_WIN:
        command = ["taskkill", "/PID", str(pid), "/T"] + (["/F"] if force else [])
        subprocess.run(command, capture_output=True)
        return
    try:
        os.kill(pid, signal.SIGKILL if force else signal.SIGTERM)
    except OSError:
        pass


def wait_for_port_free(timeout=PORT_FREE_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_in_use(PORT):
            return True
        time.sleep(0.3)
    return not port_in_use(PORT)


def free_the_port():
    """Arrête un ancien serveur PokéStock qui occupe le port. Renvoie False (sans rien arrêter) si c'est un autre programme."""
    pid = find_listening_pid(PORT)
    if pid:
        command = get_command_line(pid)
        if not is_pokestock_server(command):
            log(f"Le port {PORT} est utilisé par un autre programme (PID {pid}) : {command or 'ligne de commande illisible'}")
            log("Je ne l'arrête pas. Ferme-le toi-même, ou change PORT en haut de pokestock_auto_restart.py.")
            return False
        log(f"Ancien serveur PokéStock trouvé (PID {pid}). Arrêt…")
        kill_process(pid, force=False)
        time.sleep(1.5)
        if find_listening_pid(PORT) == pid:
            kill_process(pid, force=True)
    elif port_in_use(PORT):
        log(f"Le port {PORT} répond mais le programme qui l'utilise est introuvable : je n'y touche pas.")
        return False
    if not wait_for_port_free():
        log(f"Le port {PORT} n'a pas été libéré après {PORT_FREE_TIMEOUT} s. Abandon.")
        return False
    return True


# ----------------------------------------------------------------------------------------------------------------------
# Serveur Streamlit
# ----------------------------------------------------------------------------------------------------------------------
class Server:
    def __init__(self):
        self.proc = None

    def start(self):
        env = dict(os.environ, PYTHONUNBUFFERED="1")
        kwargs = {}
        if IS_WIN:
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP   # permet l'arrêt propre par Ctrl+Pause
        else:
            kwargs["start_new_session"] = True
        self.proc = subprocess.Popen([sys.executable] + SERVER_ARGS, cwd=ROOT, env=env, **kwargs)

    def running(self):
        return self.proc is not None and self.proc.poll() is None

    def wait_ready(self):
        """True si le serveur répond, False s'il s'est arrêté, None si le délai est dépassé."""
        deadline = time.time() + READY_TIMEOUT
        while time.time() < deadline:
            if self.proc.poll() is not None:
                return False
            try:
                with urllib.request.urlopen(HEALTH_URL, timeout=2) as response:
                    if 200 <= response.status < 500:
                        return True
            except Exception:
                pass
            time.sleep(0.5)
        return None

    def stop(self, grace=STOP_GRACE_SECONDS):
        proc = self.proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if IS_WIN:
                proc.send_signal(signal.CTRL_BREAK_EVENT)    # Streamlit l'intercepte (SIGBREAK) et s'arrête proprement
            else:
                os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(grace)
            return
        except subprocess.TimeoutExpired:
            pass
        log("Le serveur ne s'arrête pas tout seul : arrêt forcé.")
        if IS_WIN:
            subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True)
        else:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
        try:
            proc.wait(5)
        except Exception:
            pass


def launch(server, first_time):
    """Libère le port, démarre le serveur et attend qu'il réponde. Renvoie "ok", "bloque" (port pris par un autre programme) ou "echec"."""
    if not free_the_port():
        return "bloque"
    log("Démarrage du serveur PokéStock…")
    server.start()
    ready = server.wait_ready()
    if ready:
        log(f"Prêt : {APP_URL}")
        if first_time:
            log("Ouverture du navigateur par défaut…")
            try:
                webbrowser.open(APP_URL)
            except Exception:
                log(f"Impossible d'ouvrir le navigateur : ouvre {APP_URL} à la main.")
        else:
            log("Si la page ne se reconnecte pas toute seule, fais F5.")
        return "ok"
    if ready is False:
        log(f"Le serveur s'est arrêté au démarrage (code {server.proc.returncode}). L'erreur est affichée juste au-dessus.")
        log("Corrige-la puis enregistre un fichier : le redémarrage se fera tout seul.")
    else:
        log(f"Le serveur ne répond pas après {READY_TIMEOUT} s (il tourne encore). Je continue à surveiller les fichiers.")
    return "echec"


def setup_console():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if IS_WIN:
        try:
            ctypes.windll.kernel32.SetConsoleTitleW("PokéStock (redémarrage automatique)")
        except Exception:
            pass


def install_close_handler(server):
    """Fermer la fenêtre du lanceur arrête aussi le serveur qu'il a démarré (Windows)."""
    if not IS_WIN:
        return None
    handler_type = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_uint)

    def on_event(event):
        if event in (2, 5, 6):          # fermeture de la fenêtre, déconnexion, arrêt de Windows
            server.stop(grace=3)
        return False

    handler = handler_type(on_event)
    try:
        ctypes.windll.kernel32.SetConsoleCtrlHandler(handler, True)
    except Exception:
        return None
    return handler                       # à conserver : sinon Python le libère


def main():
    setup_console()
    log("PokéStock (redémarrage automatique)")
    log(f"Dossier : {ROOT}")
    log(f"Port : {PORT}   |   attente avant redémarrage : {QUIET_SECONDS:g} s sans modification")
    if not os.path.exists(os.path.join(ROOT, "app.py")):
        log("app.py introuvable dans ce dossier : place ce lanceur à la racine du projet.")
        return 1
    server = Server()
    keep_handler = install_close_handler(server)  # noqa: F841
    exit_code = 0
    try:
        log(f"Recherche d'un ancien serveur sur le port {PORT}…")
        if launch(server, first_time=True) == "bloque":
            return 1                                      # port pris par un autre programme : rien n'est arrêté ni démarré
        known = snapshot()
        pending = []
        last_change = 0.0
        broken = {}
        crash_announced = False
        log("Surveillance des fichiers .py (Ctrl+C pour arrêter).")
        while True:
            time.sleep(POLL_SECONDS)
            if server.proc is not None and not server.running() and not crash_announced:
                crash_announced = True
                log(f"Le serveur s'est arrêté (code {server.proc.returncode}). L'erreur est affichée au-dessus.")
                log("Corrige-la puis enregistre un fichier : le redémarrage se fera tout seul.")
            current = snapshot()
            changed = diff_snapshots(known, current)
            known = current
            if changed:
                log(f"Modification détectée dans : {describe_files(changed)}")
                pending = sorted(set(pending) | set(changed))
                last_change = time.time()
                continue
            if not pending or time.time() - last_change < QUIET_SECONDS:
                continue
            to_check = sorted(set(pending) | set(broken))
            batch, pending = pending, []
            errors = syntax_errors(to_check)
            broken = errors
            if errors:
                for rel, message in errors.items():
                    log(f"Erreur de syntaxe dans {rel}, {message}")
                log("Redémarrage annulé. Enregistre la correction : il reprendra tout seul.")
                continue
            log(f"Redémarrage… ({len(batch)} fichier(s) modifié(s))")
            server.stop()
            crash_announced = False
            if launch(server, first_time=False) != "ok" and not server.running():
                crash_announced = True
    except KeyboardInterrupt:
        pass
    finally:
        log("Arrêt de PokéStock…")
        server.stop()
        log("Terminé.")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
