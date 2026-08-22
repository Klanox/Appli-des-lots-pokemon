"""Direct custom-image upload bridge for the lightweight Lots cards."""

from __future__ import annotations

try:
    import streamlit.components.v2 as components_v2
except Exception:  # pragma: no cover - depends on Streamlit runtime version
    components_v2 = None


_lot_image_upload_component = None


def component_v2_available() -> bool:
    return components_v2 is not None


def _get_lot_image_upload_component():
    global _lot_image_upload_component
    if components_v2 is None:
        return None
    if _lot_image_upload_component is not None:
        return _lot_image_upload_component

    js = r"""
    export default function(component) {
        const { parentElement, setTriggerValue } = component;
        parentElement.style.height = "0px";
        parentElement.style.minHeight = "0px";
        parentElement.style.overflow = "hidden";
        parentElement.style.pointerEvents = "none";

        const doc = parentElement.ownerDocument;
        const win = doc.defaultView || window;
        const stateKey = "__pokestockLotImageUploadBridge";
        const state = win[stateKey] || {};
        if (state.listener) {
            try { doc.removeEventListener("click", state.listener, true); } catch (e) {}
        }

        const accepted = new Set(["image/jpeg", "image/png", "image/webp"]);

        function removeInput(input) {
            try { input.remove(); } catch (e) {}
        }

        const listener = (event) => {
            const target = event.target;
            if (!target || !target.closest) return;
            const button = target.closest(".ps-lot-inline-image-btn");
            if (!button || !doc.contains(button)) return;

            event.preventDefault();
            event.stopPropagation();

            const input = doc.createElement("input");
            input.type = "file";
            input.accept = "image/jpeg,image/png,image/webp";
            input.style.position = "fixed";
            input.style.left = "-10000px";
            input.style.top = "-10000px";
            input.style.opacity = "0";
            input.style.width = "1px";
            input.style.height = "1px";

            input.onchange = () => {
                const file = input.files && input.files[0];
                if (!file) {
                    removeInput(input);
                    return;
                }
                if (file.type && !accepted.has(file.type)) {
                    removeInput(input);
                    return;
                }
                const reader = new FileReader();
                reader.onload = () => {
                    setTriggerValue("upload", {
                        id: "lot-image-" + Date.now() + "-" + Math.random().toString(36).slice(2),
                        lot_idx: Number(button.dataset.lotIdx || 0),
                        card_idx: Number(button.dataset.cardIdx || 0),
                        filename: file.name || "",
                        mime: file.type || "",
                        data_url: String(reader.result || "")
                    });
                    removeInput(input);
                };
                reader.onerror = () => removeInput(input);
                reader.readAsDataURL(file);
            };

            doc.body.appendChild(input);
            input.click();
        };

        doc.addEventListener("click", listener, true);
        win[stateKey] = { listener };

        return () => {
            try { doc.removeEventListener("click", listener, true); } catch (e) {}
        };
    }
    """

    _lot_image_upload_component = components_v2.component(
        "pokestock_lot_image_upload_bridge",
        html='<div aria-hidden="true"></div>',
        css="",
        js=js,
        isolate_styles=False,
    )
    return _lot_image_upload_component


def render_lot_image_upload_bridge(*, key: str):
    component = _get_lot_image_upload_component()
    if component is None:
        return None

    def _noop():
        return None

    result = component(
        key=f"lot_image_upload_bridge_{key}",
        data={"key": key},
        default={},
        width="stretch",
        height=0,
        on_upload_change=_noop,
    )
    return getattr(result, "upload", None) if result is not None else None
