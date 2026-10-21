#!/usr/bin/env python3
"""Clic (ou tape) a 3 doigts sur le ScreenPad en mode souris -> dock tactile.
Une tape ou un clic a un doigt sur la croix du pave (en haut a droite) aussi.
En mode tactile, 3 doigts poses -> mode souris : le dock compte aussi les
contacts, mais une tuile qui prend un doigt lui fait rater le geste.

Pendant inverse du geste du lanceur : en mode tactile c'est le dock qui compte
les contacts et repasse en trackpad. En mode trackpad le dock ne recoit plus
aucun toucher (libinput en fait des mouvements de souris), d'ou ce service qui
lit directement le peripherique evdev du pad, sans le saisir (pas de grab) :
la souris continue de fonctionner normalement.

Acces au peripherique : /etc/udev/rules.d/72-screenpad-geste-uaccess.rules.
"""
import fcntl, glob, json, os, struct, subprocess, sys, time

NOM_PAD = "GDX1515:00 27C6:01F4 Touchpad"
REGLE_TACTILE = "/etc/udev/rules.d/71-screenpad-touchscreen.rules"
ETAT_MODE = os.path.expanduser("~/.local/state/omarchy/screenpad-mode")
TP_COUPE = os.path.expanduser(
    "~/.local/state/omarchy/toggles/hypr/touchpad-disabled-name")
SP = "/usr/local/bin/screenpad-power"
DOCK = os.path.expanduser("~/.local/bin/screenpad-dock")

EV_SYN, EV_KEY, EV_ABS = 0, 1, 3
ABS_X, ABS_Y = 0x00, 0x01
BTN_LEFT, BTN_TOUCH = 0x110, 0x14a
DOIGTS = {0x145: 1, 0x14d: 2, 0x14e: 3, 0x14f: 4}   # BTN_TOOL_FINGER..QUADTAP
EVENT = struct.Struct("llHHi")

TAPE_MAX = 0.25       # s : au-dela c'est un appui ou un glissement
TAPE_CROIX_MAX = 0.5  # s : la croix se vise, la tape y est plus lente
BOUGE_MAX_MM = 3.0    # une tape ne se deplace (presque) pas
# Zone de la croix du pave, en fractions de la surface (x vers la droite,
# y vers le bas), collee a l'angle : un peu plus large que le dessin pour
# viser au doigt. Reglee a l'essai sur le pad.
CROIX_X_MIN, CROIX_Y_MAX = 0.90, 0.17
REPOS = 5.0           # s : la bascule udev prend ~3 s, ignorer les rebonds
dernier = 0.0         # hors de ecouter() : le pad est rouvert apres chaque bascule


def trouver_pad():
    for f in glob.glob("/sys/class/input/event*/device/name"):
        try:
            with open(f) as h:
                if h.read().strip() == NOM_PAD:
                    return "/dev/input/" + f.split("/")[4]
        except OSError:
            pass
    return None


def absinfo(fd, axe):
    """EVIOCGABS : struct input_absinfo (value, min, max, fuzz, flat, resolution)."""
    try:
        return struct.unpack("6i", fcntl.ioctl(fd, 0x80184540 + axe, bytes(24)))
    except OSError:
        return (0, 0, 0, 0, 0, 0)


def resolution(fd, axe):
    """Resolution en unites/mm."""
    return absinfo(fd, axe)[5] or 1


def run(*cmd, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, **kw)
    except (subprocess.SubprocessError, OSError):
        return None


def mode_trackpad_actif():
    """Vrai seulement si le pad est une souris active et visible de l'utilisateur."""
    if os.path.exists(REGLE_TACTILE):          # mode tactile
        return False
    return session_visible()


def mode_tactile_actif():
    """Vrai si le pad est un ecran tactile et que le dock l'affiche."""
    if not os.path.exists(REGLE_TACTILE):
        return False
    r = run("systemctl", "--user", "is-active", "--quiet", "screenpad-dock")
    return bool(r and r.returncode == 0) and session_visible()


def session_visible():
    if os.path.exists(TP_COUPE) and os.path.getsize(TP_COUPE) > 0:
        return False                           # etat 3 du cycle : tout desactive
    r = run("pidof", "hyprlock")
    if r and r.returncode == 0:              # session verrouillee
        return False
    r = run("hyprctl", "clients", "-j")
    if r and r.returncode == 0:
        try:
            if any(c.get("class") == "org.omarchy.screensaver"
                   for c in json.loads(r.stdout)):
                return False
        except ValueError:
            pass
    return True


def pave_affiche():
    """La croix n'existe que si le dock tourne et montre le pave du mode souris."""
    try:
        with open(ETAT_MODE) as f:
            if f.read().strip() != "trackpad":
                return False
    except OSError:
        return False
    r = run("systemctl", "--user", "is-active", "--quiet", "screenpad-dock")
    return bool(r and r.returncode == 0)


def passer_en_souris():
    run("systemctl", "--user", "kill", "--kill-whom=main",
        "-s", "SIGUSR2", "screenpad-dock")


def passer_en_tactile():
    try:
        os.makedirs(os.path.dirname(ETAT_MODE), exist_ok=True)
        with open(ETAT_MODE, "w") as f:
            f.write("tactile")
    except OSError as e:
        print(f"etat non enregistre : {e}", file=sys.stderr)

    r = run("sudo", "-n", SP, "status")
    try:
        allume = (int(r.stdout.strip(), 16) & 0xffff) != 0
    except (AttributeError, ValueError):
        allume = True
    if not allume:
        run("omarchy-osd", "-i", "󰍹", "-m", "ScreenPad tactile")
        run("sudo", "-n", SP, "on")

    r = run("systemctl", "--user", "is-active", "--quiet", "screenpad-dock")
    if r and r.returncode == 0:
        # Le dock masque son pave et fait lui-meme la bascule tactile.
        # --kill-whom=main : les applis lancees depuis le dock vivent dans le
        # meme cgroup, un SIGUSR1 les tuerait.
        run("systemctl", "--user", "kill", "--kill-whom=main",
            "-s", "SIGUSR1", "screenpad-dock")
    else:
        # Au premier affichage le dock relit ETAT_MODE (tactile) et bascule.
        run("systemd-run", "--user", "--quiet", "--unit=screenpad-dock",
            "--description=Ecran d'accueil du ScreenPad", DOCK)


def ecouter(chemin):
    fd = os.open(chemin, os.O_RDONLY)
    seuil = BOUGE_MAX_MM * max(resolution(fd, ABS_X), resolution(fd, ABS_Y))
    _v, xmin, xmax, *_r = absinfo(fd, ABS_X)
    _v, ymin, ymax, *_r = absinfo(fd, ABS_Y)

    def sur_croix(px, py):
        if px is None or py is None or xmax <= xmin or ymax <= ymin:
            return False
        return ((px - xmin) / (xmax - xmin) >= CROIX_X_MIN
                and (py - ymin) / (ymax - ymin) <= CROIX_Y_MAX)
    doigts = max_doigts = 0
    debut = 0.0
    # Position courante initialisee depuis le noyau : evdev n'envoie un axe que
    # s'il a change, une tape au meme endroit n'en renvoie aucun.
    x, y = absinfo(fd, ABS_X)[0], absinfo(fd, ABS_Y)[0]
    x0 = y0 = None
    nouveau = bouge = clic = False

    def declencher_souris():
        global dernier
        if time.monotonic() - dernier < REPOS or not mode_tactile_actif():
            return
        print("3 doigts en tactile : bascule en souris", flush=True)
        dernier = time.monotonic()
        passer_en_souris()

    def declencher(croix=False):
        global dernier
        if croix:
            # La croix n'est visible que pave affiche : pas de rebond possible,
            # donc pas d'attente apres la bascule precedente.
            if not pave_affiche():
                return
            print("bascule en tactile (croix)", flush=True)
            dernier = time.monotonic()
            passer_en_tactile()
            return
        if time.monotonic() - dernier < REPOS:
            print("ignore : bascule precedente trop recente", flush=True)
            return
        if not mode_trackpad_actif():
            print("ignore : pad pas en mode souris active", flush=True)
            return
        print("bascule en tactile", flush=True)
        dernier = time.monotonic()
        passer_en_tactile()

    try:
        while True:
            data = os.read(fd, EVENT.size * 64)
            for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                _s, _us, typ, code, val = EVENT.unpack_from(data, i)
                if typ == EV_SYN and nouveau:
                    # Fin de la trame du premier contact : position de depart.
                    x0, y0, nouveau = x, y, False
                elif typ == EV_ABS and code in (ABS_X, ABS_Y):
                    if code == ABS_X:
                        x = val
                    else:
                        y = val
                    if x0 is not None and (abs(x - x0) > seuil or abs(y - y0) > seuil):
                        bouge = True
                elif typ == EV_KEY and code in DOIGTS:
                    if val:
                        doigts = DOIGTS[code]
                        max_doigts = max(max_doigts, doigts)
                        if doigts >= 3 and os.path.exists(REGLE_TACTILE):
                            declencher_souris()
                elif typ == EV_KEY and code == BTN_LEFT and val == 1:
                    print(f"clic physique avec {doigts} doigt(s)", flush=True)
                    if doigts >= 3:
                        clic = True
                        declencher()
                    elif doigts == 1 and sur_croix(*((x0, y0) if x0 is not None else (x, y))):
                        print("clic sur la croix", flush=True)
                        clic = True
                        declencher(croix=True)
                elif typ == EV_KEY and code == BTN_TOUCH:
                    if val == 1:
                        debut = time.monotonic()
                        max_doigts, bouge, clic = 0, False, False
                        x0 = y0 = None
                        nouveau = True
                    else:
                        if max_doigts >= 3:
                            print(f"contact {max_doigts} doigts : "
                                  f"{time.monotonic() - debut:.2f} s, "
                                  f"bouge={bouge}, clic={clic}", flush=True)
                        if (max_doigts >= 3 and not clic and not bouge
                                and time.monotonic() - debut < TAPE_MAX):
                            declencher()
                        elif max_doigts == 1 and not clic and sur_croix(x0, y0):
                            duree = time.monotonic() - debut
                            if not bouge and duree < TAPE_CROIX_MAX:
                                print("tape sur la croix", flush=True)
                                declencher(croix=True)
                            else:
                                print(f"croix ratee : {duree:.2f} s, bouge={bouge}",
                                      flush=True)
                        doigts = 0
    finally:
        os.close(fd)


def main():
    while True:
        chemin = trouver_pad()
        if chemin is None:
            time.sleep(1)
            continue
        try:
            ecouter(chemin)
        except OSError:
            # ENODEV : le pad est recree a chaque bascule tactile/trackpad.
            time.sleep(0.5)


if __name__ == "__main__":
    main()
