#!/usr/bin/env python3
"""Écran d'accueil tactile du ScreenPad — un ScreenXpert (ScreenPad 2.0) pour Linux.

Reprend l'interface d'origine d'ASUS :
  - le fond d'écran du bureau et une grille d'applications, 8 par page ;
  - la barre de navigation du bas : TouchPad à gauche, Accueil et App
    Navigator au centre, Control Center à droite ;
  - le Control Center : luminosité, App Navigator, Number Key, Quick Key,
    verrouillage du pad, extinction ;
  - les utilitaires Number Key (pavé numérique) et Quick Key (raccourcis) ;
  - le pavé du mode trackpad : noir, un cadre fin, un trait séparant les
    deux zones de clic et une croix pour revenir à l'écran.

Les applications se règlent dans ~/.config/omarchy/screenpad-dock.json. Les
utilitaires intégrés s'y placent comme des applications, sous les noms
screenxpert:number-key, screenxpert:quick-key et screenxpert:app-navigator.
"""
import json, math, os, shutil, signal, socket, subprocess, sys

# Le wrapper pose LD_PRELOAD=libgtk4-layer-shell.so, indispensable à l'exec pour
# que la bibliothèque passe devant libwayland-client. Une fois le processus
# démarré, elle est chargée : la variable n'a plus d'utilité ici, mais elle
# serait léguée aux applications lancées depuis le dock. Les applications GTK3
# (Electron, Chromium…) y laisseraient la vie : la GTK4 tirée par le préchargement
# détourne gdk_display_manager_get() et avorte le processus. D'où ce retrait.
os.environ.pop("LD_PRELOAD", None)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, Gio, GLib, Gdk

# Layer-shell : le dock est une couche ancrée sur le ScreenPad, pas une fenêtre.
# Il occupe donc tout le panneau (marges et barre comprises), comme un écran
# d'accueil.
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
except (ValueError, ImportError):
    LayerShell = None

gi.require_version("GLibUnix", "2.0")
from gi.repository import GLibUnix

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo

CONFIG = os.path.expanduser("~/.config/omarchy/screenpad-dock.json")
FOND = os.path.expanduser("~/.local/state/omarchy/current/background")
ETAT = os.path.expanduser("~/.local/state/omarchy")
# Le mode courant (tactile / trackpad) doit survivre a un redemarrage du
# lanceur : la mise en veille coupe le panneau, ce qui ferme le lanceur, et
# sans cette trace le pave du mode trackpad etait perdu a chaque reveil.
ETAT_MODE = os.path.join(ETAT, "screenpad-mode")
ETAT_LUMIERE = os.path.join(ETAT, "screenpad-luminosite")
COLONNES = 4
PAR_PAGE = COLONNES * 2   # 4 colonnes x 2 lignes, comme ScreenXpert
BACKLIGHT = "asus_screenpad"
CONNECTEUR = "HDMI-A-2"      # le ScreenPad
ECRAN_PRINCIPAL = "eDP-1"

# Sous ~200/255 le firmware coupe le panneau : l'écran disparaît et le lanceur
# avec. La luminosité matérielle reste donc dans [200, 255] ; en dessous, c'est
# un voile noir qui assombrit.
LUMIERE_MIN_MATERIEL = 200


def premier_executable(*chemins):
    for c in chemins:
        c = os.path.expanduser(c)
        if os.access(c, os.X_OK):
            return c
    return None


# Deux jeux de noms coexistent : celui du dépôt (screenpad-touchmode touch /
# pointer) et celui d'Omarchy (omarchy-screenpad-touchmode tactile / trackpad).
TOUCHMODE = premier_executable("/usr/local/bin/omarchy-screenpad-touchmode",
                               "/usr/local/bin/screenpad-touchmode")
MODES = ({"tactile": "tactile", "trackpad": "trackpad"}
         if TOUCHMODE and "omarchy" in TOUCHMODE
         else {"tactile": "touch", "trackpad": "pointer"})
EXTINCTION = premier_executable("~/.local/bin/omarchy-screenpad-toggle",
                                "~/.local/bin/omarchy-screenpad-cycle",
                                "/usr/local/bin/screenpad-cycle")

INTEGRES = ("screenxpert:number-key", "screenxpert:quick-key",
            "screenxpert:app-navigator")

CANDIDATS = [
    "screenxpert:number-key", "screenxpert:quick-key",
    "org.gnome.Snapshot", "chromium", "org.gnome.Nautilus", "foot",
    "com.github.xournalpp.xournalpp", "obsidian", "Discord", "WhatsApp",
    "Messages", "mpv", "com.obsproject.Studio", "org.kde.kdenlive",
    "btop", "localsend", "com.github.PintaProject.Pinta", "org.gnome.Evince",
    "libreoffice-writer", "libreoffice-calc", "Zoom", "YouTube",
]

# Raccourcis de Quick Key : (libellé, touches). Surchargeables dans la config
# par une liste "quick_keys" de {"label": ..., "keys": "ctrl+shift+z"}.
QUICK_KEYS = [
    ("Couper", "ctrl+x"), ("Copier", "ctrl+c"), ("Coller", "ctrl+v"),
    ("Tout sélectionner", "ctrl+a"), ("Annuler", "ctrl+z"),
    ("Rétablir", "ctrl+shift+z"), ("Rechercher", "ctrl+f"),
    ("Nouvel onglet", "ctrl+t"),
]

MODIFICATEURS = {"ctrl": "ctrl", "control": "ctrl", "shift": "shift",
                 "alt": "alt", "super": "logo", "logo": "logo", "win": "logo"}


def info_app(desktop_id):
    """DesktopAppInfo.new lève TypeError sur un .desktop absent : on ramène à None."""
    try:
        return DesktopAppInfo.new(desktop_id)
    except TypeError:
        return None


def lire_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        pass
    except (json.JSONDecodeError, OSError) as e:
        print(f"config illisible ({e})", file=sys.stderr)
        return {}
    apps = [b if b in INTEGRES else b + ".desktop" for b in CANDIDATS
            if b in INTEGRES or info_app(b + ".desktop")]
    config = {"apps": apps}
    try:
        os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return config


def taper(*args):
    """Envoie des touches à la fenêtre active de l'écran principal.

    Le lanceur ne prend jamais le clavier (KeyboardMode.NONE) : le focus reste
    sur l'application du grand écran, qui reçoit donc ce que tape wtype."""
    if not shutil.which("wtype"):
        print("wtype introuvable : Number Key et Quick Key inactifs", file=sys.stderr)
        return
    subprocess.Popen(["wtype", *args],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def args_raccourci(combinaison):
    """ "ctrl+shift+z" -> arguments wtype : -M ctrl -M shift -k z -m shift -m ctrl"""
    morceaux = [m.strip() for m in combinaison.split("+") if m.strip()]
    mods = [MODIFICATEURS[m.lower()] for m in morceaux[:-1] if m.lower() in MODIFICATEURS]
    args = []
    for m in mods:
        args += ["-M", m]
    args += ["-k", morceaux[-1]]
    for m in reversed(mods):
        args += ["-m", m]
    return args


def hypr(commande):
    try:
        return subprocess.run(["hyprctl", *commande], capture_output=True,
                              text=True, timeout=3).stdout
    except (subprocess.SubprocessError, OSError):
        return ""


# ---------- icônes dessinées (façon ScreenXpert) ----------
# Les icônes de la barre et des utilitaires sont tracées au cairo plutôt que
# prises dans un thème : elles gardent ainsi le trait fin de l'original.

def rectangle_arrondi(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def trace_touchpad(cr, w, h):
    s = min(w, h)
    x0, y0, lw, lh = (w - s * .8) / 2, (h - s * .6) / 2, s * .8, s * .6
    rectangle_arrondi(cr, x0, y0, lw, lh, s * .08)
    cr.stroke()
    cr.move_to(w / 2, y0 + lh)
    cr.line_to(w / 2, y0 + lh - s * .16)
    cr.stroke()


def trace_accueil(cr, w, h):
    cr.arc(w / 2, h / 2, min(w, h) * .26, 0, 2 * math.pi)
    cr.fill()


def trace_navigateur(cr, w, h):
    s = min(w, h)
    x0, y0 = (w - s * .78) / 2, (h - s * .6) / 2
    cr.rectangle(x0, y0, s * .6, s * .6)
    cr.stroke()
    cr.move_to(x0 + s * .78, y0)
    cr.line_to(x0 + s * .78, y0 + s * .6)
    cr.stroke()


def trace_reglages(cr, w, h):
    s = min(w, h)
    x0, x1 = (w - s * .7) / 2, (w + s * .7) / 2
    for i, curseur in enumerate((.35, .7, .25)):
        y = h / 2 + (i - 1) * s * .24
        cr.move_to(x0, y)
        cr.line_to(x1, y)
        cr.stroke()
        cx = x0 + (x1 - x0) * curseur
        cr.move_to(cx, y - s * .08)
        cr.line_to(cx, y + s * .08)
        cr.stroke()


def trace_pave_numerique(cr, w, h):
    s = min(w, h)
    x0, y0 = w / 2 - s * .17, h / 2 - s * .24
    for ligne in range(4):
        for col in range(3):
            cr.rectangle(x0 + col * s * .13, y0 + ligne * s * .1, s * .08, s * .06)
    cr.rectangle(x0, y0 + 4 * s * .1, s * .34, s * .06)
    cr.fill()


def trace_avion(cr, w, h):
    s = min(w, h)
    cx, cy = w / 2, h / 2
    cr.move_to(cx + s * .24, cy - s * .22)
    cr.line_to(cx - s * .26, cy + s * .0)
    cr.line_to(cx - s * .04, cy + s * .06)
    cr.line_to(cx + s * .02, cy + s * .26)
    cr.close_path()
    cr.stroke()
    cr.move_to(cx + s * .24, cy - s * .22)
    cr.line_to(cx - s * .04, cy + s * .06)
    cr.stroke()


def icone_trait(trace, taille=26, epaisseur=1.7):
    """Petite icône blanche au trait, pour la barre de navigation."""
    # Centrée : sans ça un bouton plus grand l'étire et le trait grossit avec.
    zone = Gtk.DrawingArea(content_width=taille, content_height=taille,
                           can_target=False, halign=Gtk.Align.CENTER,
                           valign=Gtk.Align.CENTER)

    def dessiner(_z, cr, w, h):
        cr.set_source_rgba(1, 1, 1, .95)
        cr.set_line_width(epaisseur)
        cr.set_line_cap(1)      # ROUND
        cr.set_line_join(1)
        trace(cr, w, h)
    zone.set_draw_func(dessiner)
    return zone


def icone_tuile(trace, haut, bas, taille=72):
    """Icône d'application ScreenXpert : carré arrondi en dégradé, glyphe blanc."""
    zone = Gtk.DrawingArea(content_width=taille, content_height=taille,
                           can_target=False)

    def dessiner(_z, cr, w, h):
        import cairo
        s = min(w, h) * .9
        x0, y0 = (w - s) / 2, (h - s) / 2
        rectangle_arrondi(cr, x0, y0, s, s, s * .22)
        degrade = cairo.LinearGradient(0, y0, 0, y0 + s)
        degrade.add_color_stop_rgb(0, *haut)
        degrade.add_color_stop_rgb(1, *bas)
        cr.set_source(degrade)
        cr.fill()
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(s * .045)
        cr.set_line_join(1)
        cr.set_line_cap(1)
        cr.translate(x0, y0)
        trace(cr, s, s)
    zone.set_draw_func(dessiner)
    return zone


UTILITAIRES = {
    "screenxpert:number-key": ("Number Key", trace_pave_numerique,
                               (.16, .72, .67), (.05, .42, .45)),
    "screenxpert:quick-key": ("Quick Key", trace_avion,
                              (.33, .56, 1.0), (.12, .28, .78)),
    "screenxpert:app-navigator": ("App Navigator", trace_navigateur,
                                  (.52, .44, .95), (.28, .2, .66)),
}


CSS = b"""
window, .fond { background-color: #0b0d10; }
.voile { background: alpha(#000000, 0.35); }
.tuile {
    background: alpha(#ffffff, 0.10);
    border: 1px solid alpha(#ffffff, 0.14);
    border-radius: 26px; padding: 10px; margin: 8px;
    min-width: 150px; min-height: 124px;
}
.tuile:hover  { background: alpha(#ffffff, 0.20); }
.tuile:active { background: alpha(#ffffff, 0.32); }
.nom { font-size: 13px; color: #eef1f5; margin-top: 6px; text-shadow: 0 1px 3px #000; }

/* Barre de navigation du bas, comme ScreenXpert : fine, sans fond propre. */
.barre { padding-bottom: 4px; background: linear-gradient(to top, alpha(#000000, 0.45), alpha(#000000, 0)); }
.nav {
    background: none; border: none; box-shadow: none; outline: none;
    min-width: 64px; min-height: 40px; padding: 0; margin: 0 4px;
    border-radius: 999px;
}
.nav:hover  { background: alpha(#ffffff, 0.12); }
.nav:active { background: alpha(#ffffff, 0.26); }

/* Control Center */
.centre {
    background: alpha(#14171c, 0.96);
    border: 1px solid alpha(#ffffff, 0.12);
    border-radius: 22px; padding: 16px 22px 12px 22px; margin-bottom: 46px;
}
.centre scale { min-width: 420px; }
.centre scale trough { min-height: 8px; border-radius: 999px; background: alpha(#ffffff, 0.14); }
.centre scale highlight { border-radius: 999px; background: #ffffff; }
.centre scale slider { min-width: 22px; min-height: 22px; background: #ffffff; }
.rond {
    background: alpha(#ffffff, 0.10); border: none; box-shadow: none;
    border-radius: 999px; min-width: 58px; min-height: 58px; padding: 0;
    color: #ffffff;
}
.rond:hover  { background: alpha(#ffffff, 0.20); }
.rond:active { background: alpha(#ffffff, 0.34); }
.rond.danger:hover { background: alpha(#e05252, 0.85); }
.legende { font-size: 11px; color: #aab2bd; margin-top: 4px; }

/* Utilitaires plein ecran (Number Key, Quick Key, App Navigator) */
.utilitaire { background: linear-gradient(110deg, #10141b 0%, #0f2a33 55%, #137a74 100%); }
.fermer-util {
    background: alpha(#ffffff, 0.10); border: none; box-shadow: none;
    border-radius: 0 0 0 14px; min-width: 64px; min-height: 52px; padding: 0;
    color: #ffffff;
}
.fermer-util:hover  { background: alpha(#ffffff, 0.22); }
.fermer-util:active { background: alpha(#ffffff, 0.34); }
.titre-util { font-size: 17px; color: #ffffff; }
.touche {
    background: none; border: none; box-shadow: none; outline: none;
    border-radius: 0; padding: 0; color: #ffffff; font-size: 30px; font-weight: 300;
}
.touche:hover  { background: alpha(#ffffff, 0.08); }
.touche:active { background: alpha(#ffffff, 0.22); }
.touche.verte { color: #4fd06a; font-size: 26px; }
.trait-v { background: alpha(#ffffff, 0.16); min-width: 1px; }
.trait-h { background: alpha(#ffffff, 0.16); min-height: 1px; }
.raccourci {
    background: alpha(#ffffff, 0.12); border: none; box-shadow: none;
    border-radius: 12px; margin: 8px; padding: 8px; min-width: 190px; min-height: 96px;
    color: #ffffff;
}
.raccourci:hover  { background: alpha(#ffffff, 0.20); }
.raccourci:active { background: alpha(#ffffff, 0.32); }
.raccourci-nom { font-size: 21px; }
.raccourci-touches { font-size: 11px; color: alpha(#ffffff, 0.6); margin-top: 6px; }
.fenetre-titre { font-size: 12px; color: #eef1f5; margin-top: 6px; }
.fermer-fenetre {
    background: alpha(#000000, 0.45); border: none; box-shadow: none;
    border-radius: 999px; min-width: 26px; min-height: 26px; padding: 0; color: #ffffff;
}
.fermer-fenetre:hover { background: alpha(#e05252, 0.9); }
.vide { font-size: 15px; color: alpha(#ffffff, 0.6); }

/* Verrouillage : le pad ignore les contacts, sauf un appui long. */
.verrou { background: alpha(#000000, 0.25); }
.cadenas { color: #ffffff; background: alpha(#000000, 0.45); border-radius: 999px;
           min-width: 64px; min-height: 64px; }

/* Assombrissement sous le seuil materiel, et voile de veille : du noir opaque.
   (CSS en ASCII : litteral bytes.) */
.sombre, .noir { background: #000000; }

/* Pave du mode trackpad : tout est dessine au cairo, le bouton est invisible. */
.croix-pave {
    background: none; border: none; box-shadow: none; outline: none;
    min-width: 84px; min-height: 76px; padding: 0; margin: 0;
}
"""


class Dock(Adw.Application):
    def __init__(self):
        # NON_UNIQUE : sans ça GApplication est mono-instance et tout nouveau
        # lancement se contente de réveiller la précédente puis s'arrête, ce qui
        # empêche de relancer le dock après l'avoir fermé.
        super().__init__(application_id="org.omarchy.ScreenpadDock",
                         flags=Gio.ApplicationFlags.NON_UNIQUE)

    # ---------- construction ----------
    # Nombre de tentatives avant d'abandonner : le lanceur peut être démarré
    # juste avant l'allumage du panneau, pour que sa couche apparaisse en même
    # temps que l'écran et masque la barre au lieu de la laisser clignoter.
    ATTENTE_MAX = 90000       # x 40 ms = 1 h : le lanceur patiente pendant
                              # toute la veille, déjà construit, pour s'afficher
                              # sans délai au rallumage du panneau.

    def do_activate(self):
        self._essais = 0
        # SIGUSR1 = clic a 3 doigts en mode souris (screenpad-geste.service) :
        # retour au tactile. Arme en tout premier, l'action par defaut du
        # signal tuerait le lanceur.
        GLibUnix.signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1,
                            self._sur_sigusr1)
        self.hold()           # empêche l'app de quitter tant qu'aucune fenêtre
        # L'interface est bâtie tout de suite, même sans écran : ne reste à
        # attendre que son apparition, pour l'afficher sans délai de rendu.
        self.config = lire_config()
        self._construire()
        self._afficher_quand_pret()

    def _afficher_quand_pret(self):
        if self.win.get_visible():
            return False
        moniteur = self._moniteur(self.win)
        if moniteur is None:
            self._essais += 1
            if self._essais > self.ATTENTE_MAX:
                print(f"ScreenPad ({CONNECTEUR}) absent : rien à afficher",
                      file=sys.stderr)
                self.release()
                self.quit()
                return False
            GLib.timeout_add(40, self._afficher_quand_pret)
            return False
        if LayerShell is not None:
            LayerShell.set_monitor(self.win, moniteur)
        self.win.present()
        if not getattr(self, "_branche", False):
            # hold() n'a été pris qu'une fois au démarrage : ne le relâcher
            # qu'au premier affichage, sinon l'application se termine.
            self._branche = True
            self._restaurer_mode()
            self._surveiller_ecran(self.win)
            self._ecouter_hyprland()
            self.release()
        return False

    def _construire(self):
        self.win = Adw.ApplicationWindow(application=self)
        self.win.set_title("ScreenpadDock")
        if LayerShell is not None:
            self._en_couche(self.win)
        else:
            self.win.fullscreen()

        css = Gtk.CssProvider()
        css.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            self.win.get_display(), css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self._panneaux = []
        pile = Gtk.Overlay()
        pile.set_child(self._fond())
        pile.add_overlay(self._voile())
        pile.add_overlay(self._contenu())
        pile.add_overlay(self._control_center())
        self.numkey = self._panneau(self._number_key())
        self.quickkey = self._panneau(self._quick_key())
        self.navigateur = self._panneau(self._app_navigator())
        self.verrou = self._panneau(self._verrou(), duree=120)
        for p in (self.numkey, self.quickkey, self.navigateur, self.verrou):
            pile.add_overlay(p)
        pile.add_overlay(self._assombrir())
        pile.add_overlay(self._pave())
        pile.add_overlay(self._voile_veille())

        self.win.set_content(pile)
        self._gestes(pile)

    def _en_couche(self, win):
        LayerShell.init_for_window(win)
        LayerShell.set_namespace(win, "screenpad-dock")
        # OVERLAY : au-dessus de la barre Omarchy, qui n'a pas sa place sur un
        # panneau de 540 px déjà occupé par le lanceur. Cloner le plugin de barre
        # pour la filtrer casse son initialisation ; la recouvrir suffit.
        LayerShell.set_layer(win, LayerShell.Layer.OVERLAY)
        for bord in (LayerShell.Edge.TOP, LayerShell.Edge.BOTTOM,
                     LayerShell.Edge.LEFT, LayerShell.Edge.RIGHT):
            LayerShell.set_anchor(win, bord, True)
        # -1 : occuper aussi la zone réservée à la barre, sinon on perd 26 px
        # de haut sur un panneau qui n'en fait que 540.
        LayerShell.set_exclusive_zone(win, -1)
        # Jamais le clavier : Number Key et Quick Key tapent dans la fenêtre
        # du grand écran, qui doit donc garder le focus.
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)

    def _surveiller_ecran(self, win):
        """Se masquer dès que le ScreenPad s'éteint.

        Sans ça la couche est réaffectée à l'écran principal et le lanceur
        s'affiche par-dessus le bureau — quelle que soit la façon dont le pad a
        été éteint (cycle, raccourci, veille, firmware)."""
        display = win.get_display() or Gdk.Display.get_default()
        if display is None:
            return
        moniteurs = display.get_monitors()

        def verifier(*_a):
            if self._moniteur(win) is None and win.get_visible():
                # Se cacher plutôt que quitter : la couche disparaît (sinon elle
                # migrerait sur l'écran principal) mais l'interface reste bâtie,
                # prête à réapparaître dès le rallumage.
                win.set_visible(False)
                self._essais = 0
                GLib.timeout_add(40, self._afficher_quand_pret)

        moniteurs.connect("items-changed", verifier)

    def _moniteur(self, win):
        """Le Gdk.Monitor correspondant au ScreenPad, par nom de connecteur."""
        display = (win.get_display() if win is not None else None) or Gdk.Display.get_default()
        if display is None:
            return None
        moniteurs = display.get_monitors()
        for i in range(moniteurs.get_n_items()):
            m = moniteurs.get_item(i)
            if m.get_connector() == CONNECTEUR:
                return m
        return None

    def _fond(self):
        chemin = os.path.realpath(FOND)
        if os.path.exists(chemin):
            img = Gtk.Picture.new_for_filename(chemin)
            img.set_content_fit(Gtk.ContentFit.COVER)
            return img
        return Gtk.Box(css_classes=["fond"])

    def _voile(self):
        # Assombrit le fond pour que les tuiles restent lisibles sur une photo claire.
        return Gtk.Box(css_classes=["voile"], can_target=False)

    # ---------- écran d'accueil ----------
    def _contenu(self):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # allow_long_swipes enchaînerait plusieurs pages d'un seul geste : sur un
        # panneau de 5,65 pouces le glissement est vite trop ample. Une page par
        # geste, avec une animation un peu plus posée.
        self.carousel = Adw.Carousel(vexpand=True, hexpand=True,
                                     allow_long_swipes=False,
                                     reveal_duration=0, margin_top=14)
        self.carousel.set_scroll_params(Adw.SpringParams.new(1.0, 1.0, 240.0))
        for page in self._pages():
            self.carousel.append(page)
        boite.append(self.carousel)

        points = Adw.CarouselIndicatorDots(carousel=self.carousel,
                                           halign=Gtk.Align.CENTER)
        boite.append(points)
        boite.append(self._barre_navigation())
        return boite

    def _barre_navigation(self):
        """TouchPad | Accueil, App Navigator | Control Center — l'ordre d'ASUS."""
        barre = Gtk.CenterBox(css_classes=["barre"])

        def bouton(trace, aide, action):
            b = Gtk.Button(child=icone_trait(trace), css_classes=["nav"],
                           tooltip_text=aide)
            b.connect("clicked", action)
            return b

        gauche = Gtk.Box(margin_start=10)
        gauche.append(bouton(trace_touchpad, "Repasser en trackpad", self._mode_souris))
        milieu = Gtk.Box(spacing=18)
        milieu.append(bouton(trace_accueil, "Accueil", self._accueil))
        milieu.append(bouton(trace_navigateur, "Applications ouvertes",
                             lambda *_: self._ouvrir(self.navigateur)))
        droite = Gtk.Box(margin_end=10)
        droite.append(bouton(trace_reglages, "Control Center", self._basculer_centre))
        barre.set_start_widget(gauche)
        barre.set_center_widget(milieu)
        barre.set_end_widget(droite)
        return barre

    def _pages(self):
        elements = []
        for d in self.config.get("apps", []):
            if d in UTILITAIRES:
                elements.append(d)
            else:
                info = info_app(d)
                if info:
                    elements.append(info)
        for debut in range(0, len(elements), PAR_PAGE) or [0]:
            grille = Gtk.Grid(row_homogeneous=True, column_homogeneous=True,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            for pos, el in enumerate(elements[debut:debut + PAR_PAGE]):
                tuile = self._tuile_utilitaire(el) if isinstance(el, str) else self._tuile(el)
                grille.attach(tuile, pos % COLONNES, pos // COLONNES, 1, 1)
            # Chaque page doit occuper toute la largeur du carrousel : une grille
            # à sa largeur naturelle laisse dépasser le début de la page suivante.
            page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                           hexpand=True, vexpand=True, halign=Gtk.Align.FILL)
            grille.set_hexpand(True)
            page.append(grille)
            yield page

    def _tuile_nue(self, icone, nom):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        boite.append(icone)
        etiquette = Gtk.Label(label=nom, css_classes=["nom"])
        etiquette.set_ellipsize(3)
        etiquette.set_max_width_chars(11)
        boite.append(etiquette)
        return Gtk.Button(child=boite, css_classes=["tuile"])

    def _tuile(self, info):
        icone = Gtk.Image.new_from_gicon(info.get_icon()) if info.get_icon() \
            else Gtk.Image.new_from_icon_name("application-x-executable")
        icone.set_pixel_size(72)
        bouton = self._tuile_nue(icone, info.get_name())
        bouton.connect("clicked", self._lancer, info)
        return bouton

    def _tuile_utilitaire(self, ident):
        nom, trace, haut, bas = UTILITAIRES[ident]
        bouton = self._tuile_nue(icone_tuile(trace, haut, bas), nom)
        cible = {"screenxpert:number-key": "numkey",
                 "screenxpert:quick-key": "quickkey",
                 "screenxpert:app-navigator": "navigateur"}[ident]
        bouton.connect("clicked", lambda *_: self._ouvrir(getattr(self, cible)))
        return bouton

    def _accueil(self, *_a):
        self._fermer_tout()
        if self.carousel.get_n_pages():
            self.carousel.scroll_to(self.carousel.get_nth_page(0), True)

    # ---------- panneaux plein écran ----------
    def _panneau(self, enfant, duree=160):
        """Un utilitaire plein écran, en fondu.

        can_target suit l'affichage : un revealer masqué mais ciblable avalerait
        les contacts destinés aux tuiles."""
        r = Gtk.Revealer(child=enfant, reveal_child=False, can_target=False,
                         transition_type=Gtk.RevealerTransitionType.CROSSFADE,
                         transition_duration=duree, hexpand=True, vexpand=True)
        self._panneaux.append(r)
        return r

    def _ouvrir(self, panneau):
        self._fermer_tout()
        if panneau is self.navigateur:
            self._remplir_navigateur()
        panneau.set_reveal_child(True)
        panneau.set_can_target(True)

    def _fermer(self, panneau):
        panneau.set_reveal_child(False)
        panneau.set_can_target(False)

    def _fermer_tout(self, *_a):
        for p in self._panneaux:
            self._fermer(p)
        self.centre.set_reveal_child(False)

    def _cadre_utilitaire(self, trace, titre, contenu, panneau_attr):
        """En-tête commun : icône et titre à gauche, croix dans l'angle droit."""
        fond = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                       css_classes=["utilitaire"], hexpand=True, vexpand=True)
        tete = Gtk.Box(spacing=10)
        icone = icone_trait(trace, 24, 1.6)
        icone.set_margin_start(18)
        tete.append(icone)
        tete.append(Gtk.Label(label=titre, css_classes=["titre-util"], hexpand=True,
                              halign=Gtk.Align.START))
        fermer = Gtk.Button(icon_name="window-close-symbolic", css_classes=["fermer-util"],
                            valign=Gtk.Align.START)
        fermer.connect("clicked", lambda *_: self._fermer(getattr(self, panneau_attr)))
        tete.append(fermer)
        fond.append(tete)
        contenu.set_vexpand(True)
        fond.append(contenu)
        return fond

    # ---------- Number Key ----------
    def _number_key(self):
        """Le pavé d'ASUS : 5 colonnes x 4 lignes, traits fins entre les touches,
        effacement sur deux lignes en haut à droite, « enter » en vert."""
        grille = Gtk.Grid(row_homogeneous=True, column_homogeneous=True,
                          hexpand=True, vexpand=True,
                          margin_start=40, margin_end=40, margin_bottom=18)
        touches = [
            ("7", 0, 0), ("8", 1, 0), ("9", 2, 0), ("/", 3, 0),
            ("4", 0, 1), ("5", 1, 1), ("6", 2, 1), ("*", 3, 1),
            ("1", 0, 2), ("2", 1, 2), ("3", 2, 2), ("-", 3, 2), ("%", 4, 2),
            ("0", 0, 3), (".", 1, 3), ("enter", 2, 3), ("+", 3, 3), ("=", 4, 3),
        ]
        affichage = {"-": "−", "*": "×", "/": "÷", ".": "·"}
        for t, col, ligne in touches:
            b = Gtk.Button(label=affichage.get(t, t), css_classes=["touche"])
            if t == "enter":
                b.add_css_class("verte")
                b.connect("clicked", lambda *_: taper("-k", "Return"))
            else:
                b.connect("clicked", lambda _b, t=t: taper(t))
            grille.attach(self._case(b, col, ligne), col, ligne, 1, 1)
        effacer = Gtk.Button(child=Gtk.Image(icon_name="edit-clear-symbolic", pixel_size=30),
                             css_classes=["touche"])
        effacer.connect("clicked", lambda *_: taper("-k", "BackSpace"))
        grille.attach(self._case(effacer, 4, 0, hauteur=2), 4, 0, 1, 2)
        return self._cadre_utilitaire(trace_pave_numerique, "Number Key", grille, "numkey")

    def _case(self, bouton, col, ligne, hauteur=1):
        """Une touche et ses traits : à droite sauf en dernière colonne, en bas
        sauf en dernière ligne — comme la grille fine de l'original."""
        bouton.set_hexpand(True)
        bouton.set_vexpand(True)
        case = Gtk.Overlay()
        case.set_child(bouton)
        if col < 4:
            case.add_overlay(Gtk.Box(css_classes=["trait-v"], halign=Gtk.Align.END,
                                     can_target=False, margin_top=10, margin_bottom=10))
        if ligne + hauteur - 1 < 3:
            case.add_overlay(Gtk.Box(css_classes=["trait-h"], valign=Gtk.Align.END,
                                     can_target=False))
        return case

    # ---------- Quick Key ----------
    def _quick_key(self):
        raccourcis = [(r.get("label", r.get("keys", "?")), r["keys"])
                      for r in self.config.get("quick_keys", []) if r.get("keys")] \
            or QUICK_KEYS
        grille = Gtk.Grid(row_homogeneous=True, column_homogeneous=True,
                          halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER,
                          margin_bottom=20)
        for i, (nom, touches) in enumerate(raccourcis[:8]):
            boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
            n = Gtk.Label(label=nom, css_classes=["raccourci-nom"], wrap=True,
                          justify=Gtk.Justification.CENTER, max_width_chars=12)
            boite.append(n)
            joli = " + ".join(m.capitalize() if len(m) > 1 else m.upper()
                              for m in touches.split("+"))
            boite.append(Gtk.Label(label=joli, css_classes=["raccourci-touches"]))
            b = Gtk.Button(child=boite, css_classes=["raccourci"])
            b.connect("clicked", lambda _b, t=touches: taper(*args_raccourci(t)))
            grille.attach(b, i % 4, i // 4, 1, 1)
        return self._cadre_utilitaire(trace_avion, "Quick Key", grille, "quickkey")

    # ---------- App Navigator ----------
    def _app_navigator(self):
        self.grille_fenetres = Gtk.FlowBox(
            selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
            max_children_per_line=5, min_children_per_line=3,
            valign=Gtk.Align.START, halign=Gtk.Align.CENTER,
            row_spacing=6, column_spacing=6, margin_top=6)
        defile = Gtk.ScrolledWindow(child=self.grille_fenetres,
                                    hscrollbar_policy=Gtk.PolicyType.NEVER,
                                    margin_bottom=14)
        return self._cadre_utilitaire(trace_navigateur, "App Navigator", defile,
                                      "navigateur")

    def _remplir_navigateur(self):
        while (enfant := self.grille_fenetres.get_first_child()) is not None:
            self.grille_fenetres.remove(enfant)
        try:
            clients = json.loads(hypr(["clients", "-j"]) or "[]")
        except json.JSONDecodeError:
            clients = []
        clients = [c for c in clients if c.get("mapped", True)
                   and not c.get("workspace", {}).get("name", "").startswith("special:")]
        if not clients:
            self.grille_fenetres.append(Gtk.Label(label="Aucune application ouverte",
                                                  css_classes=["vide"], margin_top=80))
            return
        for c in sorted(clients, key=lambda c: c.get("focusHistoryID", 0)):
            self.grille_fenetres.append(self._tuile_fenetre(c))

    def _icone_fenetre(self, client):
        """L'icône de l'application qui a ouvert la fenêtre.

        La classe ne suffit pas : Omarchy lance par exemple des foot sous leur
        propre identifiant (org.omarchy.agent), qu'aucun .desktop ne décrit. On
        se rabat alors sur l'exécutable du processus, ici foot."""
        noms = [client.get("class", ""), client.get("initialClass", "")]
        try:
            noms.append(os.path.basename(os.readlink(f"/proc/{client['pid']}/exe")))
        except (OSError, KeyError):
            pass
        noms = [n for n in dict.fromkeys(noms) if n]
        for nom in noms:
            for candidat in (nom, nom.lower()):
                info = info_app(f"{candidat}.desktop")
                if info and info.get_icon():
                    return Gtk.Image.new_from_gicon(info.get_icon())
        for info in Gio.AppInfo.get_all():
            wm = info.get_string("StartupWMClass") if hasattr(info, "get_string") else None
            if wm and wm.lower() in (n.lower() for n in noms) and info.get_icon():
                return Gtk.Image.new_from_gicon(info.get_icon())
        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        for nom in noms:
            if theme.has_icon(nom.lower()):
                return Gtk.Image.new_from_icon_name(nom.lower())
        return Gtk.Image.new_from_icon_name("application-x-executable")

    def _tuile_fenetre(self, client):
        adresse = client["address"]
        icone = self._icone_fenetre(client)
        icone.set_pixel_size(56)
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, valign=Gtk.Align.CENTER)
        boite.append(icone)
        titre = Gtk.Label(label=client.get("title") or client.get("class", ""),
                          css_classes=["fenetre-titre"], max_width_chars=16)
        titre.set_ellipsize(3)
        boite.append(titre)
        tuile = Gtk.Button(child=boite, css_classes=["tuile"])
        tuile.connect("clicked", lambda *_: self._activer_fenetre(adresse))

        fermer = Gtk.Button(icon_name="window-close-symbolic", css_classes=["fermer-fenetre"],
                            halign=Gtk.Align.END, valign=Gtk.Align.START,
                            margin_top=4, margin_end=4)
        fermer.connect("clicked", lambda *_: self._fermer_fenetre(adresse))
        pile = Gtk.Overlay()
        pile.set_child(tuile)
        pile.add_overlay(fermer)
        return pile

    def _activer_fenetre(self, adresse):
        hypr(["dispatch", f'hl.dsp.focus({{ window = "address:{adresse}" }})'])
        self._fermer(self.navigateur)

    def _fermer_fenetre(self, adresse):
        hypr(["dispatch", f'hl.dsp.window.close({{ window = "address:{adresse}" }})'])
        # Laisser à l'application le temps de disparaître avant de relister.
        GLib.timeout_add(350, lambda: (self._remplir_navigateur(), False)[1])

    # ---------- verrouillage ----------
    def _verrou(self):
        """ScreenPad Lock : le pad n'obéit plus au toucher. Un appui long sur le
        cadenas le déverrouille — un simple effleurement ne suffit pas, c'est
        tout l'intérêt."""
        fond = Gtk.Box(css_classes=["verrou"], hexpand=True, vexpand=True)
        cadenas = Gtk.Image(icon_name="changes-prevent-symbolic", pixel_size=28,
                            css_classes=["cadenas"], halign=Gtk.Align.CENTER,
                            valign=Gtk.Align.CENTER, hexpand=True)
        fond.append(cadenas)
        appui = Gtk.GestureLongPress.new()
        appui.set_delay_factor(1.6)
        appui.connect("pressed", lambda *_: self._fermer(self.verrou))
        fond.add_controller(appui)
        return fond

    # ---------- Control Center ----------
    def _control_center(self):
        contenu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12,
                          css_classes=["centre"])
        ligne = Gtk.Box(spacing=12)
        ligne.append(Gtk.Image(icon_name="display-brightness-symbolic", pixel_size=20))
        self.curseur = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 1)
        self.curseur.set_draw_value(False)
        self.curseur.set_hexpand(True)
        self.curseur.set_value(self._lire_luminosite())
        self.curseur.connect("value-changed", self._regler_luminosite)
        ligne.append(self.curseur)
        contenu.append(ligne)

        boutons = Gtk.Box(spacing=22, halign=Gtk.Align.CENTER)

        def rond(enfant, legende, action, danger=False):
            b = Gtk.Button(child=enfant, css_classes=["rond"] + (["danger"] if danger else []),
                           halign=Gtk.Align.CENTER)
            b.connect("clicked", action)
            boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            boite.append(b)
            boite.append(Gtk.Label(label=legende, css_classes=["legende"]))
            boutons.append(boite)

        rond(icone_trait(trace_navigateur, 24), "Applications",
             lambda *_: self._ouvrir(self.navigateur))
        rond(icone_trait(trace_pave_numerique, 26, 1.2), "Number Key",
             lambda *_: self._ouvrir(self.numkey))
        rond(icone_trait(trace_avion, 24), "Quick Key",
             lambda *_: self._ouvrir(self.quickkey))
        rond(icone_trait(trace_touchpad, 24), "TouchPad", self._mode_souris)
        rond(Gtk.Image(icon_name="changes-prevent-symbolic", pixel_size=20),
             "Verrouiller", lambda *_: self._ouvrir(self.verrou))
        rond(Gtk.Image(icon_name="system-shutdown-symbolic", pixel_size=20),
             "Éteindre", self._eteindre_pad, danger=True)
        contenu.append(boutons)

        self.centre = Gtk.Revealer(child=contenu, valign=Gtk.Align.END,
                                   halign=Gtk.Align.CENTER,
                                   transition_type=Gtk.RevealerTransitionType.SLIDE_UP,
                                   transition_duration=200, reveal_child=False)
        return self.centre

    def _basculer_centre(self, *_a):
        ouvert = not self.centre.get_reveal_child()
        self._fermer_tout()
        self.centre.set_reveal_child(ouvert)

    # ---------- luminosité ----------
    def _assombrir(self):
        self.sombre = Gtk.Box(css_classes=["sombre"], can_target=False,
                              hexpand=True, vexpand=True)
        self._appliquer_luminosite(self._lire_luminosite(), materiel=False)
        return self.sombre

    def _lire_luminosite(self):
        try:
            with open(ETAT_LUMIERE) as f:
                return max(10, min(100, int(f.read().strip())))
        except (OSError, ValueError):
            return 100

    def _regler_luminosite(self, echelle):
        valeur = int(echelle.get_value())
        self._appliquer_luminosite(valeur)
        try:
            os.makedirs(ETAT, exist_ok=True)
            with open(ETAT_LUMIERE, "w") as f:
                f.write(str(valeur))
        except OSError:
            pass

    def _appliquer_luminosite(self, valeur, materiel=True):
        """La moitié haute du curseur règle le rétroéclairage entre 200 et 255,
        la moitié basse ajoute un voile noir : le panneau ne descend jamais
        sous le seuil où le firmware le coupe."""
        if valeur >= 55:
            voile = 0.0
            brut = LUMIERE_MIN_MATERIEL + round((255 - LUMIERE_MIN_MATERIEL)
                                                * (valeur - 55) / 45)
        else:
            voile = (55 - valeur) / 45 * 0.8
            brut = LUMIERE_MIN_MATERIEL
        self.sombre.set_opacity(voile)
        if materiel:
            subprocess.Popen(["brightnessctl", "-q", "-d", BACKLIGHT, "set",
                              str(max(LUMIERE_MIN_MATERIEL, brut))],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _eteindre_pad(self, *_a):
        """Fermer le lanceur seul laisserait un panneau allumé et noir, sans
        rien pour le récupérer : le bouton éteint donc l'ensemble.

        Lancé hors du cgroup du lanceur, sinon systemd tuerait le script au
        moment où il arrête ce service — avant qu'il ait rendu le trackpad."""
        if EXTINCTION is None:
            print("aucun script d'extinction trouvé", file=sys.stderr)
            return
        try:
            subprocess.Popen(["systemd-run", "--user", "--quiet", "--collect", EXTINCTION],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"extinction impossible : {e}", file=sys.stderr)

    # ---------- pavé du mode trackpad ----------
    def _pave(self):
        """Le pavé d'ASUS quand le pad redevient un trackpad : fond noir opaque,
        un cadre fin aux coins arrondis, un trait vertical en bas au milieu
        (limite des clics gauche et droit) et, en haut à droite, une croix
        précédée d'un petit séparateur. Aucun texte."""
        dessin = Gtk.DrawingArea(hexpand=True, vexpand=True, can_target=False)
        dessin.set_draw_func(self._dessiner_pave)

        fermer = Gtk.Button(css_classes=["croix-pave"],
                            halign=Gtk.Align.END, valign=Gtk.Align.START)
        fermer.connect("clicked", self._quitter_mode_souris)

        pile = Gtk.Overlay(hexpand=True, vexpand=True)
        pile.set_child(dessin)
        pile.add_overlay(fermer)

        self.reveleur_pave = Gtk.Revealer(
            child=pile, transition_type=Gtk.RevealerTransitionType.CROSSFADE,
            transition_duration=160, reveal_child=False,
            can_target=False, hexpand=True, vexpand=True)
        return self.reveleur_pave

    @staticmethod
    def _dessiner_pave(_zone, cr, w, h):
        # Proportions relevées sur la capture d'ASUS (2160 x 1080).
        cr.set_source_rgb(0, 0, 0)
        cr.paint()
        gris = (.42, .42, .42)
        marge, rayon = w * .0095, w * .012
        cr.set_line_width(1.2)
        cr.set_source_rgb(*gris)
        rectangle_arrondi(cr, marge, marge, w - 2 * marge, h - 2 * marge, rayon)
        cr.stroke()
        # Trait du bas, au milieu : de la bordure jusqu'à 13 % de la hauteur.
        cr.move_to(round(w / 2) + .5, h - marge)
        cr.line_to(round(w / 2) + .5, h * .87)
        cr.stroke()
        # Séparateur à gauche de la croix.
        x = round(w * .9225) + .5
        cr.move_to(x, h * .052)
        cr.line_to(x, h * .105)
        cr.stroke()
        # Croix fine, blanche.
        cx, cy, d = w * .961, h * .078, h * .022
        cr.set_source_rgb(1, 1, 1)
        cr.set_line_width(1.4)
        cr.move_to(cx - d, cy - d)
        cr.line_to(cx + d, cy + d)
        cr.move_to(cx + d, cy - d)
        cr.line_to(cx - d, cy + d)
        cr.stroke()

    def _voile_veille(self):
        self.reveleur_noir = Gtk.Revealer(
            child=Gtk.Box(css_classes=["noir"], hexpand=True, vexpand=True),
            transition_type=Gtk.RevealerTransitionType.CROSSFADE,
            transition_duration=400, reveal_child=False,
            can_target=False, hexpand=True, vexpand=True)
        return self.reveleur_noir

    def _veille(self, actif):
        self.reveleur_noir.set_reveal_child(actif)

    def _ecouter_hyprland(self):
        """Suivre l'ouverture et la fermeture de l'économiseur d'écran.

        closewindow ne donne que l'adresse de la fenêtre : on retient donc
        celles de classe org.omarchy.screensaver à leur ouverture.
        """
        sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
        base = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        if not sig:
            return
        try:
            self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self._sock.connect(f"{base}/hypr/{sig}/.socket2.sock")
        except OSError as e:
            print(f"événements Hyprland indisponibles : {e}", file=sys.stderr)
            return
        self._ecran_veille = set()
        self._reste = ""
        canal = GLib.IOChannel.unix_new(self._sock.fileno())
        canal.set_encoding(None)
        canal.set_buffered(False)
        GLib.io_add_watch(canal, GLib.PRIORITY_DEFAULT, GLib.IOCondition.IN,
                          self._sur_evenement_hypr)

    def _sur_evenement_hypr(self, canal, _condition):
        try:
            data = self._sock.recv(8192)
        except OSError:
            return False
        if not data:
            return False
        self._reste += data.decode("utf-8", "replace")
        while "\n" in self._reste:
            ligne, self._reste = self._reste.split("\n", 1)
            nom, _, corps = ligne.partition(">>")
            if nom == "openwindow":
                champs = corps.split(",", 3)
                if len(champs) >= 3 and champs[2] == "org.omarchy.screensaver":
                    self._ecran_veille.add(champs[0])
                    self._veille(True)
            elif nom == "closewindow":
                self._ecran_veille.discard(corps.strip())
                if not self._ecran_veille:
                    self._veille(False)
        return True

    def _mode_souris(self, *_a):
        if self.reveleur_pave.get_reveal_child():
            return
        self._fermer_tout()
        self.reveleur_pave.set_reveal_child(True)
        # Sans can_target le pavé masqué avalerait les contacts des tuiles.
        self.reveleur_pave.set_can_target(True)
        self._touchmode("trackpad")
        self._ecrire_mode("trackpad")

    def _quitter_mode_souris(self, *_a):
        self.reveleur_pave.set_reveal_child(False)
        self.reveleur_pave.set_can_target(False)
        self._touchmode("tactile")
        self._ecrire_mode("tactile")

    def _sur_sigusr1(self):
        if hasattr(self, "reveleur_pave"):
            self._quitter_mode_souris()
        return GLib.SOURCE_CONTINUE

    def _lire_mode(self):
        try:
            with open(ETAT_MODE) as f:
                return f.read().strip()
        except OSError:
            return "tactile"

    def _ecrire_mode(self, mode):
        try:
            os.makedirs(ETAT, exist_ok=True)
            with open(ETAT_MODE, "w") as f:
                f.write(mode)
        except OSError as e:
            print(f"etat non enregistre : {e}", file=sys.stderr)

    def _restaurer_mode(self):
        """Retrouver le mode d'avant la veille, au premier affichage.

        Appele apres present() : le revealer doit exister et la fenetre etre
        realisee, sinon la transition ne part pas."""
        if self._lire_mode() == "trackpad":
            self._mode_souris()
        else:
            # Imposer le tactile plutot que de ne rien faire : sans cela le pad
            # resterait dans le mode ou l'a laisse le lanceur precedent.
            self._quitter_mode_souris()

    def _touchmode(self, mode):
        if TOUCHMODE is None:
            return
        try:
            subprocess.Popen(["sudo", "-n", TOUCHMODE, MODES[mode]],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"bascule {mode} impossible : {e}", file=sys.stderr)

    # ---------- gestes ----------
    def _gestes(self, cible):
        glissement = Gtk.GestureSwipe.new()
        glissement.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        glissement.connect("swipe", self._sur_glissement)
        cible.add_controller(glissement)

        # Trois doigts = retour au trackpad. En phase BUBBLE le contrôleur ne
        # voit les contacts qu'après les tuiles : il observe sans jamais les
        # priver du toucher, contrairement à CAPTURE.
        self._contacts = set()
        brut = Gtk.EventControllerLegacy.new()
        brut.set_propagation_phase(Gtk.PropagationPhase.BUBBLE)
        brut.connect("event", self._sur_evenement)
        cible.add_controller(brut)

    def _sur_evenement(self, _c, event):
        # GTK appelle aussi ce gestionnaire sans événement : ignorer, sinon
        # chaque contact remplit le journal d'AttributeError.
        if event is None:
            return False
        typ = event.get_event_type()
        seq = event.get_event_sequence()
        if typ == Gdk.EventType.TOUCH_BEGIN:
            self._contacts.add(seq)
            if len(self._contacts) >= 3 and not self.verrou.get_reveal_child():
                self._contacts.clear()
                self._mode_souris()
        elif typ in (Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
            self._contacts.discard(seq)
        return False

    def _sur_glissement(self, _g, vx, vy):
        # Vertical franc seulement : l'horizontal appartient au carrousel.
        # Vers le haut ouvre le Control Center, vers le bas le referme.
        if abs(vy) < 300 or abs(vy) < abs(vx):
            return
        if any(p.get_reveal_child() for p in self._panneaux):
            return
        self.centre.set_reveal_child(vy < 0)

    def _lancer(self, _b, info):
        # Le pad est un lanceur, pas un espace de travail : on ramène le focus
        # sur l'écran principal pour que la fenêtre s'y ouvre.
        hypr(["dispatch", f'hl.dsp.focus({{ monitor = "{ECRAN_PRINCIPAL}" }})'])
        # Lancée par info.launch(), l'application resterait dans le cgroup du
        # lanceur : l'arrêter (croix, redémarrage) la tuerait avec lui.
        # uwsm-app lui donne sa propre unité systemd.
        ident = info.get_id()
        if ident and shutil.which("uwsm-app"):
            try:
                subprocess.Popen(["uwsm-app", "--", ident],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                pass
        try:
            info.launch(None, None)
        except GLib.Error as e:
            print(f"lancement impossible : {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(Dock().run(None))
