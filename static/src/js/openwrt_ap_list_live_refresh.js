import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { ListController } from "@web/views/list/list_controller";
import { useEffect } from "@odoo/owl";

patch(ListController.prototype, {
    setup() {
        super.setup(...arguments);
        this.iotOpenwrtOrm = useService("orm");

        useEffect(
            () => {
                if (this.props.resModel !== "iot.openwrt.ap" || !this.model.isReady) {
                    return;
                }
                const ids = (this.model.root.records || [])
                    .map((record) => record.resId)
                    .filter((id) => Number.isInteger(id));
                if (!ids.length) {
                    return;
                }
                const signature = ids.join(",");
                const now = Date.now();
                if (
                    this.__iotOpenwrtLastRefreshSignature === signature &&
                    now - (this.__iotOpenwrtLastRefreshAt || 0) < 30000
                ) {
                    return;
                }
                this.__iotOpenwrtLastRefreshSignature = signature;
                this.__iotOpenwrtLastRefreshAt = now;
                Promise.resolve().then(async () => {
                    try {
                        await this.iotOpenwrtOrm.call("iot.openwrt.ap", "refresh_live_stats", [ids]);
                        await this.model.root.load();
                    } catch {
                        // Keep cached data if refresh fails.
                    }
                });
            },
            () => [
                this.props.resModel,
                this.model.isReady,
                ...(this.model.root.records || []).map((record) => record.resId),
            ]
        );
    },
});
