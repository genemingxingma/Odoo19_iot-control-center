"""Gate application stack frames emitted by the ESP8266 compiler."""
import json
from pathlib import Path

source = Path(__file__).resolve().parents[1] / "firmware/esp8266_relay/.pio/build/esp12e/src/esp8266_relay.ino.cpp.su"
limits = {"publishStatus": 256, "publishTelemetry": 256, "publishReport": 384,
          "applyScheduleSet": 768, "handleCommand": 384}
frames = {}
for line in source.read_text(encoding="utf-8").splitlines():
    parts = line.split("\t")
    if len(parts) != 3:
        continue
    for name, maximum in limits.items():
        if name in parts[0]:
            assert parts[2] == "static", f"unbounded frame: {name}"
            size = int(parts[1])
            assert size <= maximum, f"stack regression: {name}: {size} > {maximum}"
            frames[name] = max(size, frames.get(name, 0))
assert set(frames) == set(limits), "missing compiler stack evidence; rebuild with -fstack-usage"
# This is the application part of the callback chain, not a claim that driver
# or serializer stack frames are zero. Reserve at least half of the 4KB stack.
chain = sum(frames[name] for name in ("handleCommand", "applyScheduleSet", "publishStatus", "publishReport"))
assert chain <= 2048, f"callback chain leaves too little driver headroom: {chain}"
print("RELAY_STACK_GATE_OK", json.dumps({"frames": frames, "application_chain_bytes": chain}))
