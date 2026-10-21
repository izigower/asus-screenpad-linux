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
import json, os, socket, subprocess, sys, threading, time

CLASSE = "org.omarchy.screensaver"
ALIM = "/usr/local/bin/screenpad-power"
TOUCHE = "/usr/local/bin/screenpad-touchmode"
LANCEUR = os.path.expanduser("~/.local/bin/screenpad-dock")
ETAT_MODE = os.path.expanduser("~/.local/state/omarchy/screenpad-mode")


def mode_sauvegarde():
    """Le mode choisi avant la veille, écrit par le lanceur."""
    try:
        with open(ETAT_MODE) as f:
            valeur = f.read().strip()
        return valeur if valeur in ("tactile", "trackpad") else "tactile"
    except OSError:
        return "tactile"


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
        # Ne pas imposer le tactile : le lanceur relit son mode d'avant la veille
        # et le rétablit lui-même. On ne s'en mêle que s'il n'a pas pu le faire,
        # sinon un pad laissé en pavé translucide repasserait en tactile au
        # réveil, ce qui était exactement le défaut.
        mode_entree(mode_sauvegarde())
        print("panneau, lanceur et mode rétablis", flush=True)
    except (subprocess.SubprocessError, OSError) as e:
        print(f"rétablissement impossible : {e}", file=sys.stderr, flush=True)


def _socket_commandes():
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    base = os.environ.get("XDG_RUNTIME_DIR", "/run/user/%d" % os.getuid())
    return f"{base}/hypr/{sig}/.socket.sock"


def session_verrouillee():
    """Vrai quand l'ecran de verrouillage couvre les moniteurs.

    On interroge la socket de commandes de Hyprland en direct plutot que
    d'appeler omarchy-hyprland-session-locked : un sous-processus toutes les
    deux secondes couterait bien plus cher qu'un aller-retour sur une socket.
    """
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(2)
        s.connect(_socket_commandes())
        s.sendall(b"j/monitors")
        morceaux = []
        while True:
            bloc = s.recv(65536)
            if not bloc:
                break
            morceaux.append(bloc)
        s.close()
        moniteurs = json.loads(b"".join(morceaux).decode("utf-8", "replace"))
        return any("LOCK" in (m.get("solitaryBlockedBy") or []) for m in moniteurs)
    except (OSError, ValueError):
        return False


def surveiller_verrouillage(fenetres):
    """Eteint le pad pendant le verrouillage, le rend au deverrouillage.

    Necessaire parce qu'omarchy-system-lock termine par un pkill sur
    l'economiseur d'ecran : la fermeture de cette fenetre rallumait le pad au
    moment meme ou l'ecran de mot de passe apparaissait, qui s'affichait donc
    en double. Couvre aussi le verrouillage manuel, sans economiseur.
    """
    etait_verrouillee = False
    while True:
        time.sleep(2)
        try:
            verrouillee = session_verrouillee()
            if verrouillee and not etait_verrouillee:
                if pad_allume():
                    eteindre_pad()
            elif not verrouillee and etait_verrouillee:
                # Ne pas rendre le pad si l'economiseur tourne encore : c'est
                # a lui de decider, il a sa propre logique.
                if not fenetres and not pad_allume():
                    reparer_pad()
            etait_verrouillee = verrouillee
        except Exception as e:      # un veilleur ne doit jamais mourir
            print(f"surveillance du verrouillage : {e}", file=sys.stderr, flush=True)


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

    threading.Thread(target=surveiller_verrouillage, args=(fenetres,),
                     daemon=True).start()

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
                # Le verrouillage tue l'economiseur : sans ce garde-fou, le pad
                # se rallumait pile quand l'ecran de mot de passe apparait.
                # surveiller_verrouillage() le rendra au deverrouillage.
                if not fenetres and not pad_allume() and not session_verrouillee():
                    reparer_pad()


if __name__ == "__main__":
    try:
        main()
    except (KeyboardInterrupt, BrokenPipeError, ConnectionError):
        pass
