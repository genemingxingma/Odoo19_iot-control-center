/** @odoo-module **/
import { Component, onWillStart, onWillDestroy, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { deserializeDateTime, formatDateTime } from "@web/core/l10n/dates";
import { formatInteger } from "@web/views/fields/formatters";

export class IoTOperationsOverview extends Component {
    static template = "iot_control_center.OperationsOverview";
    static props = ["*"];

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({ data: null, loading: false, failed: false });
        this.disposed = false;
        onWillStart(() => this.refresh());
        onWillDestroy(() => { this.disposed = true; });
    }

    async refresh() {
        if (this.state.loading) return;
        this.state.loading = true;
        try {
            const data = await this.orm.call("iot.control.board", "get_overview", []);
            if (!this.disposed) {
                this.state.data = data;
                this.state.failed = false;
            }
        } catch {
            if (!this.disposed) this.state.failed = true;
        } finally {
            if (!this.disposed) this.state.loading = false;
        }
    }

    open(action) {
        return this.action.doAction(action);
    }

    number(value) {
        return formatInteger(value);
    }

    get updatedAt() {
        const value = this.state.data?.generated_at;
        return value ? formatDateTime(deserializeDateTime(value)) : "";
    }
}

registry.category("actions").add("iot_control_center.operations_overview", IoTOperationsOverview);
