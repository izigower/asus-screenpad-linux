#!/usr/bin/env python3
"""Écran d'accueil tactile du ScreenPad — équivalent maison de ScreenXpert.

Reprend les codes de l'interface d'origine : le fond d'écran du bureau, des
tuiles d'applications semi-transparentes par-dessus, 8 par page, des points de
pagination, un glissement horizontal pour changer de page, un panneau de
réglages qu'on tire depuis le haut, et une croix pour fermer.

Les applications se règlent dans ~/.config/omarchy/screenpad-dock.json.
"""
import json, os, socket, subprocess, sys

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

# Layer-shell : le dock est une couche d'arrière-plan ancrée sur le ScreenPad,
# pas une fenêtre. Il occupe donc tout le panneau (marges et barre comprises) et
# les applications lancées s'affichent par-dessus, comme un écran d'accueil.
try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell as LayerShell
except (ValueError, ImportError):
    LayerShell = None

try:
    gi.require_version("GioUnix", "2.0")
    from gi.repository import GioUnix
    DesktopAppInfo = GioUnix.DesktopAppInfo
except (ValueError, ImportError):
    DesktopAppInfo = Gio.DesktopAppInfo

CONFIG = os.path.expanduser("~/.config/omarchy/screenpad-dock.json")
FOND = os.path.expanduser("~/.local/state/omarchy/current/background")
COLONNES = 4
PAR_PAGE = COLONNES * 2   # 4 colonnes x 2 lignes, comme ScreenXpert
BACKLIGHT = "asus_screenpad"
CONNECTEUR = "HDMI-A-2"      # le ScreenPad
ECRAN_PRINCIPAL = "eDP-1"
TOUCHMODE = "/usr/local/bin/omarchy-screenpad-touchmode"

CANDIDATS = [
    "org.gnome.Snapshot", "chromium", "org.gnome.Nautilus", "foot",
    "com.github.xournalpp.xournalpp", "obsidian", "Discord", "WhatsApp",
    "Messages", "mpv", "com.obsproject.Studio", "org.kde.kdenlive",
    "btop", "localsend", "com.github.PintaProject.Pinta", "org.gnome.Evince",
    "libreoffice-writer", "libreoffice-calc", "Zoom", "YouTube",
]


def info_app(desktop_id):
    """DesktopAppInfo.new lève TypeError sur un .desktop absent : on ramène à None."""
    try:
        return DesktopAppInfo.new(desktop_id)
    except TypeError:
        return None


def charger_config():
    if os.path.exists(CONFIG):
        try:
            with open(CONFIG, encoding="utf-8") as f:
                return json.load(f).get("apps", [])
        except (json.JSONDecodeError, OSError) as e:
            print(f"config illisible ({e})", file=sys.stderr)
    apps = [b + ".desktop" for b in CANDIDATS if info_app(b + ".desktop")]
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump({"apps": apps}, f, indent=2, ensure_ascii=False)
    except OSError:
        pass
    return apps


CSS = b"""
window, .fond { background-color: #0b0d10; }
.voile { background: alpha(#000000, 0.35); }
.tuile {
    background: alpha(#ffffff, 0.10);
    border: 1px solid alpha(#ffffff, 0.14);
    border-radius: 26px; padding: 10px; margin: 10px;
    min-width: 150px; min-height: 132px;
}
.tuile:hover  { background: alpha(#ffffff, 0.20); }
.tuile:active { background: alpha(#ffffff, 0.32); }
.nom { font-size: 13px; color: #eef1f5; margin-top: 6px; text-shadow: 0 1px 3px #000; }
.croix {
    background: alpha(#000000, 0.35); border-radius: 999px;
    min-width: 34px; min-height: 34px; padding: 0; margin: 8px;
    color: #ffffff; border: 1px solid alpha(#ffffff, 0.18);
}
.croix:hover { background: alpha(#e05252, 0.85); }
.reglages {
    background: alpha(#12151a, 0.94);
    border-bottom-left-radius: 20px; border-bottom-right-radius: 20px;
    border: 1px solid alpha(#ffffff, 0.12); padding: 14px 20px;
}
.titre-reglages { font-size: 13px; color: #aab2bd; }
.poignee { background: alpha(#ffffff, 0.25); border-radius: 3px; min-height: 5px; min-width: 60px; margin: 6px; }
/* Le voile du mode souris couvre le panneau entier : ni marge, ni bordure,
   ni coins arrondis, sinon le lanceur reste visible sur les bords. */
.pave { background: alpha(#000000, 0.66); }
/* Voile de veille : du noir opaque, pour que le pad passe pour un trackpad
   ordinaire. Baisser la luminosite ne marche pas -- sous ~200/255 le firmware
   coupe le panneau et l'ecran disparait. (CSS en ASCII : litteral bytes.) */
.noir { background: #000000; }
.croix-pave {
    background: none; border: none; box-shadow: none; outline: none;
    min-width: 42px; min-height: 42px; padding: 0;
    margin-top: 14px; margin-right: 12px;
    color: #ffffff;
}
.croix-pave:hover  { background: alpha(#ffffff, 0.16); border-radius: 999px; }
.croix-pave:active { background: alpha(#ffffff, 0.28); border-radius: 999px; }
/* Zone de clic large et invisible : au doigt, une pastille de 34 px se rate.
   Le bouton reste transparent, la pastille visible est son enfant. */
.zone-souris {
    background: none; border: none; box-shadow: none; outline: none;
    min-width: 78px; min-height: 78px; padding: 0; margin: 0;
}
.bouton-souris {
    background: alpha(#000000, 0.32); border-radius: 999px;
    border: 1px solid alpha(#ffffff, 0.16);
    min-width: 34px; min-height: 34px; padding: 0;
    color: #ffffff; font-size: 17px;
}
.zone-souris:hover  .bouton-souris { background: alpha(#ffffff, 0.26); }
.zone-souris:active .bouton-souris { background: alpha(#ffffff, 0.40); }
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
        self.hold()           # empêche l'app de quitter tant qu'aucune fenêtre
        # L'interface est bâtie tout de suite, même sans écran : ne reste à
        # attendre que son apparition, pour l'afficher sans délai de rendu.
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

        pile = Gtk.Overlay()
        pile.set_child(self._fond())
        pile.add_overlay(self._voile())
        pile.add_overlay(self._contenu())
        pile.add_overlay(self._panneau_reglages())
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
        LayerShell.set_keyboard_mode(win, LayerShell.KeyboardMode.NONE)



    def _surveiller_ecran(self, win):
        """Quitter dès que le ScreenPad s'éteint.

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

    def _contenu(self):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # La barre Omarchy occupe les 26 premiers pixels : sans marge les
        # boutons passent dessous et deviennent intouchables.
        haut = Gtk.Box(halign=Gtk.Align.END, valign=Gtk.Align.START, spacing=0,
                       margin_top=2, margin_end=0)
        pastille = Gtk.Label(label="\U000F037D", css_classes=["bouton-souris"],
                             halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        self.bouton_souris = Gtk.Button(child=pastille, css_classes=["zone-souris"])
        self.bouton_souris.set_tooltip_text("Repasser en trackpad")
        self.bouton_souris.connect("clicked", self._mode_souris)
        haut.append(self.bouton_souris)
        boite.append(haut)

        # allow_long_swipes enchaînerait plusieurs pages d'un seul geste : sur un
        # panneau de 5,65 pouces le glissement est vite trop ample. Une page par
        # geste, avec une animation un peu plus posée.
        self.carousel = Adw.Carousel(vexpand=True, hexpand=True,
                                     allow_long_swipes=False,
                                     reveal_duration=0)
        self.carousel.set_scroll_params(Adw.SpringParams.new(1.0, 1.0, 240.0))
        for page in self._pages():
            self.carousel.append(page)
        boite.append(self.carousel)

        points = Adw.CarouselIndicatorDots(carousel=self.carousel,
                                           halign=Gtk.Align.CENTER, margin_bottom=6)
        boite.append(points)
        return boite

    def _pages(self):
        apps = [i for i in (info_app(d) for d in charger_config()) if i]
        for debut in range(0, len(apps), PAR_PAGE) or [0]:
            grille = Gtk.Grid(row_homogeneous=True, column_homogeneous=True,
                              halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
            for pos, info in enumerate(apps[debut:debut + PAR_PAGE]):
                grille.attach(self._tuile(info), pos % COLONNES, pos // COLONNES, 1, 1)
            # Chaque page doit occuper toute la largeur du carrousel : une grille
            # à sa largeur naturelle laisse dépasser le début de la page suivante.
            page = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL,
                           hexpand=True, vexpand=True, halign=Gtk.Align.FILL)
            grille.set_hexpand(True)
            page.append(grille)
            yield page

    def _tuile(self, info):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        icone = Gtk.Image.new_from_gicon(info.get_icon()) if info.get_icon() \
            else Gtk.Image.new_from_icon_name("application-x-executable")
        icone.set_pixel_size(72)
        boite.append(icone)
        nom = Gtk.Label(label=info.get_name(), css_classes=["nom"])
        nom.set_ellipsize(3)
        nom.set_max_width_chars(11)
        boite.append(nom)

        bouton = Gtk.Button(child=boite, css_classes=["tuile"])
        bouton.connect("clicked", self._lancer, info)
        return bouton

    # ---------- panneau de réglages ----------
    def _panneau_reglages(self):
        contenu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8,
                          css_classes=["reglages"])
        contenu.append(Gtk.Label(label="Luminosité du ScreenPad",
                                 halign=Gtk.Align.START, css_classes=["titre-reglages"]))

        self.curseur = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 5, 100, 1)
        self.curseur.set_value(self._luminosite())
        self.curseur.set_draw_value(False)
        self.curseur.connect("value-changed", self._regler_luminosite)
        contenu.append(self.curseur)

        ligne = Gtk.Box(spacing=8, halign=Gtk.Align.CENTER)
        eteindre = Gtk.Button(label="Éteindre le ScreenPad", css_classes=["croix"])
        eteindre.connect("clicked", self._eteindre)
        ligne.append(eteindre)
        contenu.append(ligne)
        contenu.append(Gtk.Box(css_classes=["poignee"], halign=Gtk.Align.CENTER))

        self.reveleur = Gtk.Revealer(child=contenu, valign=Gtk.Align.START,
                                     halign=Gtk.Align.CENTER,
                                     transition_type=Gtk.RevealerTransitionType.SLIDE_DOWN,
                                     transition_duration=200, reveal_child=False)
        return self.reveleur

    def _luminosite(self):
        try:
            out = subprocess.run(["brightnessctl", "-d", BACKLIGHT, "-m"],
                                 capture_output=True, text=True, timeout=3).stdout
            return int(out.split(",")[3].rstrip("%"))
        except (subprocess.SubprocessError, IndexError, ValueError, OSError):
            return 70

    def _regler_luminosite(self, echelle):
        subprocess.Popen(["brightnessctl", "-d", BACKLIGHT,
                          "set", f"{int(echelle.get_value())}%"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _eteindre(self, _b):
        # Le cycle gère l'extinction du panneau et ferme ce dock au passage.
        subprocess.Popen(["omarchy-screenpad-cycle"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # ---------- pavé translucide (mode souris) ----------
    def _pave(self):
        boite = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2,
                        halign=Gtk.Align.CENTER, valign=Gtk.Align.CENTER)
        boite.append(Gtk.Label(label="\U000F0A1F  Mode souris", css_classes=["pave-titre"]))
        boite.append(Gtk.Label(label="Le pad redevient un trackpad",
                               css_classes=["pave-info"]))
        boite.append(Gtk.Label(label="Touche la croix pour revenir au tactile",
                               css_classes=["pave-info"]))

        cadre = Gtk.Box(css_classes=["pave"], hexpand=True, vexpand=True)
        cadre.append(boite)

        fermer = Gtk.Button(icon_name="window-close-symbolic",
                            css_classes=["croix-pave"],
                            halign=Gtk.Align.END, valign=Gtk.Align.START)
        fermer.connect("clicked", self._quitter_mode_souris)

        pile = Gtk.Overlay()
        pile.set_child(cadre)
        pile.add_overlay(fermer)

        self.reveleur_pave = Gtk.Revealer(
            child=pile, transition_type=Gtk.RevealerTransitionType.CROSSFADE,
            transition_duration=180, reveal_child=False)
        return self.reveleur_pave

    def _mode_souris(self):
        """Trois doigts : le pad repasse en trackpad, avec un pavé translucide."""
        if self.reveleur_pave.get_reveal_child():
            return
        self.reveleur_pave.set_reveal_child(True)
        self._touchmode("trackpad")

    def _quitter_mode_souris(self, *_a):
        self.reveleur_pave.set_reveal_child(False)
        self._touchmode("tactile")

    def _eteindre_pad(self, *_a):
        """Fermer le lanceur seul laisserait un panneau allumé et noir, sans
        rien pour le récupérer : la croix éteint donc l'ensemble.

        Lancé hors du cgroup du lanceur, sinon systemd tuerait le script au
        moment où il arrête ce service — avant qu'il ait rendu le trackpad."""
        try:
            subprocess.Popen(
                ["systemd-run", "--user", "--quiet", "--collect",
                 os.path.expanduser("~/.local/bin/omarchy-screenpad-toggle")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"extinction impossible : {e}", file=sys.stderr)

    def _touchmode(self, mode):
        try:
            subprocess.Popen(["sudo", "-n", TOUCHMODE, mode],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"bascule {mode} impossible : {e}", file=sys.stderr)

    # ---------- mode souris ----------
    def _pave(self):
        """Pavé translucide affiché quand le pad redevient un trackpad."""
        # Volontairement vide : une surface sombre translucide suffit à dire que
        # le pad est redevenu un trackpad. Du texte par-dessus les icônes les
        # rendrait illisibles sans rien apprendre de plus.
        cadre = Gtk.Box(css_classes=["pave"], hexpand=True, vexpand=True)

        fermer = Gtk.Button(icon_name="window-close-symbolic",
                            css_classes=["croix-pave"],
                            halign=Gtk.Align.END, valign=Gtk.Align.START)
        fermer.connect("clicked", self._quitter_mode_souris)

        pile = Gtk.Overlay(hexpand=True, vexpand=True)
        pile.set_child(cadre)
        pile.add_overlay(fermer)

        self.reveleur_pave = Gtk.Revealer(
            child=pile, transition_type=Gtk.RevealerTransitionType.CROSSFADE,
            transition_duration=160, reveal_child=False,
            can_target=False, hexpand=True, vexpand=True)
        return self.reveleur_pave

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
        self.reveleur_pave.set_reveal_child(True)
        # Sans can_target le pavé masqué avalerait les contacts des tuiles.
        self.reveleur_pave.set_can_target(True)
        self.bouton_souris.set_visible(False)
        self._touchmode("trackpad")

    def _quitter_mode_souris(self, *_a):
        self.reveleur_pave.set_reveal_child(False)
        self.reveleur_pave.set_can_target(False)
        self.bouton_souris.set_visible(True)
        self._touchmode("tactile")

    def _eteindre_pad(self, *_a):
        """Fermer le lanceur seul laisserait un panneau allumé et noir, sans
        rien pour le récupérer : la croix éteint donc l'ensemble.

        Lancé hors du cgroup du lanceur, sinon systemd tuerait le script au
        moment où il arrête ce service — avant qu'il ait rendu le trackpad."""
        try:
            subprocess.Popen(
                ["systemd-run", "--user", "--quiet", "--collect",
                 os.path.expanduser("~/.local/bin/omarchy-screenpad-toggle")],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            print(f"extinction impossible : {e}", file=sys.stderr)

    def _touchmode(self, mode):
        try:
            subprocess.Popen(["sudo", "-n", TOUCHMODE, mode],
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
            if len(self._contacts) >= 3:
                self._contacts.clear()
                self._mode_souris()
        elif typ in (Gdk.EventType.TOUCH_END, Gdk.EventType.TOUCH_CANCEL):
            self._contacts.discard(seq)
        return False


    def _sur_glissement(self, _g, vx, vy):
        # Vertical franc seulement : l'horizontal appartient au carrousel.
        if abs(vy) < 300 or abs(vy) < abs(vx):
            return
        self.reveleur.set_reveal_child(vy > 0)
        if vy > 0:
            self.curseur.set_value(self._luminosite())

    def _lancer(self, _b, info):
        # Le pad est un lanceur, pas un espace de travail : on ramène le focus
        # sur l'écran principal pour que la fenêtre s'y ouvre.
        try:
            subprocess.run(["hyprctl", "dispatch",
                            f'hl.dsp.focus({{ monitor = "{ECRAN_PRINCIPAL}" }})'],
                           capture_output=True, timeout=3)
        except (subprocess.SubprocessError, OSError):
            pass
        try:
            info.launch(None, None)
        except GLib.Error as e:
            print(f"lancement impossible : {e}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(Dock().run(None))
