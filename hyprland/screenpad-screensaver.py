#!/usr/bin/env python3
"""Rallume le ScreenPad si la mise en veille l'a fait couper.

Surtout NE PAS baisser la luminosité pour l'assombrir : sur ce matériel, en
dessous d'environ 200/255 le firmware coupe le panneau, HDMI-A-2 disparaît et le
lanceur se ferme. L'assombrissement visuel est fait par le lanceur lui-même, qui
affiche du noir.

Se branche sur le flux d'événements de Hyprland : l'économiseur d'écran est une
fenêtre de classe org.omarchy.screensaver. On note son adresse à l'ouverture
pour savoir laquelle surveiller à la fermeture.
"""
import os, socket, subprocess, sys, time

CLASSE = "org.omarchy.screensaver"
BL = "/sys/class/backlight/asus_screenpad"
ALIM = "/usr/local/bin/omarchy-screenpad-power"
TOUCHE = "/usr/local/bin/omarchy-screenpad-touchmode"
LANCEUR = os.path.expanduser("~/.local/bin/omarchy-screenpad-dock")


def luminosite():
    try:
        with open(f"{BL}/brightness") as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def regler(valeur):
    try:
        with open(f"{BL}/brightness", "w") as f:
            f.write(str(valeur))
        return True
    except OSError:
        # sysfs n'est pas accessible en écriture directe pour l'utilisateur
        return os.system(f"brightnessctl -d asus_screenpad set {valeur} >/dev/null 2>&1") == 0


def pad_allume():
    """Vrai si le firmware alimente encore le panneau."""
    try:
        sortie = subprocess.run(["sudo", "-n", ALIM, "status"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        return (int(sortie, 16) & 0xFFFF) != 0
    except (subprocess.SubprocessError, ValueError, OSError):
        return True     # dans le doute, ne rien réparer


def mode_entree(valeur=None):
    """Lire ou changer le mode d'entrée du pad (tactile / trackpad)."""
    try:
        cmd = ["sudo", "-n", TOUCHE, valeur or "etat"]
        return subprocess.run(cmd, capture_output=True, text=True,
                              timeout=15).stdout.strip()
    except (subprocess.SubprocessError, OSError):
        return ""


def eteindre_pad():
    """Couper franchement le panneau pendant la veille.

    Un simple voile noir laisse le halo du rétroéclairage LCD ; couper le
    panneau donne un vrai pad éteint. Le mode d'entrée repasse en trackpad pour
    qu'un doigt posé au réveil déplace le curseur au lieu de ne rien faire.
    """
    try:
        mode_entree("trackpad")
        subprocess.run(["systemctl", "--user", "stop", "screenpad-dock"],
                       capture_output=True, timeout=10)
        subprocess.run(["sudo", "-n", ALIM, "off"], capture_output=True, timeout=10)
        # Relancer aussitôt le lanceur : il se construit pendant la veille et
        # attend son écran, prêt à s'afficher dès le rallumage.
        subprocess.run(["systemctl", "--user", "reset-failed", "screenpad-dock"],
                       capture_output=True, timeout=10)
        subprocess.run(["systemd-run", "--user", "--quiet", "--collect",
                        "--unit=screenpad-dock", LANCEUR],
                       capture_output=True, timeout=10)
        print("veille : panneau coupé, lanceur en attente", flush=True)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"extinction impossible : {e}", file=sys.stderr, flush=True)


def reparer_pad():
    """Rallumer le panneau et son lanceur après une mise en veille.

    Omarchy coupe l'affichage de tous les écrans en veille (dpms off), et le
    firmware ASUS en profite pour éteindre le panneau : HDMI-A-2 disparaît et le
    lanceur se ferme de lui-même. Le rallumer n'est pas prévu par
    screenpad.service, qui ne couvre que la sortie de veille système.
    """
    try:
        # Le lanceur attend déjà, construit, depuis la mise en veille ; on le
        # redémarre seulement s'il a fini par abandonner.
        actif = subprocess.run(["systemctl", "--user", "is-active", "--quiet",
                                "screenpad-dock"], capture_output=True).returncode == 0
        if not actif:
            subprocess.run(["systemctl", "--user", "reset-failed", "screenpad-dock"],
                           capture_output=True, timeout=10)
            subprocess.run(["systemd-run", "--user", "--quiet", "--collect",
                            "--unit=screenpad-dock", LANCEUR],
                           capture_output=True, timeout=10)
        subprocess.run(["sudo", "-n", ALIM, "on"], capture_output=True, timeout=10)
        mode_entree("tactile")
        print("panneau, lanceur et tactile rétablis", flush=True)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"rétablissement impossible : {e}", file=sys.stderr, flush=True)


def socket_evenements():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    if not sig:
        sys.exit("HYPRLAND_INSTANCE_SIGNATURE absent")
    return f"{base}/hypr/{sig}/.socket2.sock"


def main():
    chemin = socket_evenements()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.connect(chemin)
    print(f"veilleur ScreenPad connecté à {chemin}", flush=True)

    fenetres = set()      # adresses des fenêtres d'économiseur ouvertes

    reste = ""
    while True:
        data = s.recv(8192)
        if not data:
            break
        reste += data.decode("utf-8", "replace")
        while "\n" in reste:
            ligne, reste = reste.split("\n", 1)
            evenement, _, corps = ligne.partition(">>")

            if evenement == "openwindow":
                # adresse,espace,classe,titre
                champs = corps.split(",", 3)
                if len(champs) >= 3 and champs[2] == CLASSE:
                    if not fenetres and pad_allume():
                        eteindre_pad()
                    fenetres.add(champs[0])

            elif evenement == "closewindow":
                fenetres.discard(corps.strip())
                if not fenetres and not pad_allume():
                    reparer_pad()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError, ConnectionError):
        pass
