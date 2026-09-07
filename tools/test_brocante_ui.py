"""Streamlit interaction smoke tests against the memory-only Brocante fixture."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from streamlit.testing.v1.element_tree import ButtonGroup

# AppTest currently iterates single-selection segmented values as characters.
# Keep the compatibility adapter confined to this isolated UI test process.
def _selected_indices(group):
    values = group.value
    values = [values] if isinstance(values, str) else (values or [])
    return [group.options.index(group.format_func(value)) for value in values]


ButtonGroup.indices = property(_selected_indices)


def button(app, label):
    return next(b for b in app.button if b.label == label)


def field(app, kind, label):
    return next(f for f in getattr(app, kind) if f.label == label)


def assert_clean(app):
    assert not app.exception, [e.message for e in app.exception]


def reopen(app, view):
    """Reopen persisted memory data without AppTest's stale post-rerun widgets."""
    fresh = AppTest.from_file(str(ROOT / "tests" / "brocante_app_fixture.py"), default_timeout=30)
    fresh.query_params["apptest"] = "1"
    for key in ("fixture_stock", "fixture_events", "cards_index"):
        fresh.session_state[key] = app.session_state[key]
    fresh.session_state["brocante_view"] = view
    return fresh.run()


def run():
    app = AppTest.from_file(str(ROOT / "tests" / "brocante_app_fixture.py"), default_timeout=30)
    app.query_params["apptest"] = "1"
    app.run()
    assert_clean(app)
    for view in ("Vente", "Rachat", "Hors stock", "Échange", "Frais / clôture", "Historique", "Aujourd’hui"):
        app.session_state["brocante_view"] = view
        app.run()
        assert_clean(app)
        print("render:", view)

    app.session_state["brocante_view"] = "Rachat"
    for number, amount in enumerate((30.0, 12.0), 1):
        app = reopen(app, "Rachat")
        app.session_state["bro_purchase_cart_smoke-event"] = [
            {"card": {"name": "Pikachu", "number": "25", "set": "Test", "lang": "fr"}, "quantity": 5, "value": 10}]
        app.run()
        field(app, "number_input", "Montant total réellement payé (€)").set_value(amount)
        field(app, "checkbox", "Je confirme l'achat et son entrée dans le stock").check()
        button(app, "Valider le rachat").click().run()
        assert_clean(app)
        lots = app.session_state["fixture_stock"]["lots"]
        assert len(lots) == 2
        assert len(lots[-1]["cards"]) == number
        assert sum(c["purchase_total"] for c in lots[-1]["cards"]) == (30 if number == 1 else 42)
    print("purchases: two purchases, one lot, exact costs")

    app = reopen(app, "Hors stock")
    field(app, "number_input", "Prix total encaissé (€)").set_value(100.0)
    field(app, "number_input", "Coût total attribué (€)").set_value(20.0)
    button(app, "Enregistrer la vente").click().run()
    assert_clean(app)
    assert len(app.session_state["fixture_stock"]["ventes_hors_stock"]) == 1
    print("off-stock: shared sale engine, one order")

    app = reopen(app, "Frais / clôture")
    field(app, "number_input", "Montant (€)").set_value(10.0)
    button(app, "Ajouter le frais").click().run()
    assert_clean(app)
    app = reopen(app, "Frais / clôture")
    field(app, "number_input", "Espèces réellement comptées (€)").set_value(96.0).run()
    field(app, "checkbox", "Je confirme la clôture de cette brocante").check().run()
    button(app, "Clôturer la brocante").click().run()
    assert_clean(app)
    event = app.session_state["fixture_events"]["sessions"][0]
    assert event["status"] == "closed"
    assert event["closure"]["theoretical_cash"] == 98
    assert event["closure"]["cash_variance"] == -2
    print("closure: 50 + 100 - 42 - 10 = 98, counted 96, variance -2")
    app = reopen(app, "Historique")
    assert_clean(app)

    prepared = AppTest.from_file(str(ROOT / "tests" / "brocante_app_fixture.py"), default_timeout=30)
    prepared.query_params["preparing"] = "1"
    prepared.query_params["apptest"] = "1"
    prepared.run()
    assert_clean(prepared)
    button(prepared, "Enregistrer la préparation").click().run()
    assert_clean(prepared)
    prepared = reopen(prepared, "Aujourd’hui")
    field(prepared, "checkbox", "Démarrer quand même").check()
    button(prepared, "Démarrer la brocante").click().run()
    assert_clean(prepared)
    assert prepared.session_state["fixture_events"]["sessions"][0]["status"] == "active"
    print("preparation: checklist and explicit override")


if __name__ == "__main__":
    run()
