#!/bin/bash
# Lancé dans le conteneur, en utilisateur test : un scénario par appel.
set -u
REPO=/repo
export SCREENPAD_SYSROOT=/fake/root SCREENPAD_POWER=/usr/local/sbin/screenpad-power-faux
export PATH=$HOME/.local/bin:$PATH
touch /fake/appels.log; chmod 666 /fake/appels.log
ECHECS=0
vrai() { if eval "$1"; then echo "    ok   $2"; else echo "    ÉCHEC $2"; ECHECS=$((ECHECS+1)); fi; }
compte() { grep -cF -- "$2" "$1" 2>/dev/null || echo 0; }

machine() {  # $1 = fabricant
  mkdir -p /fake/root/sys/class/dmi/id /fake/root/sys/bus/i2c/devices/i2c-GDX1515:00
  echo "$1" > /fake/root/sys/class/dmi/id/sys_vendor
  echo "Zenbook UX5400EA_UX5400EA" > /fake/root/sys/class/dmi/id/product_name
}
omarchy_neuf() {
  mkdir -p ~/.config/hypr
  cp /usr/share/omarchy/config/hypr/{monitors,input,bindings}.lua ~/.config/hypr/
  quickshell -n -p /usr/share/omarchy/shell & disown
}
lancer() { (cd "$REPO" && ./setup "$@") > /fake/sortie.txt 2>&1; echo $? > /fake/code; }
code() { cat /fake/code; }

case $1 in
omarchy)
  machine "ASUSTeK COMPUTER INC."; omarchy_neuf
  lancer --yes
  vrai '[[ $(code) == 0 ]]' "setup se termine sans erreur"
  vrai '[[ -x /usr/local/bin/screenpad-power && -x /usr/local/bin/screenpad-touchmode ]]' "outils root installés"
  vrai 'sudo grep -q "^test ALL=(root) NOPASSWD: /usr/local/bin/screenpad-power, /usr/local/bin/screenpad-touchmode" /etc/sudoers.d/screenpad' "règle sudoers pour l'utilisateur"
  vrai 'sudo visudo -c >/dev/null' "sudoers valide"
  vrai '[[ -f /etc/udev/rules.d/72-screenpad-geste-uaccess.rules && -f /etc/modules-load.d/acpi_call.conf ]]' "règles udev + module au boot"
  vrai 'grep -q "systemctl enable --now screenpad.service" /fake/appels.log' "screenpad.service activé"
  vrai 'grep -qF "hl.monitor({ output = \"HDMI-A-2\", mode = \"1080x2160@60\", position = \"0x900\", scale = 2, transform = 3 })" ~/.config/hypr/monitors.lua' "écran du pad sous l'écran principal (0x900)"
  vrai 'grep -qF "hl.monitor({ output = \"eDP-1\", mode = \"preferred\", position = \"0x0\", scale = 2 })" ~/.config/hypr/monitors.lua' "écran principal ancré en 0x0"
  vrai 'grep -qF "output = \"HDMI-A-2\" })" ~/.config/hypr/input.lua' "tactile rattaché au pad"
  vrai 'grep -qF "\"screenpad-cycle\", { locked = true }" ~/.config/hypr/bindings.lua' "raccourci Fn+F6"
  vrai 'for f in monitors input bindings; do luac -p ~/.config/hypr/$f.lua || exit 1; done' "les 3 fichiers Lua restent valides"
  vrai 'grep -q "hyprctl reload" /fake/appels.log' "Hyprland rechargé"
  vrai 'grep -q "pacman -S --needed --noconfirm python-gobject gtk4 libadwaita gtk4-layer-shell wtype" /fake/appels.log' "dépendances manquantes proposées à pacman"
  vrai 'ls ~/.local/share/screenpad/screenpad-{dock,geste,screensaver}.py >/dev/null && ls ~/.local/bin/screenpad-{dock,cycle,toggle,no-notifications} >/dev/null' "scripts utilisateur installés"
  vrai 'grep -q "systemctl --user enable screenpad-geste.service screenpad-screensaver.service screenpad-dock-autostart.service" /fake/appels.log' "services utilisateur activés"
  vrai 'grep -q "modelData.name !== \"HDMI-A-2\"" ~/.config/omarchy/plugins/test.notifications/Service.qml' "notifications masquées sur le pad"
  vrai '! grep -q "Reste à faire" /fake/sortie.txt' "rien ne reste à faire"
  avant=$(md5sum ~/.config/hypr/*.lua)
  lancer --yes
  vrai '[[ $(code) == 0 ]]' "2e passage sans erreur"
  vrai '[[ "$(md5sum ~/.config/hypr/*.lua)" == "$avant" ]]' "2e passage : config Hyprland inchangée"
  vrai '[[ $(ls -d ~/.config/omarchy/plugins/*/ | wc -l) == 1 ]]' "2e passage : un seul clone du plugin"
  ;;
mako)
  machine "ASUSTeK COMPUTER INC."
  mkdir -p ~/.config/mako; printf 'font=Sans 10\n\n[urgency=high]\nborder-color=#f00\n' > ~/.config/mako/config
  mako & disown
  lancer --yes
  vrai '[[ $(code) == 0 ]]' "setup se termine sans erreur"
  vrai '[[ $(head -1 ~/.config/mako/config) == output=eDP-1 ]]' "mako : output=eDP-1 en tête (option globale)"
  vrai 'grep -q "^\[urgency=high\]" ~/.config/mako/config && grep -q "^font=Sans 10" ~/.config/mako/config' "mako : reste de la config conservé"
  vrai 'grep -q "makoctl reload" /fake/appels.log' "mako rechargé"
  vrai 'grep -q "Pas Omarchy" /fake/sortie.txt && grep -qF "hl.monitor({ output = \"HDMI-A-2\"" /fake/sortie.txt' "hors Omarchy : lignes Hyprland affichées"
  vrai '[[ ! -e ~/.config/hypr/monitors.lua ]]' "hors Omarchy : config Hyprland non touchée"
  lancer --yes
  vrai '[[ $(compte ~/.config/mako/config output=) == 1 ]]' "2e passage : une seule ligne output"
  ;;
dunst)
  machine "ASUSTeK COMPUTER INC."
  mkdir -p ~/.config/dunst; printf '[global]\n    font = Sans 10\n\n[urgency_low]\n    timeout = 5\n' > ~/.config/dunst/dunstrc
  dunst & disown
  lancer --yes
  vrai '[[ $(code) == 0 ]]' "setup se termine sans erreur"
  vrai '[[ $(sed -n 2p ~/.config/dunst/dunstrc | xargs) == "monitor = eDP-1" ]]' "dunst : monitor juste sous [global]"
  vrai 'grep -q "follow = none" ~/.config/dunst/dunstrc && grep -q "^\[urgency_low\]" ~/.config/dunst/dunstrc' "dunst : follow = none, reste conservé"
  lancer --yes
  vrai '[[ $(compte ~/.config/dunst/dunstrc "monitor =") == 1 ]]' "2e passage : une seule ligne monitor"
  ;;
pas-asus)
  machine "LENOVO"
  (cd "$REPO" && echo n | ./setup) > /fake/sortie.txt 2>&1; echo $? > /fake/code
  vrai '[[ $(code) == 1 ]]' "s'arrête si on refuse de continuer"
  vrai '[[ ! -e /usr/local/bin/screenpad-power && ! -e ~/.local/bin/screenpad-dock ]]' "rien n'est installé"
  ;;
sans-acpi)
  machine "ASUSTeK COMPUTER INC."; touch /fake/sans-acpi
  lancer --yes
  vrai 'grep -q "pacman -S --needed --noconfirm acpi_call-dkms linux-headers" /fake/appels.log' "acpi_call proposé à pacman"
  vrai '[[ $(code) == 0 ]]' "continue une fois acpi_call installé"
  ;;
sans-session)
  machine "ASUSTeK COMPUTER INC."; touch /fake/sans-session /fake/sans-hyprland
  lancer --yes
  vrai '[[ $(code) == 0 ]]' "setup se termine sans erreur"
  vrai 'grep -q "Reste à faire" /fake/sortie.txt && grep -q "graphical-session.target" /fake/sortie.txt' "signale la session sans uwsm"
  vrai 'grep -q "Hyprland ne tourne pas" /fake/sortie.txt' "signale l'absence de Hyprland"
  ;;
esac
if (( ECHECS )); then echo "  --- sortie de setup ---"; sed 's/^/  | /' /fake/sortie.txt; fi
exit $ECHECS
