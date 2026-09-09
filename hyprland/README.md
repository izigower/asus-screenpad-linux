# Outils Hyprland

Optionnels : le cœur du dépôt (`bin/`) suffit à faire apparaître le ScreenPad
comme écran. Ces outils-ci reproduisent l'expérience ScreenXpert de Windows.

| Fichier | Rôle |
|---|---|
| `screenpad-dock.py` | écran d'accueil tactile : grille d'applications, pages, panneau de luminosité, geste à trois doigts pour rendre le trackpad |
| `screenpad-cycle` | cycle à trois états, équivalent du `Fn+F6` : trackpad seul → écran tactile → tout éteint |
| `screenpad-screensaver.py` | éteint le panneau pendant l'économiseur d'écran et le rallume au réveil |

Le lanceur exige `gtk4-layer-shell`, chargé via `LD_PRELOAD` — la bibliothèque
doit précéder libwayland, ce qu'un import Python ne permet pas.

Ces scripts portent encore des chemins et des noms propres à Omarchy ; ils sont
fournis comme point de départ, pas comme paquet fini.
