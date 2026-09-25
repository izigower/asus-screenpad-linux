# asus-screenpad-linux

Faire fonctionner le **ScreenPad** d'un ASUS ZenBook sous Linux : comme second
écran, et comme surface tactile.

Testé sur un **ZenBook 14X OLED UX5400EA** (ScreenPad 2.0, 2160×1080).

## Le problème

Sous Linux, le ScreenPad n'existe pas. Aucun écran supplémentaire n'apparaît,
et les connecteurs DisplayPort restent `disconnected` — rien ne le distingue
d'un port vide.

La raison n'est pas un pilote manquant : **le firmware laisse le panneau
éteint**, et un panneau éteint est indiscernable d'un panneau absent.

Les projets existants (`asus-wmi-screenpad`, `screenpad-tools`,
`asus-screenpad-control`) ne traitent que la **luminosité** d'un ScreenPad déjà
allumé, ou passent par le compositeur sans toucher au firmware. Aucun ne
rallume le panneau.

## La solution

Une méthode ACPI du firmware, que le pilote `asus-wmi` du noyau n'expose pas :

```
\_SB.ATKD.WMNB → méthode DEVS → device id 0x00050031 ← alimentation du ScreenPad
```

Une fois le panneau allumé, tout le reste suit : le connecteur passe
`connected`, l'écran apparaît, le compositeur peut l'utiliser normalement.

## Installation

```sh
sudo ./install.sh
```

Prérequis : `acpi_call-dkms` (Arch), `acpi-call-dkms` (Debian/Ubuntu).

## Utilisation

```sh
screenpad-power on        # allume le panneau
screenpad-power off       # l'éteint
screenpad-power status    # 0x100a0 = allumé, 0x10000 = éteint
screenpad-power brightness 128   # luminosité, de 1 à 255 (sans valeur : la lit)

screenpad-touchmode touch    # le pad devient un écran tactile
screenpad-touchmode pointer  # le pad redevient un trackpad
```

Le service `screenpad.service` allume le panneau au démarrage et à chaque
sortie de veille — le firmware le recoupe systématiquement.

## Configurer l'écran

Le panneau se déclare en **portrait 1080×2160** et doit être pivoté. Sous
Hyprland :

```lua
hl.monitor({ output = "HDMI-A-2", mode = "1080x2160@60",
             position = "0x900", scale = 2, transform = 3 })
```

Le connecteur est **HDMI-A-2**, pas un port DisplayPort — c'est ce qui m'a fait
chercher au mauvais endroit pendant des heures. Vérifie le tien avec
`hyprctl monitors` ou `drm_info` une fois le panneau allumé.

## Tactile

Le pad ne peut pas être souris **et** écran tactile en même temps : c'est le
même compromis que sous Windows, où un geste à trois doigts basculait entre les
deux modes.

`screenpad-touchmode` reclasse le périphérique côté udev. Le firmware refuse la
méthode standard (le champ `Input Mode` du descripteur HID est accepté puis
ignoré), c'est donc la seule voie.

Une fois en mode tactile, il faut encore dire au compositeur à quel écran
correspond la surface :

```lua
hl.device({ name = "gdx1515:00-27c6:01f4-touchpad", output = "HDMI-A-2" })
```

## Pour aller plus loin

Le dossier [`hyprland/`](hyprland/) contient **un ScreenXpert pour Linux** :
écran d'accueil, barre de navigation, Control Center, Number Key, Quick Key,
App Navigator et le pavé noir du mode trackpad, fidèles à l'interface ASUS.
On y trouve aussi un cycle à trois états qui reproduit le `Fn+F6` de Windows.

![Number Key sur le ScreenPad](docs/captures/number-key.png)

[`docs/FINDINGS.md`](docs/FINDINGS.md) détaille la méthode de diagnostic :
comment décompiler le DSDT pour trouver les identifiants WMI, et ce que
révèlent les autres identifiants non documentés.

## Attention

N'écris **pas** dans `/sys/class/backlight/asus_screenpad` (`brightnessctl`,
curseur de ton bureau…) : jusqu'à Linux 7.1 au moins, le pilote `asus-wmi` lit
l'état d'alimentation à l'envers. Chaque réglage de luminosité y envoie l'ordre
d'éteindre le panneau, quelle que soit la valeur. Le connecteur disparaît, et
l'écran avec.

Règle la luminosité par `screenpad-power brightness <1-255>`, qui passe par le
firmware. Le correctif du noyau est accepté (voir
[`docs/FINDINGS.md`](docs/FINDINGS.md#piège-de-la-luminosité--un-bug-du-pilote-pas-du-firmware)).
Si le pad s'est éteint : `screenpad-power on`.

## Licence

GPL-2.0-or-later, comme les projets dont ce travail s'inspire.
