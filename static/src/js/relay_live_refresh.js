/** @odoo-module **/
import { onMounted, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { listView } from "@web/views/list/list_view";
import { kanbanView } from "@web/views/kanban/kanban_view";
import { formView } from "@web/views/form/form_view";

export const RELAY_REFRESH_MS = 2000;

export function canRefreshRelay(doc, root) {
    if (doc.hidden || !root || root.dirty || root.editedRecord) return false;
    if (doc.querySelector(".modal.show, .o_dialog, .o-dropdown--menu")) return false;
    const focused = doc.activeElement;
    // Odoo focuses the search box when opening a view. Loading records does
    // not replace that search input, so it must not disable live feedback.
    if (focused?.closest?.(".o_searchview")) return true;
    return !focused || (!focused.isContentEditable && !["INPUT", "TEXTAREA", "SELECT"].includes(focused.tagName));
}

function liveController(BaseController) {
    return class extends BaseController {
        setup() {
            super.setup();
            let disposed = false;
            let timer;
            const schedule = () => {
                if (!disposed) timer = setTimeout(refresh, RELAY_REFRESH_MS);
            };
            const refresh = async () => {
                try {
                    if (!disposed && canRefreshRelay(document, this.model.root)) {
                        await this.model.load();
                    }
                } catch {
                    // Keep the last confirmed data and retry on the next tick.
                } finally {
                    schedule();
                }
            };
            onMounted(schedule);
            onWillUnmount(() => {
                disposed = true;
                clearTimeout(timer);
            });
        }
    };
}

for (const [name, view] of [["list", listView], ["kanban", kanbanView], ["form", formView]]) {
    registry.category("views").add("iot_relay_live_" + name, {
        ...view, Controller: liveController(view.Controller),
    });
}
