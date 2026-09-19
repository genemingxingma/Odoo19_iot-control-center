param([string]$PlatformIOHome = "$env:USERPROFILE/.platformio")
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$src = Join-Path $root 'firmware/instruments/maintenance'
$out = Join-Path $root 'firmware/instruments/out/maintenance'
$cc = Join-Path $PlatformIOHome 'packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-gcc.exe'
$objcopy = Join-Path $PlatformIOHome 'packages/toolchain-xtensa-esp32/bin/xtensa-esp32-elf-objcopy.exe'
New-Item -ItemType Directory -Path $out -Force | Out-Null
& $cc -Os -Wall -Wextra -Werror -mtext-section-literals -ffreestanding -fno-builtin -fno-stack-protector -nostdlib "-Wl,-T,$src/usb_screen_bridge.ld" "-Wl,-Map,$out/bridge.map" "$src/usb_screen_bridge.S" "$src/usb_screen_bridge.c" -o "$out/bridge.elf"
if ($LASTEXITCODE) { throw 'RAM bridge build failed' }
& $objcopy -O binary --only-section=.text "$out/bridge.elf" "$out/bridge-text.bin"
if ($LASTEXITCODE) { throw 'IRAM extraction failed' }
& $objcopy -O binary --only-section=.data "$out/bridge.elf" "$out/bridge-data.bin"
if ($LASTEXITCODE) { throw 'DRAM extraction failed' }
Get-FileHash -Algorithm SHA256 "$out/bridge-text.bin", "$out/bridge-data.bin"
