"""Read bounded, credential-free USB diagnostics from the new washer firmware."""
import argparse
import json
from pathlib import Path
import time
import serial


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True)
    p.add_argument('--seconds',type=int,default=30)
    p.add_argument('--receipt',type=Path,required=True)
    a=p.parse_args()
    if a.receipt.exists() or not 1<=a.seconds<=300: raise RuntimeError('Use a new receipt and bounded duration')
    port=serial.Serial(port=None,baudrate=115200,timeout=0.2,write_timeout=1)
    port.dtr=False; port.rts=False; port.port=a.port; port.open()
    readings=[]; deadline=time.monotonic()+a.seconds; next_request=0
    try:
        while time.monotonic()<deadline:
            if time.monotonic()>=next_request:
                port.write(b'STATUS\n'); next_request=time.monotonic()+2
            line=port.readline(4096)
            if not line.startswith(b'IOT_STATUS '): continue
            try: value=json.loads(line[11:])
            except (ValueError,UnicodeError): continue
            readings.append(value)
            print(json.dumps(value),flush=True)
            if any(value.get(k) for k in ('commissioned','enable_pin','inlet_a_pin','inlet_b_pin','drain_pwm','overflow_pwm','motor_running')):
                raise RuntimeError('Output-locked test invariant failed; do not reconnect actuator power')
    finally:
        port.close()
        a.receipt.write_text(json.dumps(readings,indent=2),encoding='utf-8')
    if not readings: raise RuntimeError('No valid firmware diagnostics received')


if __name__=='__main__': main()
