/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { GraphRenderer } from "@web/views/graph/graph_renderer";
import { GraphModel } from "@web/views/graph/graph_model";
function isTHReading(renderer) {
    return renderer?.model?.metaData?.resModel === "iot.th.reading";
}

function normalizeMeasures(renderer) {
    const md = renderer.model.metaData || {};
    const allowed = ["temperature", "humidity"];
    const current = Array.isArray(md.iotMeasures) ? md.iotMeasures.filter((m) => allowed.includes(m)) : [];
    if (current.length) {
        return current;
    }
    return ["temperature"];
}

patch(GraphRenderer.prototype, {
    _iotGetActiveMeasures() {
        if (!isTHReading(this)) {
            return [this.model.metaData.measure];
        }
        return normalizeMeasures(this);
    },

    onMeasureSelected({ measure }) {
        if (isTHReading(this)) {
            const selected = normalizeMeasures(this);
            let next = selected.slice();
            if (next.includes(measure)) {
                if (next.length > 1) {
                    next = next.filter((m) => m !== measure);
                }
            } else {
                next.push(measure);
            }
            this.model.updateMetaData({
                iotMeasures: next,
                measure: next[0],
            });
            return;
        }
        return super.onMeasureSelected({ measure });
    },
});

patch(GraphModel.prototype, {
    _getData(dataPoints, forceUseAllDataPoints) {
        const result = super._getData(dataPoints, forceUseAllDataPoints);
        if (this.metaData?.resModel !== "iot.th.reading" || this.metaData?.mode !== "line") {
            return result;
        }
        // Odoo graph model initializes missing buckets with 0.
        // For TH trend we must treat missing buckets as null to avoid false drops to zero.
        for (const dataset of result.datasets || []) {
            const data = dataset?.data || [];
            const domains = dataset?.domains || [];
            for (let i = 0; i < data.length; i++) {
                const d = domains[i];
                const hasPoint = Array.isArray(d) ? d.length > 0 : Boolean(d);
                if (!hasPoint) {
                    data[i] = null;
                }
            }
        }
        return result;
    },

    async _loadDataPoints(metaData) {
        if (metaData?.resModel !== "iot.th.reading") {
            return super._loadDataPoints(metaData);
        }
        const { domain, fields, groupBy, resModel } = metaData;
        const selectedMeasures = Array.isArray(metaData.iotMeasures) && metaData.iotMeasures.length
            ? metaData.iotMeasures
            : [metaData.measure || "temperature"];
        const useTemperature = selectedMeasures.includes("temperature");
        const useHumidity = selectedMeasures.includes("humidity");
        const numbering = {};
        const groups = await this.orm.formattedReadGroup(
            resModel,
            domain,
            groupBy.map((gb) => gb.spec),
            ["__count", "temperature:avg", "humidity:avg"],
            {
                // Do not backfill missing temporal buckets with synthetic zeros.
                context: { ...this.searchParams.context, fill_temporal: false },
            }
        );
        const dataPoints = [];
        for (const group of groups) {
            if (!group.__count || group.__count <= 0) {
                continue;
            }
            const labels = [];
            const rawValues = [];
            for (const gb of groupBy) {
                let label;
                const val = group[gb.spec];
                rawValues.push({ [gb.spec]: val });
                const fieldName = gb.fieldName;
                const fieldDef = fields[fieldName] || {};
                const type = fieldDef.type;
                if (type === "boolean") {
                    label = `${val}`;
                } else if (type === "integer") {
                    label = val === false ? "0" : `${val}`;
                } else if (val === false) {
                    label = this._getDefaultFilterLabel(gb);
                } else if (["many2many", "many2one"].includes(type)) {
                    const [id, name] = val;
                    const key = JSON.stringify([fieldName, name]);
                    if (!numbering[key]) {
                        numbering[key] = {};
                    }
                    const numbers = numbering[key];
                    if (!numbers[id]) {
                        numbers[id] = Object.keys(numbers).length + 1;
                    }
                    label = numbers[id] === 1 ? name : `${name} (${numbers[id]})`;
                } else if (type === "selection") {
                    const selected = (fieldDef.selection || []).find((s) => s[0] === val);
                    label = selected ? selected[1] : val;
                } else if (["date", "datetime"].includes(type)) {
                    label = val[1];
                } else {
                    label = val;
                }
                labels.push(label);
            }

            const common = {
                count: group.__count,
                domain: group.__domain,
            };
            if (useTemperature) {
                const tempVal = group["temperature:avg"];
                if (tempVal !== false && tempVal !== null && tempVal !== undefined) {
                dataPoints.push({
                    ...common,
                    value: Number(tempVal),
                    labels: [...labels, "Temperature"],
                    identifier: JSON.stringify([...rawValues, { metric: "temperature" }]),
                    cumulatedStart: 0,
                });
                }
            }
            if (useHumidity) {
                const humVal = group["humidity:avg"];
                if (humVal !== false && humVal !== null && humVal !== undefined) {
                dataPoints.push({
                    ...common,
                    value: Number(humVal),
                    labels: [...labels, "Humidity"],
                    identifier: JSON.stringify([...rawValues, { metric: "humidity" }]),
                    cumulatedStart: 0,
                });
                }
            }
        }
        metaData.measure = useTemperature ? "temperature" : "humidity";
        metaData.allIntegers = false;
        return [dataPoints, new Set()];
    },
});
