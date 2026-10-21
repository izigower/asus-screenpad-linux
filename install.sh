#!/bin/bash
# Installe la partie système des outils ScreenPad (root).
# Pour tout installer, lancer plutôt ./setup en utilisateur normal.
set -e
[[ $EUID -eq 0 ]] || { echo "Relance avec : sudo $0"; exit 1; }
ICI="$(cd "$(dirname "$0")" && pwd)"
UTILISATEUR=${SCREENPAD_USER:-${SUDO_USER:-}}

command -v modprobe >/dev/null || { echo "modprobe introuvable"; exit 1; }
if ! modprobe acpi_call 2>/dev/null; then
  echo "Le module acpi_call est requis :"
  echo "  Arch          : pacman -S acpi_call-dkms"
  echo "  Debian/Ubuntu : apt install acpi-call-dkms"
  exit 1
fi
mkdir -p /etc/modules-load.d
echo acpi_call > /etc/modules-load.d/acpi_call.conf

install -Dm755 "$ICI/bin/screenpad-power"     /usr/local/bin/screenpad-power
install -Dm755 "$ICI/bin/screenpad-touchmode" /usr/local/bin/screenpad-touchmode
install -Dm644 "$ICI/systemd/screenpad.service" /etc/systemd/system/screenpad.service

# Lecture du pad par l'utilisateur de la session (geste à 3 doigts, croix).
install -Dm644 "$ICI/udev/72-screenpad-geste-uaccess.rules" \
  /etc/udev/rules.d/72-screenpad-geste-uaccess.rules
udevadm control --reload-rules 2>/dev/null || true
udevadm trigger --subsystem-match=input 2>/dev/null || true

# Le lanceur et les raccourcis appellent ces deux outils par sudo -n.
if [[ -n $UTILISATEUR && $UTILISATEUR != root ]]; then
  REGLE=$(mktemp)
  cat > "$REGLE" <<EOF
# Outils ScreenPad sans mot de passe (lanceur, Fn+F6, gestes).
$UTILISATEUR ALL=(root) NOPASSWD: /usr/local/bin/screenpad-power, /usr/local/bin/screenpad-touchmode
EOF
  if visudo -cf "$REGLE" >/dev/null; then
    install -Dm440 "$REGLE" /etc/sudoers.d/screenpad
  else
    echo "Règle sudoers invalide, non installée" >&2
  fi
  rm -f "$REGLE"
fi

systemctl daemon-reload
systemctl enable --now screenpad.service

echo
echo "Installé. État du panneau : $(/usr/local/bin/screenpad-power status)"
echo "  0x100a0 = allumé, 0x10000 = éteint"
