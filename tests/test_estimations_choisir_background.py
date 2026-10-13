"""« Choisir » : l'appel API d'image ne bloque plus le clic, et le chronometrage est inactif par defaut.

Aucun reseau (requests remplace), aucune donnee reelle (dossiers temporaires), aucun serveur Streamlit.
"""
import ast
import os
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

from services import card_image_lookup, choisir_trace
from ui.pages import estimations

ROOT = Path(__file__).resolve().parents[1]


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code = status
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


def load_app_functions(names, extra_globals):
    """Charge uniquement les fonctions demandees de app.py (jamais le demarrage de l'application)."""
    tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8-sig"))
    body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    namespace = dict(extra_globals)
    exec(compile(ast.Module(body=body, type_ignores=[]), "app_functions", "exec"), namespace)
    return namespace


class SessionState(dict):
    __getattr__ = dict.get


class FakeStreamlit:
    def __init__(self):
        self.session_state = SessionState()


def make_namespace(requests_get, lookups):
    fake_st = FakeStreamlit()
    namespace = load_app_functions(
        {"ecd", "add_estimation_card"},
        {
            "st": fake_st,
            "json": __import__("json"),
            "requests": mock.Mock(get=requests_get),
            "new_uid": lambda prefix: f"{prefix}_x{len(lookups)}{time.time_ns()}",
            "search_in_cache": lambda name, number: [],
            "parse_int_input": lambda value, default: int(value or default),
            "parse_float_input": lambda value, default: float(str(value or default).replace(",", ".")),
            "apply_custom_image_fallback": lambda card: None,
            "start_card_image_lookup": lambda uid, card_id, lang="fr": lookups.append((uid, card_id, lang)),
        },
    )
    return namespace, fake_st


CARD_WITHOUT_IMAGE = ({"id": "smp-SM184", "localId": "SM184", "name": "Evoli"}, "Promos Soleil et Lune")
CARD_WITH_IMAGE = ({"id": "base1-55", "image": "https://assets.tcgdex.net/fr/base/base1/55", "localId": "55", "name": "Evoli"}, "Set de Base")


class AddEstimationCardTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.lookups = []

        def slow_get(url, timeout=3):
            self.calls.append((url, threading.current_thread().name))
            return FakeResponse(200, {"image": "https://assets.tcgdex.net/fr/sm/smp/SM184"})

        self.ns, self.fake_st = make_namespace(slow_get, self.lookups)

    def test_no_blocking_api_call_for_a_card_without_local_image(self):
        active = {"cards": []}
        self.ns["add_estimation_card"](active, "Evoli", "SM184", "0,00", "1", "NM", [], "", False, CARD_WITHOUT_IMAGE)
        self.assertEqual(self.calls, [])                      # aucun appel reseau pendant l'ajout
        self.assertEqual(len(active["cards"]), 1)             # la carte est bien ajoutee tout de suite
        card = active["cards"][0]
        self.assertEqual(card["image_url"], "")
        self.assertEqual(self.lookups, [(card["uid"], "smp-SM184", "fr")])   # la recherche est confiee a l'arriere-plan
        self.assertFalse([k for k in self.fake_st.session_state if k.startswith("ecd_")])  # resultat incomplet : pas mis en cache

    def test_card_with_local_image_keeps_the_same_result_and_starts_no_lookup(self):
        active = {"cards": []}
        self.ns["add_estimation_card"](active, "Evoli", "55", "0,00", "1", "NM", [], "", False, CARD_WITH_IMAGE)
        card = active["cards"][0]
        self.assertEqual(card["image_url"], "https://assets.tcgdex.net/fr/base/base1/55/high.webp")
        self.assertEqual(card["set"], "Set de Base")
        self.assertEqual(self.lookups, [])
        self.assertEqual(self.calls, [])

    def test_default_ecd_still_calls_the_api_and_caches(self):
        enriched = self.ns["ecd"](*CARD_WITHOUT_IMAGE, lang="fr")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(enriched["image_url"], "https://assets.tcgdex.net/fr/sm/smp/SM184/high.webp")
        self.ns["ecd"](*CARD_WITHOUT_IMAGE, lang="fr")
        self.assertEqual(len(self.calls), 1)                  # 2e appel : cache de session

    def test_lookup_failure_inside_add_never_blocks_the_write(self):
        def boom(uid, card_id, lang="fr"):
            raise RuntimeError("thread impossible")

        self.ns["start_card_image_lookup"] = boom
        active = {"cards": []}
        self.ns["add_estimation_card"](active, "Evoli", "SM184", "0,00", "1", "NM", [], "", False, CARD_WITHOUT_IMAGE)
        self.assertEqual(len(active["cards"]), 1)


class BackgroundLookupTest(unittest.TestCase):
    def setUp(self):
        card_image_lookup._DONE.clear()
        card_image_lookup._PENDING.clear()
        self.addCleanup(card_image_lookup._DONE.clear)
        self.addCleanup(setattr, card_image_lookup, "_http_get", None)

    def wait_done(self, uid):
        for _ in range(100):
            if uid in card_image_lookup._DONE or uid not in card_image_lookup._PENDING:
                return
            time.sleep(0.02)

    def test_result_is_stored_by_the_thread_and_popped_once(self):
        gate = threading.Event()

        def get(url, timeout=3):
            gate.wait(2)
            return FakeResponse(200, {"image": "https://assets.tcgdex.net/fr/sm/smp/SM184"})

        card_image_lookup._http_get = get
        started = time.perf_counter()
        self.assertTrue(card_image_lookup.start_card_image_lookup("u1", "smp-SM184", "fr"))
        self.assertLess(time.perf_counter() - started, 0.2)   # rend la main sans attendre le « reseau »
        self.assertEqual(card_image_lookup.pop_ready_image_urls(["u1"]), {})
        gate.set()
        self.wait_done("u1")
        self.assertEqual(card_image_lookup.pop_ready_image_urls(["u1", "autre"]), {"u1": "https://assets.tcgdex.net/fr/sm/smp/SM184/high.webp"})
        self.assertEqual(card_image_lookup.pop_ready_image_urls(["u1"]), {})

    def test_failures_leave_no_result_and_never_raise(self):
        card_image_lookup._http_get = lambda url, timeout=3: (_ for _ in ()).throw(OSError("hors ligne"))
        self.assertTrue(card_image_lookup.start_card_image_lookup("u2", "x-1", "fr"))
        self.wait_done("u2")
        self.assertEqual(card_image_lookup.pop_ready_image_urls(["u2"]), {})
        self.assertFalse(card_image_lookup.start_card_image_lookup("", "x-1"))
        self.assertFalse(card_image_lookup.start_card_image_lookup("u3", ""))

    def test_falls_back_to_english_and_keeps_extension(self):
        urls = []

        def get(url, timeout=3):
            urls.append(url)
            if "/fr/" in url:
                return FakeResponse(404)
            return FakeResponse(200, {"image": "https://assets.tcgdex.net/en/x/y/1.png"})

        card_image_lookup._http_get = get
        self.assertEqual(card_image_lookup.fetch_tcgdex_image_url("x-1", "fr"), "https://assets.tcgdex.net/en/x/y/1.png")
        self.assertEqual(len(urls), 2)


class AdoptionTest(unittest.TestCase):
    def setUp(self):
        card_image_lookup._DONE.clear()
        self.addCleanup(card_image_lookup._DONE.clear)
        estimations._IMAGE_PREFETCH_DONE.clear()
        self.addCleanup(estimations._IMAGE_PREFETCH_DONE.clear)

    def test_url_is_attached_only_when_the_card_has_no_image_and_saved_once(self):
        estimate = {"cards": [{"uid": "a", "image_url": ""}, {"uid": "b", "image_url": "https://deja/ici.webp"}, {"uid": "c", "manual_image_path": "m.png"}]}
        card_image_lookup._DONE.update({"a": "https://nouveau/a.webp", "b": "https://nouveau/b.webp", "c": "https://nouveau/c.webp"})
        saves = []
        self.assertTrue(estimations._adopt_prefetched_images(estimate, {"e": 1}, lambda data: saves.append(data)))
        self.assertEqual(estimate["cards"][0]["image_url"], "https://nouveau/a.webp")
        self.assertEqual(estimate["cards"][1]["image_url"], "https://deja/ici.webp")      # jamais ecrasee
        self.assertNotIn("image_url", estimate["cards"][2])
        self.assertEqual(len(saves), 1)
        self.assertFalse(estimations._adopt_prefetched_images(estimate, {"e": 1}, lambda data: saves.append(data)))
        self.assertEqual(len(saves), 1)                                                   # rien de nouveau : aucune sauvegarde

    def test_nothing_pending_means_no_save(self):
        saves = []
        self.assertFalse(estimations._adopt_prefetched_images({"cards": [{"uid": "a"}]}, {}, lambda data: saves.append(data)))
        self.assertEqual(saves, [])


class TraceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patches = [
            mock.patch.object(choisir_trace, "LOG_DIR", self.tmp / "logs"),
            mock.patch.object(choisir_trace, "LOG_FILE", self.tmp / "logs" / "choisir_timing.log"),
            mock.patch.object(choisir_trace, "FLAG_FILE", self.tmp / "logs" / "trace_choisir.on"),
            mock.patch.dict(os.environ, {}, clear=False),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        os.environ.pop(choisir_trace.ENV_NAME, None)
        choisir_trace._STATE.update({"checked_at": 0.0, "enabled": False})
        self.addCleanup(choisir_trace._STATE.update, {"checked_at": 0.0, "enabled": False})

    def test_disabled_by_default_writes_nothing_and_starts_no_server(self):
        self.assertFalse(choisir_trace.enabled())
        self.assertEqual(choisir_trace.browser_script(), "")
        choisir_trace.begin("Choisir", carte="X")
        choisir_trace.step("etape")
        choisir_trace.run_start()
        choisir_trace.run_end()
        self.assertFalse((self.tmp / "logs").exists())
        self.assertIsNone(choisir_trace._STATE["server"])

    def test_flag_file_enables_without_restart_and_removal_disables(self):
        (self.tmp / "logs").mkdir()
        (self.tmp / "logs" / "trace_choisir.on").write_text("")
        choisir_trace._STATE["checked_at"] = 0.0
        self.assertTrue(choisir_trace.enabled())
        (self.tmp / "logs" / "trace_choisir.on").unlink()
        choisir_trace._STATE["checked_at"] = 0.0
        self.assertFalse(choisir_trace.enabled())

    def test_environment_variable_enables(self):
        os.environ[choisir_trace.ENV_NAME] = "1"
        choisir_trace._STATE["checked_at"] = 0.0
        self.assertTrue(choisir_trace.enabled())

    def test_enabled_trace_writes_steps_and_receives_browser_markers(self):
        import streamlit as st

        os.environ[choisir_trace.ENV_NAME] = "1"
        choisir_trace._STATE["checked_at"] = 0.0
        with mock.patch.object(st, "session_state", {}):
            script = choisir_trace.browser_script()
            self.assertIn("127.0.0.1", script)
            self.assertNotIn("__PORT__", script)
            port = choisir_trace._STATE["port"]
            choisir_trace.note_fragment_start()
            choisir_trace.begin("Choisir", carte="Evoli")
            choisir_trace.step("save_estimations termine", sauvegarde_ms=12)
            choisir_trace.run_start()
            choisir_trace.run_end()
            urllib.request.urlopen(f"http://127.0.0.1:{port}/m?e=clic%20Choisir&t=123&dt=0", timeout=3).read()
            urllib.request.urlopen(f"http://127.0.0.1:{port}/m?e=carte%20peinte&t=456&dt=321", timeout=3).read()
        text = (self.tmp / "logs" / "choisir_timing.log").read_text(encoding="utf-8")
        for expected in ("clic « Choisir » detecte", "save_estimations termine", "rerun complet n°1", "fin de la page Estimations", "[navigateur] clic Choisir", "[navigateur] carte peinte +321 ms"):
            self.assertIn(expected, text)

    def test_inject_is_silent_when_disabled(self):
        calls = []
        choisir_trace.inject_browser_script(lambda body, height=0: calls.append(body))
        self.assertEqual(calls, [])
        os.environ[choisir_trace.ENV_NAME] = "1"
        choisir_trace._STATE["checked_at"] = 0.0
        choisir_trace.inject_browser_script(lambda body, height=0: calls.append(body))
        self.assertEqual(len(calls), 1)
        self.assertIn("[PokéStock] Choisir", calls[0])


if __name__ == "__main__":
    unittest.main()
