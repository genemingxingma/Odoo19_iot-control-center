/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onMounted, onWillUnmount, onWillUpdateProps, useState } from "@odoo/owl";

export class DelayCountdownField extends Component {
    static template = "iot_control_center.DelayCountdownField";
    static props = {
        ...standardFieldProps,
    };
    static supportedTypes = ["float", "integer"];

    setup() {
        this.state = useState({ tick: 0 });
        this._baseRemainingSec = this._remainingFromProps(this.props);
        this._baseTs = Date.now();
        this._timer = null;

        onMounted(() => {
            this._timer = setInterval(() => {
                this.state.tick += 1;
            }, 1000);
        });

        onWillUnmount(() => {
            if (this._timer) {
                clearInterval(this._timer);
                this._timer = null;
            }
        });

        onWillUpdateProps((nextProps) => {
            const nextSec = this._remainingFromProps(nextProps);
            const currentSec = this._remainingNow(this.props);
            const currentActive = this._isActive(this.props);
            const nextActive = this._isActive(nextProps);
            if (currentActive !== nextActive || Math.abs(nextSec - currentSec) > 2) {
                this._baseRemainingSec = nextSec;
                this._baseTs = Date.now();
            }
        });
    }

    _isActive(props) {
        return Boolean(props?.record?.data?.delay_active);
    }

    _remainingFromProps(props) {
        const raw = Number(props?.value || 0);
        return Math.max(Math.round(raw * 60), 0);
    }

    _remainingNow(props) {
        if (!this._isActive(props)) {
            return 0;
        }
        const elapsedSec = Math.floor((Date.now() - this._baseTs) / 1000);
        return Math.max(this._baseRemainingSec - elapsedSec, 0);
    }

    get displayValue() {
        const sec = this._remainingNow(this.props);
        const mm = Math.floor(sec / 60);
        const ss = sec % 60;
        return `${mm}:${String(ss).padStart(2, "0")}`;
    }
}

registry.category("fields").add("delay_countdown", {
    component: DelayCountdownField,
    displayName: "Delay Countdown",
    supportedTypes: ["float", "integer"],
});

