# Correctifs amont

Correctifs découverts pendant ce travail, destinés aux projets concernés.
Ils sont ici pour être citables et reproductibles en attendant leur
soumission en amont.

## `0001-elan-retry-on-transient-not-ready-status-for-all-dev.patch`

**Projet :** [libfprint](https://gitlab.freedesktop.org/libfprint/libfprint)
**Fichier :** `libfprint/drivers/elan.c`

Dans `CAPTURE_READ_DATA`, la reprise sur les états transitoires `0x00`
(pas prêt) et `0xaf` (occupé) est réservée en dur au modèle `ELAN_0C58`.
Les 60 autres capteurs de la table reçoivent `FP_DEVICE_ERROR_PROTO`, ce qui
avorte l'enrôlement.

Constaté sur un **Elan `04f3:0c6e`** (ASUS ZenBook 14X OLED UX5400EA), où
l'enrôlement échouait systématiquement :

```
[elan] CAPTURE_NUM_STATES entering state 2
[elan] SSM CAPTURE_NUM_STATES failed in state 2 with error:
       The driver encountered a protocol error with the device.
```

`libfprint-image_device` signalait en outre la transition illégale qui en
découle, `AWAIT_FINGER_ON` → `AWAIT_FINGER_OFF`, répétée toutes les dix
secondes sans jamais atteindre `CAPTURE`.

Avec le correctif, l'enrôlement aboutit. Le comportement du `0x0c58` est
inchangé.

### Appliquer

```sh
git clone https://gitlab.freedesktop.org/libfprint/libfprint.git
cd libfprint
git am < 0001-elan-retry-on-transient-not-ready-status-for-all-dev.patch
meson setup build -Ddoc=false -Dgtk-examples=false \
      -Dudev_rules=disabled -Dudev_hwdb=disabled -Dintrospection=false
ninja -C build
```

### Limite connue

Ce correctif rend l'enrôlement **possible**, il ne rend pas ce capteur
**fiable** : le `04f3:0c6e` est une bande de 149×51 pixels, et les scores de
correspondance mesurés restent très en dessous du seuil (0 à 19 pour un seuil
de 24). Utilisable pour du test, pas pour de l'authentification.
