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

## Piège de la luminosité : un bug du pilote, pas du firmware

Écrire dans `/sys/class/backlight/asus_screenpad/brightness` éteint le
panneau : `0x00050031` passe à 0 et le connecteur disparaît. On a d'abord cru
à une limite du firmware (« les valeurs basses éteignent, 200 est sûr »). En
réalité, une écriture à 249 coupe le panneau aussi, et le firmware accepte
toutes les valeurs de 1 à 255 quand on l'appelle directement.

Le fautif est `update_screenpad_bl_status()` dans `asus-wmi` (Linux 7.1) :

```c
if (bd->props.power) {            /* pris pour « allumé »…               */
        /* allume puis règle la luminosité */
}
if (!bd->props.power) {           /* …or 0 vaut BACKLIGHT_POWER_ON       */
        asus_wmi_set_devstate(ASUS_WMI_DEVID_SCREENPAD_POWER, 0, NULL);
}
```

`bl_power` vaut `0` (`BACKLIGHT_POWER_ON`) quand le pad est allumé, et le test
est inversé. Chaque écriture de luminosité envoie donc l'ordre d'extinction.
Signalé sur `platform-driver-x86` en septembre 2026 : la série de Denis Benato
*« fix screenpad backlight regression »* corrige ce test. Ilpo Järvinen l'a
appliquée le 18/09/2026 (commits 159e956fd4f9, 341b4769f5cf, 99215e618ff2,
854be60ed0e9). Elle n'est pas encore dans les noyaux distribués.

En attendant, on règle la luminosité par le firmware, comme l'alimentation :
DEVS sur `0x00050032`, valeur 1 à 255. `screenpad-power brightness <1-255>`
le fait, et `screenpad-power brightness` relit la valeur (octet de poids faible
de DSTS `0x00050032`, `0xff` étant codé en dur comme maximum).

Relevé sur UX5400EA : 128, 64, 16 et 1 appliqués et relus à l'identique, pad
toujours allumé.
