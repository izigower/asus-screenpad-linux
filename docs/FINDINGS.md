# Comment le ScreenPad a été retrouvé

Notes de diagnostic, pour qui voudrait reproduire la démarche sur un autre
modèle ASUS.

## Le piège initial

Le ScreenPad n'apparaît nulle part :

```
card1-DP-1      disconnected   modes=[]
card1-DP-2      disconnected   modes=[]
card1-eDP-1     connected      modes=[2880x1800]
```

J'ai passé des heures à forcer `DP-1` et `DP-2` — écriture dans
`/sys/class/drm/*/status`, EDID fabriqué et injecté via `drm.edid_firmware`.
Le connecteur passait bien `connected`, mais n'exposait que des modes VESA
génériques : personne au bout du fil.

**Deux erreurs à ne pas refaire :**

1. Le panneau n'est pas sur DisplayPort mais sur **HDMI-A-2**.
2. Un connecteur `disconnected` ne prouve rien quand le panneau est éteint.

## La bonne méthode : lire le firmware

```sh
sudo pacman -S acpica
sudo acpidump -b && iasl -d dsdt.dat
```

Chercher dans `dsdt.dsl` la méthode WMI d'ASUS, `\_SB.ATKD.WMNB`. Elle
distribue les appels selon un identifiant de méthode encodé en ASCII :

| Identifiant | ASCII | Rôle |
|---|---|---|
| `0x53545344` | `DSTS` | lecture d'un device |
| `0x53564544` | `DEVS` | écriture |

Puis repérer les device ids de la famille `0x000500xx` :

| Device id | Rôle | Connu du noyau |
|---|---|---|
| `0x00050031` | **alimentation du ScreenPad** | oui, mais mal exposé |
| `0x00050032` | luminosité | oui |
| `0x00050033` | présence (renvoie une constante) | non |
| `0x00050034` | inconnu, bit dans l'EC | non |
| `0x00050035` | inconnu, commandes EC `5`/`6` | non |

## Appeler la méthode

`asus-wmi` n'expose pas d'écriture utilisable sur `0x00050031`, d'où le passage
par `acpi_call` :

```sh
echo '\_SB.ATKD.WMNB 0x0 0x53564544 b3100050001000000' > /proc/acpi/call
```

Le tampon contient le device id puis la valeur, chacun sur 4 octets en
little-endian.

## Le bug du pilote noyau

L'attribut `bl_power` du backlight `asus_screenpad` ne reflète pas l'état réel
et ne permet pas de rallumer le panneau :

| Étape | `bl_power` | état firmware | écran visible |
|---|---|---|---|
| panneau allumé | 0 | `0x100a0` | oui |
| coupé par le firmware | **0** | `0x10000` | non |
| écriture `bl_power` 0/1/0 | 0 | `0x10000` | non |
| appel WMI direct | 0 | `0x100a0` | oui |

Le pilote croit le panneau allumé alors qu'il est éteint, et son interface
n'a aucun effet. Signalable en amont.

## Le tactile

Le descripteur HID déclare deux collections — `Touch Pad` (report 17) et
`Touch Screen` (report 1) — plus un `Input Mode` (report 9, 3 octets).
Écrire `09 02 00` pour demander le mode écran tactile est **accepté sans erreur
mais sans effet** : la collection n'est pas implémentée dans le firmware.

Ce qui marche : le pad émet déjà des coordonnées absolues multitouch
(`ABS_MT_POSITION_X/Y`) sur 128×64 mm, exactement le ratio 2:1 de son écran.
Il suffit de le reclasser côté udev.

## Piège de la luminosité

Alimentation et luminosité sont liées dans le firmware. Écrire une valeur basse
dans `/sys/class/backlight/asus_screenpad/brightness` (testé 0, 1, 30, 50, 100,
120, 150) fait passer `0x00050031` à 0 : le connecteur disparaît. 200 est sûr.
