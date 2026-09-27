import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../static/src/js/relay_live_refresh.js", import.meta.url), "utf8")
    .replace(/^import .*;$/gm, "").replace(/\bexport /g, "");
const registered = new Map();
const mounted = [];
const unmounted = [];
const timers = new Map();
let timerId = 0;
let loads = 0;
let finishLoad;
class Controller {
    setup() {
        this.model = { root: { dirty: false }, load: () => {
            loads++;
            return new Promise((resolve) => { finishLoad = resolve; });
        }};
    }
}
const doc = { hidden: false, activeElement: { tagName: "BODY" }, querySelector: () => null };
const context = vm.createContext({
    onMounted: (callback) => mounted.push(callback), onWillUnmount: (callback) => unmounted.push(callback),
    registry: { category: () => ({ add: (name, view) => registered.set(name, view) }) },
    listView: { Controller }, kanbanView: { Controller }, formView: { Controller },
    document: doc, setTimeout: (callback, delay) => {
        assert.equal(delay, 2000);
        timers.set(++timerId, callback);
        return timerId;
    }, clearTimeout: (id) => timers.delete(id),
});
vm.runInContext(source + "\nglobalThis.policy = canRefreshRelay;", context);
assert.equal(registered.size, 3);
assert.equal(context.policy(doc, { dirty: false }), true);
assert.equal(context.policy({ ...doc, hidden: true }, {}), false);
assert.equal(context.policy(doc, { dirty: true }), false);
assert.equal(context.policy(doc, { editedRecord: {} }), false);
for (const tagName of ["INPUT", "TEXTAREA", "SELECT"]) {
    assert.equal(context.policy({ ...doc, activeElement: { tagName } }, {}), false);
}
assert.equal(context.policy({ ...doc, activeElement: { isContentEditable: true } }, {}), false);
assert.equal(context.policy({ ...doc, querySelector: () => ({}) }, {}), false);
const searchFocus = { tagName: "INPUT", closest: (selector) => selector === ".o_searchview" ? {} : null };
assert.equal(context.policy({ ...doc, activeElement: searchFocus }, {}), true);
assert.equal(context.policy({ ...doc, activeElement: searchFocus }, { dirty: true }), false);
doc.activeElement = searchFocus;
const live = new (registered.get("iot_relay_live_kanban").Controller)();
live.setup();
mounted[0]();
assert.equal(timers.size, 1);
const callback = timers.values().next().value;
timers.clear();
const refreshing = callback();
assert.equal(loads, 1);
assert.equal(timers.size, 0, "No overlapping polling while the request is pending");
unmounted[0]();
finishLoad();
await refreshing;
assert.equal(timers.size, 0, "Unmounted view must not restart polling");
console.log("RELAY_LIVE_REFRESH_OK: registrations, editing/modal/visibility guards, no overlap, cleanup");
