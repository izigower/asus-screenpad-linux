#!/bin/bash
# Banc d'essai de ./setup dans des conteneurs Arch jetables.
# usage : tests/docker/run.sh [scénario…]
set -u
ICI="$(cd "$(dirname "$0")" && pwd)"; REPO="$(cd "$ICI/../.." && pwd)"
CTX=$(mktemp -d); trap 'rm -rf "$CTX"' EXIT
cp -r "$ICI/Dockerfile" "$ICI/stubs" "$CTX/"
# Les vrais fichiers par défaut d'Omarchy, s'ils sont là : config Hyprland et
# plugin de notifications. Sans eux le scénario omarchy est sauté.
mkdir -p "$CTX/omarchy"
if [[ -d /usr/share/omarchy ]]; then
  mkdir -p "$CTX/omarchy/config/hypr" "$CTX/omarchy/shell/plugins"
  cp /usr/share/omarchy/config/hypr/{monitors,input,bindings}.lua "$CTX/omarchy/config/hypr/"
  cp -r /usr/share/omarchy/shell/plugins/notifications "$CTX/omarchy/shell/plugins/"
fi
docker build -q -t screenpad-setup-test "$CTX" >/dev/null || exit 1

scenarios=("$@")
(( ${#scenarios[@]} )) || scenarios=(omarchy mako dunst pas-asus sans-acpi sans-session)
total=0
for s in "${scenarios[@]}"; do
  [[ $s == omarchy && ! -d /usr/share/omarchy ]] && { echo "$s : sauté (Omarchy absent)"; continue; }
  echo "$s"
  docker run --rm -u test -v "$REPO:/repo:ro" screenpad-setup-test bash /repo/tests/docker/scenarios.sh "$s"
  total=$((total + $?))
done
echo; (( total )) && echo "$total échec(s)" || echo "Tout passe."
exit $(( total > 0 ))
