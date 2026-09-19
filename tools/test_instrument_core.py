"""Compile and exercise the exact MCU-independent C++ safety core on the host."""
import pathlib
import shutil
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
compiler = shutil.which("clang++") or shutil.which("g++")
if not compiler:
    raise SystemExit("A C++17 host compiler is required; tests were not run.")
with tempfile.TemporaryDirectory(prefix="imytest-instrument-test-") as tmp:
    binary = pathlib.Path(tmp) / "control_test.exe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ROOT / "firmware/instruments/lib/InstrumentCore/src"),
        str(ROOT / "firmware/instruments/test/control_test.cpp"), "-o", str(binary)], check=True)
    subprocess.run([str(binary)], check=True)
    ui = pathlib.Path(tmp) / "ui_test.exe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ROOT / "firmware/instruments/test"),
        "-I", str(ROOT / "firmware/instruments/include"),
        "-I", str(ROOT / "firmware/instruments/lib/InstrumentCore/src"),
        str(ROOT / "firmware/instruments/test/ui_test.cpp"), "-o", str(ui)], check=True)
    preview = ROOT / "deploy/artifacts/instrument-screen-commands.txt"
    preview.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ui), str(preview)], check=True)
    panel = pathlib.Path(tmp) / "heater_panel_test.exe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ROOT / "firmware/instruments/lib/InstrumentCore/src"),
        str(ROOT / "firmware/instruments/test/heater_panel_test.cpp"), "-o", str(panel)], check=True)
    subprocess.run([str(panel)], check=True)
    setup = pathlib.Path(tmp) / "washer_setup_test.exe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ROOT / "firmware/instruments/lib/InstrumentCore/src"),
        str(ROOT / "firmware/instruments/test/washer_setup_test.cpp"), "-o", str(setup)], check=True)
    subprocess.run([str(setup)], check=True)
    catalog = pathlib.Path(tmp) / "catalog_test.exe"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(ROOT / "firmware/instruments/include"),
        "-I", str(ROOT / "firmware/instruments/lib/InstrumentCore/src"),
        "-I", str(ROOT / "firmware/instruments/.pio/libdeps/washer/ArduinoJson/src"),
        str(ROOT / "firmware/instruments/test/catalog_test.cpp"), "-o", str(catalog)], check=True)
    subprocess.run([str(catalog)], check=True)
