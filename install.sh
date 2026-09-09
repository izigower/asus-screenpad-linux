#!/bin/bash
# Installe les outils ScreenPad.
set -e
[[ $EUID -eq 0 ]] || { echo "Relance avec : sudo $0"; exit 1; }
ICI="$(cd "$(dirname "$0")" && pwd)"

command -v modprobe >/dev/null || { echo "modprobe introuvable"; exit 1; }
if ! modprobe acpi_call 2>/dev/null; then
  echo "Le module acpi_call est requis :"
  echo "  Arch          : pacman -S acpi_call-dkms"
  echo "  Debian/Ubuntu : apt install acpi-call-dkms"
  exit 1
fi
echo acpi_call > /etc/modules-load.d/acpi_call.conf

install -Dm755 "$ICI/bin/screenpad-power"     /usr/local/bin/screenpad-power
install -Dm755 "$ICI/bin/screenpad-touchmode" /usr/local/bin/screenpad-touchmode
install -Dm644 "$ICI/systemd/screenpad.service" /etc/systemd/system/screenpad.service
systemctl daemon-reload
systemctl enable --now screenpad.service

echo
echo "Installé. État du panneau : $(/usr/local/bin/screenpad-power status)"
echo "  0x100a0 = allumé, 0x10000 = éteint"
echo
echo "Le panneau devrait maintenant apparaître comme écran. Repère son"
echo "connecteur, puis configure-le (voir le README) :"
command -v hyprctl >/dev/null && hyprctl monitors 2>/dev/null | grep -E "^Monitor" || true
