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
        const timeMode = (this.searchParams?.context?.iot_time_mode || metaData?.context?.iot_time_mode || "hour").toLowerCase();
        const targetInterval = "hour";
        const effectiveGroupBy = (groupBy || []).map((gb) => {
            const isStringGroupBy = typeof gb === "string";
            const rawSpec = isStringGroupBy ? gb : (gb?.spec || "");
            const rawFieldName = isStringGroupBy
                ? gb.split(":")[0]
                : (gb?.fieldName || (rawSpec ? rawSpec.split(":")[0] : ""));
            const fieldName = rawFieldName || "";
            const spec = rawSpec || fieldName;
            const isReportedAt =
                fieldName === "reported_at" ||
                fieldName.startsWith("reported_at:") ||
                spec === "reported_at" ||
                spec.startsWith("reported_at:");
            if (isReportedAt) {
                return { fieldName: "reported_at", spec: `reported_at:${targetInterval}` };
            }
            if (isStringGroupBy) {
                return { fieldName, spec };
            }
            return { ...gb, fieldName, spec };
        });
        const selectedMeasures = Array.isArray(metaData.iotMeasures) && metaData.iotMeasures.length
            ? metaData.iotMeasures
            : [metaData.measure || "temperature"];
        const useTemperature = selectedMeasures.includes("temperature");
        const useHumidity = selectedMeasures.includes("humidity");
        const numbering = {};
        if (timeMode === "raw") {
            const descendingRecords = await this.orm.searchRead(
                resModel,
                domain,
                ["id", "reported_at", "temperature", "humidity", "sensor_id", "node_id", "sensor_code"],
                {
                    context: { ...this.searchParams.context },
                    order: "reported_at desc,id desc",
                    limit: 10000,
                }
            );
            const records = [...(descendingRecords || [])].reverse();
            const dataPoints = [];
            for (const record of records || []) {
                const labels = [];
                const rawValues = [];
                for (const gb of effectiveGroupBy) {
                    const fieldName = gb.fieldName;
                    const fieldDef = fields[fieldName] || {};
                    const type = fieldDef.type;
                    let value;
                    if (fieldName === "reported_at") {
                        value = record.reported_at;
                    } else {
                        value = record[fieldName];
                    }
                    rawValues.push({ [gb.spec]: value });
                    let label;
                    if (["date", "datetime"].includes(type)) {
                        label = String(value || "");
                    } else if (["many2many", "many2one"].includes(type) && Array.isArray(value)) {
                        label = value[1] || "";
                    } else if (value === false || value === null || value === undefined) {
                        label = this._getDefaultFilterLabel(gb);
                    } else {
                        label = String(value);
                    }
                    labels.push(label);
                }
                const common = {
                    count: 1,
                    domain: [["id", "=", record.id]],
                };
                if (useTemperature && record.temperature !== false && record.temperature !== null && record.temperature !== undefined) {
                    dataPoints.push({
                        ...common,
                        value: Number(record.temperature),
                        labels: [...labels, "Temperature"],
                        identifier: JSON.stringify([...rawValues, { metric: "temperature", id: record.id }]),
                        cumulatedStart: 0,
                    });
                }
                if (useHumidity && record.humidity !== false && record.humidity !== null && record.humidity !== undefined) {
                    dataPoints.push({
                        ...common,
                        value: Number(record.humidity),
                        labels: [...labels, "Humidity"],
                        identifier: JSON.stringify([...rawValues, { metric: "humidity", id: record.id }]),
                        cumulatedStart: 0,
                    });
                }
            }
            metaData.measure = useTemperature ? "temperature" : "humidity";
            metaData.allIntegers = false;
            return [dataPoints, new Set()];
        }
        const groups = await this.orm.formattedReadGroup(
            resModel,
            domain,
            effectiveGroupBy.map((gb) => gb.spec),
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
            for (const gb of effectiveGroupBy) {
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
                    // Use a stable bucket key to avoid 12h-label collisions
                    // (e.g., 01:00 AM and 01:00 PM both rendered as "01:00").
                    if (Array.isArray(val)) {
                        label = String(val[0] ?? val[1] ?? "");
                    } else {
                        label = String(val ?? "");
                    }
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
