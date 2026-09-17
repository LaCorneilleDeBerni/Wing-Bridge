#!/usr/bin/env python3
"""
Séquence d'initialisation de la MA2 Wing — générée depuis d.pcapng
La wing nécessite un upload firmware ARM à chaque démarrage.
"""
import etat
import hashlib
import os, sys, time, usb.core, usb.util, usb.backend.libusb1
from pathlib import Path

VID = 0x03EB
PID = 0x160B
EP_IN  = 0x81
EP_OUT = 0x02
TIMEOUT_MS = 500

HELLO_PKT    = bytes.fromhex("0190040000000000")
FW_END_PKT   = bytes.fromhex("079004000000300000000000")
FW_CFG_PKT   = bytes.fromhex("109004007c000000")
HELLO2_PKT   = bytes.fromhex("0190040000000000")

# ── 🧪 Carte des LEDs après FW_CFG : expérience CLOSE (intestable) ─────────────
#
# MA2 onPC envoie parfois (2 cycles sur 13 captures) la carte des LEDs (264 o)
# AU BOOTLOADER, ~6,6 ms après FW_CFG_PKT. Intestable par cette voie :
# l'endpoint de SORTIE se bloque dans la 1re ms après FW_END_PKT, FW_CFG_PKT
# lui-même ne part pas. Code gardé désactivé : si un jour l'endpoint tient,
# c'est la première chose à réessayer (repasser à True).
# → docs/HARDWARE.md, « Comparaison avec MA2 onPC ».
ENVOYER_CARTE_LED = False
FW_LED_PKT   = bytes.fromhex("04900401") + bytes(260)   # 264 o, comme MA2 onPC
FW_LED_DELAI = 0.0066                                    # 6,6 ms mesurés

# ── QUI RÉPOND AU HELLO : le bootloader, ou le firmware applicatif ? ──────────
#
# 🔑 Relevé dans `d.pcapng`, la capture d'origine de MA2 onPC.
# Le MÊME paquet Hello (`0190040000000000`) reçoit DEUX réponses distinctes
# selon l'interlocuteur :
#
#   bootloader Atmel  → 0400079101000100   (device 21 de la capture)
#   firmware chargé   → 0791040001000200   (device 22, après le reboot)
#
# Dans `d.pcapng` : 18 paquets d'entrée portent la signature bootloader (17
# chunks de 1024 o + l'accusé du Hello lui-même), tous identiques ; côté
# applicatif, la 2nde signature n'apparaît elle qu'une seule fois — la
# poignée de main post-reboot — et tout le reste est du paquet d'état
# (`03907c00…`).
#
# 🔁 Recontrôlé sur les 5 captures `Wireshark capture/Phase 2/` (les seules
# autres à couvrir une connexion à froid) : même partition sur chacune —
# 2 Hello par capture, toujours la signature bootloader avant le reboot puis
# l'applicatif après. **12/12** sur les 6 captures qui contiennent
# effectivement un Hello. ⚠️ Ne pas invoquer `a-1.pcapng` / `test 2-1.pcapng`
# / `ts 3-1.pcapng` / `testwing.pcapng` comme preuve ici : elles sont du
# régime établi et ne contiennent AUCUN paquet Hello — elles ne peuvent ni
# confirmer ni infirmer quoi que ce soit sur ce point.
#
# ⚠️ POURQUOI ÇA COMPTE. `etat_wing()` déduit l'état de la VITESSE d'énumération
# USB — une heuristique que ce fichier assume comme telle, avec son repli
# « inconnu → tenter et voir ». Ces deux signatures, elles, sont la wing qui dit
# ELLE-MÊME qui elle est : c'est une preuve de protocole, pas une déduction.
# On s'en sert pour refuser un envoi de firmware à une wing qui tourne, y
# compris quand la vitesse est illisible — le trou que la vitesse seule laissait.
HELLO_REP_BOOTLOADER = bytes.fromhex("0400079101000100")
HELLO_REP_APPLICATIF = bytes.fromhex("0791040001000200")

# Paquet de sondage, pour la preuve de vie en fin d'init.
# ⚠️ DOIT rester identique à wing_bridge.POLL — c'est le même paquet que celui
# de la boucle de polling, sinon le test ne prouve rien. Recopié plutôt
# qu'importé pour ne pas créer de dépendance circulaire entre les deux modules ;
# le test de fumée vérifie qu'ils ne divergent pas.
POLL_PKT     = bytes.fromhex("05900000")
POLL_ESSAIS  = 12                     # ~12 × (300 ms max) — largement suffisant
CONFIG2_PKT  = bytes.fromhex("109004007c000000")

# En mode figé (PyInstaller), les ressources sont dans sys._MEIPASS
if getattr(sys, "frozen", False):
    _DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    _DIR = os.path.dirname(os.path.abspath(__file__))

# ── Le firmware côté FICHIERS (cache, blob livré, empreinte) vit dans
# wing_firmware.py — ce module-ci ne fait que le DIALOGUE avec la wing.
import wing_firmware
import wing_etat_materiel




def _backend():
    """
    Backend libusb. Ordre de recherche :
    1. dylib/DLL posée à côté des scripts (ou embarquée dans l'app figée)
       → sous Windows : mettre libusb-1.0.dll dans ce dossier, rien d'autre à faire
    2. libusb installée au niveau système (Homebrew sur Mac, PATH sur Windows)
    """
    for name in ("libusb-1.0.dll", "libusb-1.0.0.dylib", "libusb-1.0.dylib"):
        cand = os.path.join(_DIR, name)
        if os.path.exists(cand):
            return usb.backend.libusb1.get_backend(
                find_library=lambda x, c=cand: c)
    return usb.backend.libusb1.get_backend()


# Journal de l'application. wing_ui y branche sa fonction `log` au démarrage.
# Sans ça, les messages d'init partent en print() vers stdout — c'est-à-dire
# nulle part une fois l'app lancée depuis le Finder. Or ce sont précisément les
# messages qui expliquent une wing qui ne répond pas : ils doivent arriver
# sous les yeux de l'utilisateur, pas dans un flux perdu.
JOURNAL = None


def _msg(cle_ou_texte, **params):
    """`cle_ou_texte` : une clé `journal.*` (+ `params`) depuis la Phase 2
    i18n, ou un texte nu (repli `print` quand `JOURNAL` n'est pas branché —
    tests, exécution hors app)."""
    if JOURNAL is not None:
        try:
            JOURNAL(cle_ou_texte, **params)
            return
        except Exception:
            pass
    print(cle_ou_texte if not params
          else f"{cle_ou_texte} {params}")


def _read(dev, timeout_ms=TIMEOUT_MS):
    try:
        return bytes(dev.read(EP_IN, 2048, timeout=timeout_ms))
    except Exception:
        return None


# ⚠️ « USBError » tout court ne dit RIEN : un délai dépassé (device présent,
# muet) et un device PARTI du bus sont la même classe d'exception — et c'est
# la distinction qui compte. On lit donc le code (`_partie_du_bus`) avant de
# conclure.
_ERR_USB = {-1: "E/S", -4: "device parti", -7: "délai dépassé",
            -9: "pipe (stall)", -5: "introuvable", -6: "occupé",
            -99: "erreur libusb générique (LIBUSB_ERROR_OTHER)"}
_ERR_ERRNO = {5: "E/S", 19: "device parti", 60: "délai dépassé",
              32: "pipe (stall)", 110: "délai dépassé", 16: "occupé"}


def _err_usb(e) -> str:
    """Décrit une erreur USB de façon exploitable. Voir _ERR_USB ci-dessus.

    ⚠️ CODE INTERNE STABLE, jamais traduit : `_partie_du_bus()` compare son
    résultat par égalité (`in (...)`) — une traduction romprait la
    comparaison dès que l'app tourne en anglais. Pour un texte AFFICHÉ
    (journal, trace), utiliser `_err_usb_texte()` ci-dessous."""
    b = getattr(e, "backend_error_code", None)
    n = getattr(e, "errno", None)
    return (_ERR_USB.get(b) or _ERR_ERRNO.get(n)
            or f"{type(e).__name__}({b if b is not None else n})")


# Code interne (_err_usb) → clé i18n, pour le texte AFFICHÉ. Les codes qui ne
# sont pas dans _ERR_USB/_ERR_ERRNO (repli `f"{type}({b or n})"`, ex.
# "USBError(110)") restent tels quels : ce sont déjà des identifiants
# techniques, pas de la prose française.
_ERR_USB_CLES = {
    "E/S": "journal.init.err_usb.es",
    "device parti": "journal.init.err_usb.parti",
    "délai dépassé": "journal.init.err_usb.timeout",
    "pipe (stall)": "journal.init.err_usb.stall",
    "introuvable": "journal.init.err_usb.introuvable",
    "occupé": "journal.init.err_usb.occupe",
    "erreur libusb générique (LIBUSB_ERROR_OTHER)": "journal.init.err_usb.generique",
}


def _err_usb_texte(e) -> str:
    """Version AFFICHÉE (langue courante de l'app) de `_err_usb()` — pour le
    journal/la trace, jamais pour une comparaison (voir `_err_usb`)."""
    import wing_i18n
    code = _err_usb(e)
    cle = _ERR_USB_CLES.get(code)
    return wing_i18n.L(cle) if cle else code


def _partie_du_bus(e) -> bool:
    """L'erreur prouve-t-elle que la wing a QUITTÉ le bus ? (≠ simple silence)"""
    return _err_usb(e) in ("device parti", "introuvable", "pipe (stall)")


def _noter_paquet(d, ms):
    """Comptabilise un paquet reçu dans la fenêtre d'après FW_CFG. Voir _DRAIN."""
    _DRAIN["paquets"] += 1
    _DRAIN["octets"] += len(d)
    if _DRAIN["premier_ms"] is None:
        _DRAIN["premier_ms"] = ms
    _DRAIN["dernier_ms"] = ms
    _DRAIN["signature"] = d[:8].hex()


def _attendre_en_lisant(dev, duree_s, ms):
    """Attend `duree_s` en LISANT, au lieu de dormir les yeux fermés.

    🐛 Défaut trouvé en éprouvant l'instrumentation, pas sur le matériel. Le
    délai avant la carte des LEDs était un `time.sleep(6,6 ms)`
    aveugle : or c'est exactement la portion de fenêtre où `d.pcapng` montre
    QUATRE paquets entrants. On mesurait donc une fenêtre dont on ratait le
    premier quart — et on ne pouvait pas le savoir, faute de compteur.

    ⚠️ N'ajoute AUCUN paquet sortant : uniquement des lectures, que la référence
    fait au même endroit et que le drain refait 6,6 ms plus tard. Le rythme de
    l'expérience est préservé — la carte des LEDs part toujours à +6,6 ms.
    🔁 Pour revenir au sommeil aveugle : remettre `time.sleep(FW_LED_DELAI)`.
    """
    fin = time.perf_counter() + duree_s
    while True:
        reste = fin - time.perf_counter()
        if reste <= 0.0005:          # moins d'½ ms : ne pas déborder du rendez-vous
            break
        try:
            d = bytes(dev.read(EP_IN, 2048, timeout=max(1, int(reste * 1000))))
        except Exception as e:
            if _partie_du_bus(e) and _DRAIN["partie_ms"] is None:
                _DRAIN["partie_ms"], _DRAIN["partie_par"] = ms(), _err_usb_texte(e)
                return
            continue
        if d:
            _noter_paquet(d, ms())


# Résultat de la dernière ouverture USB — chaque étape y est notée (elles
# échouaient toutes en silence). ❌ La revendication perdue n'explique PAS la
# wing lente après un redémarrage : réfuté, `claim` valait `ok` pendant la
# panne. Garder la mesure — c'est elle qui a réfuté en dix secondes.
DERNIER_OPEN = {"detach": "", "config": "", "claim": "", "halt": ""}


def _open(vid=VID, pid=PID):
    b = _backend()
    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=b)
    if dev is None:
        return None
    DERNIER_OPEN.update(detach="", config="", claim="", halt="")
    for iface in range(2):
        try:
            if dev.is_kernel_driver_active(iface):
                dev.detach_kernel_driver(iface)
        except Exception as e:
            # Bénin sur macOS : il n'y a en général aucun pilote noyau attaché
            # à un périphérique vendor-specific. On garde la trace, sans bruit.
            DERNIER_OPEN["detach"] = f"{type(e).__name__}: {e}"
    # ⚠️ On ne configure QUE si la wing ne l'est pas déjà.
    #
    # 🔎 Piste à surveiller. Sur macOS, `set_configuration` passe
    # par IOKit SetConfiguration, qui RE-CONFIGURE le périphérique même quand
    # on lui redemande la configuration courante. C'est un des rares gestes de
    # `_open()` capables d'agir sur la wing elle-même — et il était fait à
    # chaque ouverture, y compris sur une wing déjà configurée et en pleine
    # forme. Candidat sérieux pour la lenteur résiduelle, qui apparaît
    # justement à la RÉOUVERTURE de la liaison, sans rien d'autre autour.
    try:
        deja = dev.get_active_configuration()
    except Exception:
        deja = None
    if deja is None:
        try:
            dev.set_configuration()
            DERNIER_OPEN["config"] = "configurée"
        except Exception as e:
            DERNIER_OPEN["config"] = f"{type(e).__name__}: {e}"
    else:
        DERNIER_OPEN["config"] = "déjà configurée — non retouchée"
    # ── Revendication de l'interface, AVEC PATIENCE (jusqu'à 1,5 s) ──────────
    # Le système met parfois un instant à rendre l'interface après une fermeture :
    # échouer aussitôt faisait marteler « Access denied » (9 fois en 28 s) là où
    # quelques centaines de millisecondes suffisaient.
    DERNIER_OPEN["claim"] = ""
    for _ in range(6):
        try:
            usb.util.claim_interface(dev, 0)
            DERNIER_OPEN["claim"] = ""
            break
        except Exception as e:
            DERNIER_OPEN["claim"] = f"{type(e).__name__}: {e}"
            time.sleep(0.25)
    if DERNIER_OPEN["claim"]:
        # ⚠️ Aucun conseil de débranchement ici. Ce message le portait, et
        # s'affichait 9 fois d'affilée dans un cas qui se réglait tout seul.
        _msg("journal.init.claim_ko", claim=DERNIER_OPEN['claim'])

    # ── Déblocage des endpoints : `clear_halt` à CHAQUE ouverture ────────────
    # Après un redémarrage en place (os.execv), l'ancienne image meurt souvent avec
    # un transfert en vol : les endpoints restent en HALT et la 1re lecture rend
    # « [Errno 32] Pipe error » — un endpoint bloqué, pas une wing absente. Le
    # prendre pour une wing muette faisait recharger le firmware pour rien (et une
    # fois sur deux la wing revenait lente). Sans effet sur des endpoints sains.
    for ep in (EP_IN, EP_OUT):
        try:
            dev.clear_halt(ep)
        except Exception as e:
            DERNIER_OPEN["halt"] = f"ep 0x{ep:02x} — {type(e).__name__}: {e}"
    return dev


# ── État de la wing, lu sur la VITESSE d'énumération USB ─────────────────────
#
# Découvert après une panne d'une heure, vérifié sur toutes les observations
# disponibles sans contre-exemple :
#
#   HIGH / 480 Mb/s (speed=3) → BOOTLOADER Atmel. Répond au Hello, JAMAIS au
#                               polling. C'est l'état au branchement.
#   FULL /  12 Mb/s (speed=2) → firmware applicatif chargé. Répond au polling.
#
# C'est le seul moyen fiable de savoir à qui on parle AVANT de lui parler.
# Fail-safe : toute autre valeur (ou absence) donne "inconnu", et on retombe
# alors sur le comportement d'avant — tenter et voir.
VITESSE_LIB = {1: "LOW/1.5", 2: "FULL/12", 3: "HIGH/480", 4: "SUPER"}


def _trouver(vid=VID, pid=PID):
    """Trouve la wing SANS revendiquer l'interface — lecture d'état seule."""
    try:
        return usb.core.find(idVendor=vid, idProduct=pid, backend=_backend())
    except Exception:
        return None


def etat_wing(dev):
    """'operationnelle' | 'bootloader' | 'inconnu'."""
    v = getattr(dev, "speed", None)
    if v == 2:
        return "operationnelle"
    if v == 3:
        return "bootloader"
    return "inconnu"


def attendre_reapparition(timeout_s=8.0, fige_s=None, _t0=None):
    """Attend que la wing réapparaisse après un reboot. Retourne (dev, état).

    On ne se contente plus de « un device est là » : c'est ce qui faisait
    saisir l'ANCIENNE énumération, ou le bootloader pris pour la wing prête.
    On attend l'état opérationnel, et on rend la main dès qu'il arrive.

    ⚠️⚠️ LE CHIFFRE DE LA TRACE ÉTAIT UN ARTEFACT.
    Quand la wing revient en BOOTLOADER, cette fonction ne sort pas : elle
    attend le délai COMPLET. La trace annonçait donc « revenue à +15,7 s » sur
    quatre échecs d'affilée — un chiffre remarquablement constant… parce que
    c'était le timeout, pas une mesure. On a failli chercher une cause à une
    régularité qui n'en était pas une.
    🔑 On horodate donc la PREMIÈRE FOIS où on la voit, séparément du temps
    total d'attente. C'est ce premier chiffre qui dit quelque chose du matériel.

    ⏱️ ON RELÈVE AUSSI LE TRAJET, pas seulement l'état final.
    Neuf échecs d'affilée ont tous annoncé « verdict à 15,6 s » : le délai est
    consommé EN ENTIER à chaque fois. Or on ignore si l'état bouge pendant ces
    quinze secondes. Deux issues, et les deux sont utiles :
      • il bouge  → attendre plus longtemps transformerait des échecs en
        réussites, et c'est gratuit ;
      • il ne bouge jamais → on peut trancher en 2 s au lieu de 15, et chaque
        rebranchement coûte cinq fois moins de patience.
    Sans ce relevé on ne peut faire ni l'un ni l'autre.

    ⚡ `fige_s` — VERDICT ANTICIPÉ. Si l'état reste le même pendant `fige_s`
    après la réapparition, on rend la main sans attendre le délai complet.
    Mesuré : sur 10 échecs, la wing réapparaît en bootloader vers
    +1 s et **n'en bouge plus** — les 14,6 s suivantes n'apprennent rien et
    n'apportent qu'une chose : de l'attente. Le trajet reste enregistré, donc
    si une wing se réveillait tard, on le VERRAIT au lieu de le supposer.
    🔁 Pour revenir au comportement long : appeler sans `fige_s`.

    `_t0` : 🔎 DIAGNOSTIC (PAS UN CORRECTIF). Référence de temps
    externe (le même `_t0` que `full_init`), utilisée UNIQUEMENT pour horodater
    `_REVEIL_DIAG["polls_reapparition"]` sur une frise partagée avec le reste
    de la zone post-reboot. `trajet`/`vue_s`/`anticipe_s` restent, eux,
    calculés sur le `t0` local ci-dessous — inchangé, pour ne rien déplacer
    dans un champ déjà lu ailleurs. Sans `_t0` (appel hors `full_init`, ex.
    `_tenter_reveil`), on retombe sur `t0` local pour les deux.
    """
    t_end = time.time() + timeout_s
    dernier = None
    DERNIER_ENVOI["vue_s"] = None          # première apparition, en secondes
    DERNIER_ENVOI["trajet"] = []           # (seconde, état) aux CHANGEMENTS
    DERNIER_ENVOI["anticipe_s"] = None
    # 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — voir _REVEIL_DIAG en tête
    # de fichier. Repart à zéro à CHAQUE appel : ne reflète que l'attente en
    # cours, comme `trajet` juste au-dessus.
    _REVEIL_DIAG["polls_reapparition"] = []
    t0 = time.perf_counter()
    t0_diag = _t0 if _t0 is not None else t0   # voir la note sur `_t0` ci-dessus
    precedent, depuis = None, None
    while time.time() < t_end:
        d = _trouver()
        e = etat_wing(d) if d is not None else "absente"
        maintenant = time.perf_counter() - t0
        if e != precedent:
            DERNIER_ENVOI["trajet"].append((maintenant, e))
            precedent, depuis = e, maintenant
        # 🔎 DIAGNOSTIC — CHAQUE scrutation, pas seulement les changements.
        # `vitesse_brute` = `dev.speed` non mappé (voir VITESSE_LIB) : c'est
        # ELLE qui permettrait de voir un flottement que `etat` seul masque
        # (ex. deux valeurs brutes différentes qui se mappent sur le même
        # « inconnu »).
        _REVEIL_DIAG["polls_reapparition"].append((
            round((time.perf_counter() - t0_diag) * 1000.0, 1),
            d is not None,
            getattr(d, "speed", None) if d is not None else None,
            e))
        if d is not None:
            if DERNIER_ENVOI.get("vue_s") is None:
                DERNIER_ENVOI["vue_s"] = maintenant
            dernier = (d, e)
            if e in ("operationnelle", "inconnu"):
                return d, e
            if fige_s and depuis is not None and maintenant - depuis >= fige_s:
                DERNIER_ENVOI["anticipe_s"] = maintenant
                return d, e
        time.sleep(0.2)
    return dernier if dernier else (None, None)


def attendre_disparition(timeout_s=3.0, _t0=None) -> bool:
    """Attend que la wing QUITTE le bus. Utilisé après un reset de port.

    🐛 Sans cette attente, `_tenter_reveil` rouvrait la wing avant
    qu'elle ait re-énuméré : il saisissait l'ANCIENNE énumération, dont la
    poignée était déjà morte. Toutes les écritures échouaient, et on concluait
    « ✗ toujours lente (muette) » — en conseillant de débrancher — alors que le
    reset avait parfaitement fonctionné. Preuve : 5 s plus tard, la
    reconnexion automatique trouvait la wing à 1,1 ms.

    `_t0` : 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — même rôle que dans
    `attendre_reapparition` : horodate `_REVEIL_DIAG["polls_disparition"]` sur
    la frise partagée de `full_init` si fourni, sinon sur un départ local.
    Ne change ni la logique ni la valeur de retour.
    """
    t0_diag = _t0 if _t0 is not None else time.perf_counter()
    _REVEIL_DIAG["polls_disparition"] = []
    fin = time.time() + timeout_s
    while time.time() < fin:
        absente = _trouver() is None
        # 🔎 DIAGNOSTIC — chaque scrutation, présente ou non.
        _REVEIL_DIAG["polls_disparition"].append((
            round((time.perf_counter() - t0_diag) * 1000.0, 1), not absente))
        if absente:
            return True
        time.sleep(0.1)
    return False


def wing_absente() -> bool:
    """La wing a-t-elle disparu du bus ? (= débranchée)

    Sert à l'appelant pour savoir qu'une coupure d'alimentation a bien eu lieu,
    seule condition dans laquelle un nouvel envoi de firmware a une chance.
    """
    return _trouver() is None


def upload_firmware(dev, verbose=True, force_operateur=False):
    """
    Phase 1 : upload firmware ARM vers la wing (device à l'adresse initiale).
    Retourne True si succès, False sinon.

    ⚠️ `force_operateur=True` : saute UNIQUEMENT les deux
    refus « wing déjà opérationnelle » (vitesse d'énumération + Hello applicatif)
    ci-dessous. Armé UNIQUEMENT par le chemin de reconnexion automatique après un
    arrachage à chaud (`RECO_MUETTE["force_demande"]` → usb_loop). Le garde-fou
    reste PLEINEMENT actif pour tout appelant qui ne passe pas ce drapeau — c'est
    la seule dérogation, et elle pousse volontairement une wing muette-mais-
    énumérée dans son bootloader pour la recharger (risque : rester en bootloader
    si l'upload cale — sur une wing déjà muette, c'est un compromis accepté).

    ⚠️ Un `False` ne veut PAS dire « l'envoi a échoué en cours de route ». Dans
    la quasi-totalité des cas, RIEN n'a été envoyé — on s'est arrêté avant, à la
    poignée de main. `DERNIER_ECHEC["raison"]` dit laquelle, pour que l'appelant
    n'écrive pas un message faux (un journal a déjà affiché « ✗ Échec de
    l'envoi du firmware » alors qu'aucun octet n'était parti).
    """
    if verbose:
        print("  [INIT] Phase 1 : upload firmware...")
    DERNIER_ECHEC["raison"] = ""
    DERNIER_ECHEC["envoi_tente"] = False

    # 🔎 DIAGNOSTIC (PAS UN CORRECTIF — pas de retry ajouté ici).
    # Remet à zéro les repères de rupture AVANT toute tentative, pour ne jamais
    # lire le résidu d'un essai précédent si celui-ci s'arrête avant d'avoir
    # atteint la fenêtre de drain (donc avant le reset partiel plus bas). Le
    # seul but est de savoir, la prochaine fois qu'un essai échoue, EXACTEMENT
    # à quel chunk (i/total) ou à quelle étape (Hello / FW_END / FW_CFG) —
    # au lieu du seul « échec après 20 s d'attente » qu'on avait jusqu'ici.
    _DRAIN.update(chunk_num=None, chunk_total=None, chunk_erreur="",
                  cfg_erreur="", cfg_octets=None,
                  chunks_duree_ms=None, chunk_max_gap_ms=None,
                  chunk_max_gap_num=None)

    # ⛔ GARDE-FOU AU POINT DE DANGER — ne jamais retirer.
    #
    # Le firmware bootloader ne doit partir QUE vers un bootloader. Envoyé à une
    # wing qui tourne déjà en mode applicatif (12 Mb/s), il déverse 34 624 octets
    # d'ARM brut dans le flux de COMMANDES du firmware en marche — et c'est
    # précisément ce qui la faisait retomber dans son bootloader.
    #
    # PROUVÉ par simulation : `full_init` retombait de son « cas 1 »
    # (wing opérationnelle mais muette) dans son « cas 2 » (bootloader) sans
    # jamais revérifier l'état — 67 écritures de 512 o vers une wing saine.
    #
    # Le garde-fou est ICI, au point de danger, et pas seulement chez l'appelant :
    # c'est la seule place qu'un futur chemin d'appel ne pourra pas contourner.
    # « inconnu » reste autorisé (repli historique « tenter et voir ») ; seul
    # l'état formellement opérationnel est refusé, parce que lui seul est prouvé
    # nuisible.
    if etat_wing(dev) == "operationnelle" and not force_operateur:
        import wing_i18n
        DERNIER_ECHEC["raison"] = wing_i18n.L("journal.init.raison.refuse_applicatif")
        _msg("journal.init.fw_refuse_applicatif")
        return False
    if force_operateur and etat_wing(dev) == "operationnelle":
        _msg("journal.init.fw_forcage")

    # 1. Hello
    dev.write(EP_OUT, HELLO_PKT, timeout=TIMEOUT_MS)
    resp = _read(dev, 1000)
    if verbose:
        print(f"    Hello → {resp.hex() if resp else 'timeout'}")
    if not resp:
        import wing_i18n
        DERNIER_ECHEC["raison"] = wing_i18n.L("journal.init.raison.hello_sans_reponse")
        return False

    # ⛔ SECOND GARDE-FOU, celui-ci fondé sur le PROTOCOLE et non sur la vitesse
    # d'énumération. La wing vient de dire qui elle est (cf. les signatures en
    # tête de fichier) : si c'est le firmware applicatif qui répond, on ne lui
    # envoie surtout pas les 34 ko du bootloader.
    #
    # Ça couvre le cas que le garde-fou de vitesse laisse passer : `etat_wing()`
    # rend "inconnu" quand la vitesse est illisible, et "inconnu" reste autorisé
    # à recevoir le firmware (repli historique « tenter et voir »). Ici, plus
    # besoin de deviner.
    if resp.startswith(HELLO_REP_APPLICATIF) and not force_operateur:
        import wing_i18n
        DERNIER_ECHEC["raison"] = wing_i18n.L(
            "journal.init.raison.refuse_hello_applicatif")
        _msg("journal.init.fw_refuse_hello")
        return False
    if verbose and not resp.startswith(HELLO_REP_BOOTLOADER):
        # Ni l'une ni l'autre : on continue (repli historique), mais on le dit.
        print(f"    ⚠️ signature inconnue au Hello : {resp[:8].hex()}")

    # 2. Upload firmware en chunks
    #
    # 🔑 On vérifie ce qui part RÉELLEMENT : `write()` rend le nombre d'octets
    # transférés, et une écriture courte décalerait l'image reçue par le
    # bootloader (firmware corrompu, wing restée en bootloader sans rien
    # signaler). Pas démontré comme cause des blocages observés — mais une
    # corruption silencieuse devient ainsi une panne nommée.
    #
    # ⛔ FIRMWARE NON CONFIGURÉ : la distribution OSS ne livre PAS le firmware (il
    # appartient à MA). Sans cache ni blob livré, on le dit et on renvoie vers
    # l'écran de configuration — jamais un `FileNotFoundError` nu.
    chemin_fw = wing_firmware.resoudre_firmware()
    if chemin_fw is None:
        import wing_i18n
        DERNIER_ECHEC["firmware_absent"] = True
        DERNIER_ECHEC["raison"] = wing_i18n.L("journal.init.raison.fw_non_configure")
        _msg("journal.init.fw_non_configure")
        return False
    with open(chemin_fw, "rb") as f:
        fw = f.read()
    # 🔒 EMPREINTE REVÉRIFIÉE SUR LES OCTETS QUI VONT PARTIR (audit du
    # 25/09/2026). Elle n'était contrôlée qu'à l'IMPORT (`enregistrer_firmware`).
    # Un cache abîmé sur le disque, ou un `wing_firmware.bin` remplacé à côté
    # de l'app, partait donc tel quel vers le bootloader — sans filet, sur du
    # matériel qu'on ne sait pas toujours ramener.
    # ⚠️ Calculée sur `fw` lui-même, PAS lue dans `_FW_SHA_CACHE` : ce cache
    # est indexé par (chemin, taille, date) — un fichier modifié sans changer
    # de taille ni de date passerait. 34 ko à hacher : moins d'une milliseconde.
    # Rien n'est encore parti à ce stade (`envoi_tente` reste faux) : refuser
    # ici ne déclenche pas l'anti-martèlement. Contrôle
    # test_empreinte_firmware_a_l_envoi (smoke_securite.py).
    sha_envoi = hashlib.sha256(fw).hexdigest()
    if sha_envoi != wing_firmware.FW_SHA256:
        import wing_i18n
        DERNIER_ECHEC["raison"] = wing_i18n.L("journal.init.raison.fw_empreinte")
        _msg("journal.init.fw_empreinte", chemin=chemin_fw,
             sha=sha_envoi[:16], attendu=wing_firmware.FW_SHA256[:16], o=len(fw))
        return False
    CHUNK = 512
    total = len(fw)
    sent  = 0
    # 🔎 DIAGNOSTIC — chunk_total sert à situer chaque échec dans la séquence
    # (« chunk 43/68 »), pas seulement par son offset en octets.
    chunk_total = (total + CHUNK - 1) // CHUNK
    # 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — la cadence RÉELLE d'envoi
    # n'a jamais été mesurée côté nous (« axe cadence d'envoi » de l'enquête :
    # la référence MA2 onPC est mesurée au tshark — 0,174 ms/chunk en moyenne,
    # 0,114-0,430 ms de plage — la nôtre ne l'était pas). But précis : voir si
    # l'app réelle (plusieurs threads concurrents : usb_loop, OSC, HTTP, DMX,
    # autosave, vegas) envoie plus lentement ou plus IRRÉGULIÈREMENT que ce
    # script isolé, sans thread concurrent. `chunk_max_gap_ms` importe plus
    # que la durée totale : une contention GIL ponctuelle se voit comme un pic
    # sur UN écart, pas comme une lenteur uniforme — la durée totale seule la
    # noierait dans la moyenne.
    t_chunks_debut = time.perf_counter()
    t_dernier_chunk = None
    # 🔑 À PARTIR D'ICI, DE VRAIS OCTETS DE FIRMWARE PARTENT SUR LE FIL — même
    # si l'écriture qui suit échoue. `full_init` s'en sert pour savoir s'il
    # doit horodater l'anti-martèlement : un Hello resté sans réponse ou un
    # Hello applicatif refusé n'ont, eux, RIEN envoyé.
    DERNIER_ECHEC["envoi_tente"] = True
    while sent < total:
        chunk = fw[sent:sent+CHUNK]
        chunk_num = sent // CHUNK + 1
        try:
            ecrit = dev.write(EP_OUT, chunk, timeout=TIMEOUT_MS)
        except Exception as e:
            # 🔎 DIAGNOSTIC — PAS UN CORRECTIF : aucun retry, on capture juste
            # QUEL chunk a fait échouer l'envoi, pour la prochaine occurrence.
            import wing_i18n
            _DRAIN["chunk_num"], _DRAIN["chunk_total"] = chunk_num, chunk_total
            # 🔒 _DRAIN["chunk_erreur"] : jamais relu ailleurs (grep vérifié) —
            # diagnostic interne, pas de clé i18n (voir _ALLOWLIST_J).
            _DRAIN["chunk_erreur"] = (
                f"exception at chunk {chunk_num}/{chunk_total} "
                f"(byte {sent}/{total}): {_err_usb(e)}")
            DERNIER_ECHEC["raison"] = wing_i18n.L(
                "journal.init.raison.ecriture_refusee", chunk=chunk_num,
                total=chunk_total, octet=sent, total_o=total,
                err=f"{type(e).__name__}: {e}")
            _msg("journal.init.fw_interrompu", n=chunk_num, total=chunk_total,
                 octets=sent, octets_total=total, err=e)
            return False
        if ecrit != len(chunk):
            import wing_i18n
            # 🔎 DIAGNOSTIC — même chose pour l'écriture courte.
            _DRAIN["chunk_num"], _DRAIN["chunk_total"] = chunk_num, chunk_total
            # 🔒 _DRAIN["chunk_erreur"] : jamais relu ailleurs — diagnostic
            # interne, pas de clé i18n.
            _DRAIN["chunk_erreur"] = (
                f"short write at chunk {chunk_num}/{chunk_total} "
                f"(byte {sent}/{total}): {ecrit}/{len(chunk)} B")
            DERNIER_ECHEC["raison"] = wing_i18n.L(
                "journal.init.raison.ecriture_courte", chunk=chunk_num,
                total=chunk_total, octet=sent, total_o=total,
                ecrit=ecrit, taille=len(chunk))
            _msg("journal.init.fw_ecriture_courte", n=chunk_num,
                 total=chunk_total, ecrit=ecrit, taille=len(chunk), offset=sent)
            return False
        # 🔎 DIAGNOSTIC — écart avec l'écriture précédente. Le premier chunk
        # n'a pas de précédent (t_dernier_chunk vaut encore None) : rien à
        # comparer, sinon le délai du Hello s'y mêlerait, pas comparable.
        t_maintenant = time.perf_counter()
        if t_dernier_chunk is not None:
            gap_ms = (t_maintenant - t_dernier_chunk) * 1000.0
            if (_DRAIN["chunk_max_gap_ms"] is None
                    or gap_ms > _DRAIN["chunk_max_gap_ms"]):
                _DRAIN["chunk_max_gap_ms"] = gap_ms
                _DRAIN["chunk_max_gap_num"] = chunk_num
        t_dernier_chunk = t_maintenant
        sent += ecrit
        if verbose and sent % (CHUNK*10) == 0:
            print(f"    Firmware {sent}/{total} bytes...")

    # 🔎 DIAGNOSTIC — durée totale des 68 écritures, comparable directement à
    # la référence MA2 onPC (7,65-28,84 ms mesurés au tshark).
    _DRAIN["chunks_duree_ms"] = (time.perf_counter() - t_chunks_debut) * 1000.0

    if sent != total:
        import wing_i18n
        DERNIER_ECHEC["raison"] = wing_i18n.L(
            "journal.init.raison.octets_incomplets", sent=sent, total=total)
        _msg("journal.init.fw_incomplet", octets=sent, octets_total=total)
        return False
    DERNIER_ENVOI["octets"] = sent
    if verbose:
        print(f"    Firmware sent: {total} bytes (verified)")

    # 3. Fin firmware — vérifié lui aussi : c'est LUI qui déclenche le boot.
    if FW_END_PKT:
        try:
            n = dev.write(EP_OUT, FW_END_PKT, timeout=TIMEOUT_MS)
        except Exception as e:
            import wing_i18n
            DERNIER_ECHEC["raison"] = wing_i18n.L(
                "journal.init.raison.fin_pas_partie", err=f"{type(e).__name__}: {e}")
            _msg("journal.init.fw_fin_ko", err=e)
            return False
        if n != len(FW_END_PKT):
            import wing_i18n
            DERNIER_ECHEC["raison"] = wing_i18n.L(
                "journal.init.raison.fin_tronque", n=n, total=len(FW_END_PKT))
            _msg("journal.init.fw_fin_tronque")
            return False
        if verbose:
            print(f"    End packet sent: {FW_END_PKT.hex()}")

    # 4. La wing reboot après l'end packet — toute écriture suivante peut échouer
    #    (device disparu du bus). On ignore les erreurs ici.
    #
    # ⏱️ C'est ICI que démarre la fenêtre qu'on mesure. Tout ce qui
    #    suit est horodaté par rapport à FW_CFG, pour être comparable ligne à
    #    ligne avec `d.pcapng`. Aucun paquet n'est ajouté : on ne fait que
    #    compter et dater ce que le drain lisait déjà et jetait.
    _DRAIN.update(paquets=0, octets=0, premier_ms=None, dernier_ms=None,
                  signature="", partie_ms=None, partie_par="", cfg_erreur="",
                  cfg_octets=None)
    if FW_CFG_PKT:
        try:
            n_cfg = dev.write(EP_OUT, FW_CFG_PKT, timeout=TIMEOUT_MS)
        except Exception as e:
            _DRAIN["cfg_erreur"] = _err_usb_texte(e)  # normal si elle reboote déjà
            # 🧪 EXPÉRIENCE clear_halt(EP_OUT) + renvoi de FW_CFG_PKT : classée
            # refusée sur le fond (7/7 branchements, `clear_halt` lui-même
            # échoue, aucune amélioration — `docs/HARDWARE.md`, « La fenêtre
            # après FW_CFG_PKT »). Retirée ici après suspicion de régression
            # (10/10 échecs de démarrage consécutifs, contre ~4/10 avant) —
            # corrélation non tranchée, retrait par prudence. Ne pas la
            # réintroduire sans un test isolé dédié.
        else:
            # 🔎 DIAGNOSTIC, PAS UN CORRECTIF — jusqu'ici, seule une EXCEPTION
            # sur ce write() était captée ; une écriture COURTE (transfert
            # accepté par libusb mais tronqué) passait inaperçue, contrairement
            # à FW_END_PKT et aux chunks du firmware, qui ont ce contrôle.
            # `cfg_erreur` reste ce que lit `_trace_drain()` : ce chemin ne
            # change PAS la valeur de retour
            # de `upload_firmware()`, qui continue de rendre `True` juste
            # après le drain quoi qu'il arrive ici — voir la note en tête de
            # fonction.
            _DRAIN["cfg_octets"] = n_cfg
            if n_cfg != len(FW_CFG_PKT):
                import wing_i18n
                _DRAIN["cfg_erreur"] = wing_i18n.L(
                    "journal.init.cfg_ecriture_courte", n=n_cfg,
                    total=len(FW_CFG_PKT))
    t_cfg = time.perf_counter()

    def _ms():
        return (time.perf_counter() - t_cfg) * 1000.0

    # 🧪 L'expérience : la carte des LEDs, comme MA2 onPC. Voir FW_LED_PKT.
    #    Toute erreur est ignorée — à cet instant la wing peut déjà rebooter,
    #    et un échec ici ne doit surtout pas faire échouer un envoi réussi.
    if ENVOYER_CARTE_LED and FW_LED_PKT:
        try:
            _attendre_en_lisant(dev, FW_LED_DELAI, _ms)
            n = dev.write(EP_OUT, FW_LED_PKT, timeout=TIMEOUT_MS)
            DERNIER_ENVOI["carte_led"] = n
        except Exception as e:
            import wing_i18n
            DERNIER_ENVOI["carte_led"] = wing_i18n.L("journal.init.led_refusee",
                                                      err=_err_usb_texte(e))
        DERNIER_ENVOI["led_ms"] = _ms()      # MA2 onPC : +6,6 ms
    else:
        DERNIER_ENVOI["carte_led"] = None

    # 5. Le drain. Il lisait déjà ces paquets ; il les JETAIT. Or c'est la seule
    #    fenêtre où la wing parle encore après l'ordre de démarrer, et la
    #    grandeur directement comparable à la référence : MA2 onPC y récolte
    #    17 paquets de 1024 o, tous à la signature bootloader, le dernier à
    #    +25,3 ms, puis 1,287 s de silence avant la ré-énumération.
    t_fin_drain = time.time() + 0.5
    while time.time() < t_fin_drain:
        try:
            d = bytes(dev.read(EP_IN, 2048, timeout=50))
        except Exception as e:
            if _partie_du_bus(e) and _DRAIN["partie_ms"] is None:
                _DRAIN["partie_ms"] = _ms()
                _DRAIN["partie_par"] = _err_usb_texte(e)
                break        # inutile de marteler un device absent
            continue
        if not d:
            continue
        _noter_paquet(d, _ms())
        if verbose:
            print(f"    Drain : {len(d)}B {d[:8].hex()}...")

    if verbose:
        print("  [INIT] Phase 1 terminée, wing en reboot...")
    return True


# `wait_and_init()` n'existe plus : sa logique est dans full_init(), qui décide
# d'abord de l'état de la wing (bootloader / opérationnelle). Ne pas la
# réintroduire : deux chemins d'init concurrents.

# ── Temps de réponse de la wing ──────────────────────────────────────────────
#
# Mesuré à CHAQUE connexion, pas un simple oui/non : une wing qui répond en
# 0,4 ms et une wing qui répond en 337 ms (≈ 800 fois trop lente, lectures
# réussies, interface revendiquée) passaient toutes deux pour « prêtes ».
POLL_LENT_MS = 50.0        # au-delà, la wing est saine mais inexploitable


def mesurer_poll(dev, essais=6, lecture_ms=600):
    """Temps de réponse au polling, en ms (médiane). None si la wing est muette.

    `lecture_ms` est volontairement GÉNÉREUX : on veut mesurer une réponse
    lente, pas la manquer. Un délai trop court la ferait passer pour absente.
    """
    temps = []
    for _ in range(essais):
        t0 = time.perf_counter()
        try:
            dev.write(EP_OUT, POLL_PKT, timeout=TIMEOUT_MS)
        except Exception:
            return None
        d = _read(dev, lecture_ms)
        dt = (time.perf_counter() - t0) * 1000.0
        if d and len(d) >= 96:
            temps.append(dt)
            # ⏱️ On s'arrête dès que le verdict est acquis. Sans ça, mesurer
            # une wing lente coûtait 6 × 663 ms ≈ 4 s AVANT même de tenter
            # quoi que ce soit — le plus gros poste du réveil, pour une
            # conclusion connue au bout de deux relevés.
            if len(temps) >= 2 and min(temps) > POLL_LENT_MS:
                break                    # « lente » : inutile d'insister
            if len(temps) >= 4:
                break                    # « rapide » : 4 × ~1 ms, négligeable
        time.sleep(0.01)
    if len(temps) < 2:
        return None
    temps.sort()
    return temps[len(temps) // 2]


def repond_au_poll(dev, essais=4, mini=96, lecture_ms=200, _t0=None):
    """La wing répond-elle au polling ? C'est LE geste que fera le bridge.

    Deux paquets d'au moins `mini` octets sont exigés : c'est ce qu'attend la
    boucle de polling, et deux valent mieux qu'un pour écarter un résidu de
    tampon. Ne lève jamais.

    `_t0` : 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — même principe que
    dans `attendre_reapparition`/`attendre_disparition` : horodate
    `_REVEIL_DIAG["poll_essais"]` sur la frise partagée de `full_init` si
    fourni, sinon sur un départ local à cet appel. Ne change ni la logique ni
    la valeur de retour.
    """
    t0_diag = _t0 if _t0 is not None else time.perf_counter()
    _REVEIL_DIAG["poll_essais"] = []
    recus = 0
    for _ in range(essais):
        try:
            dev.write(EP_OUT, POLL_PKT, timeout=TIMEOUT_MS)
        except Exception as e:
            # 🔎 DIAGNOSTIC — l'écriture elle-même a échoué, pas la lecture.
            # 🔒 3e élément jamais relu (_trace_reveil ne lit que (t, ok)) —
            # diagnostic interne, pas de clé i18n (voir _ALLOWLIST_J).
            _REVEIL_DIAG["poll_essais"].append((
                round((time.perf_counter() - t0_diag) * 1000.0, 1),
                False, f"write refused: {_err_usb(e)}"))
            return False
        d = _read(dev, lecture_ms)
        ok = bool(d and len(d) >= mini)
        # 🔎 DIAGNOSTIC — chaque tentative, avec ce qui a été REÇU (0 si rien).
        _REVEIL_DIAG["poll_essais"].append((
            round((time.perf_counter() - t0_diag) * 1000.0, 1),
            ok, len(d) if d else 0))
        if ok:
            recus += 1
            if recus >= 2:
                return True
        time.sleep(0.03)
    return False


# Dernière mesure de temps de réponse, pour l'interface (None = pas mesuré).
DERNIER_POLL_MS = {"ms": None}


def _reouvrir(dev):
    """Ferme et rouvre la poignée USB, sans toucher au périphérique.

    ⏱️ Le remède le MOINS CHER : ~0,5 s, contre ~10 s pour un reset de port.
    Il suffit si la lenteur tient à l'état de NOTRE liaison (endpoint, tampon)
    plutôt qu'à celui de la wing.

    Fondé sur une observation : la wing est passée de 1,1 ms à
    619 ms d'une session à la suivante SANS reset, SANS reboot, sans même un
    `Pipe error` — la seule chose qui s'était produite entre les deux, c'est
    la fermeture et la réouverture de la liaison. Ça vaut donc la peine de
    commencer par rejouer ce geste-là avant de sortir l'artillerie.
    """
    _liberer(dev)
    time.sleep(0.3)
    return _open()


def _tenter_reveil(dev):
    """Sort la wing de son état lent SANS toucher au câble. UNE tentative.

    `reset()` envoie un vrai reset de port USB : le périphérique re-énumère
    comme au branchement. La seule différence avec le geste manuel, c'est que
    l'alimentation n'est pas coupée — et on sait que c'est justement la coupure
    qui compte dans certains cas. D'où « tentative ».

    ⚠️ UNE SEULE FOIS, jamais en boucle. La règle établie tient toujours :
    s'acharner sur une wing bloquée l'entretient dans son état. Si ça ne
    suffit pas, on le dit et on rend la main à l'utilisateur.

    Retourne un device utilisable, ou None.
    """
    _msg("journal.init.reveil_debut")
    reset_fait = True
    try:
        dev.reset()
    except Exception as e:
        reset_fait = False
        _msg("journal.init.reset_refuse", err=e)
    _liberer(dev)

    # Si `reset()` échoue (« Entity not found »), la wing n'a PAS bougé : ne pas
    # attendre sa disparition puis sa réapparition (18 s mesurées pour rien,
    # contre 0,04 s quand tout va bien).
    if not reset_fait:
        time.sleep(0.3)          # juste le temps que le système referme
    else:
        # ⚠️ ORDRE OBLIGATOIRE : attendre qu'elle PARTE, puis qu'elle REVIENNE.
        # Sauter la première attente faisait saisir l'ancienne énumération et
        # conclure à tort que le réveil avait échoué (attendre_disparition).
        attendre_disparition(3.0)
        brut, etat_usb = attendre_reapparition(timeout_s=8.0)
        if brut is None:
            _msg("journal.init.pas_reapparue_reset")
            return None
        if etat_usb == "bootloader":
            # Elle repart de zéro, exactement comme à un branchement neuf :
            # on lui renvoie le firmware. UNE fois — voir la règle du cas 2.
            d = _open()
            if d is None:
                return None
            ok = upload_firmware(d, verbose=False)
            wing_etat_materiel._marquer_firmware_envoye()   # compte comme un envoi (anti-martèlement)
            _liberer(d)
            if not ok:
                return None
            # Même règle qu'au cas 2 : ATTENDRE QU'ELLE PARTE d'abord, sinon on
            # retrouve l'ancien bootloader encore présent et on conclut à tort
            # que le firmware n'a pas démarré.
            time.sleep(0.5)
            attendre_disparition(5.0)
            brut, etat_usb = attendre_reapparition(timeout_s=15.0)
            if brut is None or etat_usb == "bootloader":
                _msg("journal.init.fw_pas_redemarre_reset")
                return None

    d = _open()
    if d is None:
        return None
    try:                                   # poignée de main, comme après reboot
        # 400 ms et non 1000 : quand la wing répond, elle répond tout de suite.
        # Ces deux lectures ne coûtaient rien en cas de succès, mais ajoutaient
        # 2 s au réveil dès qu'elle restait silencieuse.
        d.write(EP_OUT, HELLO2_PKT, timeout=TIMEOUT_MS)
        _read(d, 400)
        d.write(EP_OUT, CONFIG2_PKT, timeout=TIMEOUT_MS)
        _read(d, 400)
    except Exception:
        pass
    return d


def _valider_cadence(dev):
    """Dernier verrou avant de rendre la main : la wing répond-elle VITE ?

    🔑 C'est ce qui manquait. `repond_au_poll` ne répond que par oui/non : une
    wing qui met 337 ms le passait haut la main, et l'app démarrait sans un
    mot sur une liaison inexploitable. On mesure, on le dit, et on tente
    quelque chose.

    Ne refuse JAMAIS la connexion : à 2,7 Hz c'est pénible, mais en pleine
    représentation c'est toujours mieux que rien. On rend la wing telle
    qu'elle est, en ayant nommé le problème et le remède.
    """
    ms = mesurer_poll(dev)
    DERNIER_POLL_MS["ms"] = ms
    if ms is None or ms <= POLL_LENT_MS:
        if ms is not None:
            _msg("journal.init.prete", ms=f"{ms:.1f}")
        return dev

    _msg("journal.init.anormalement_lente", ms=f"{ms:.0f}")
    _t0 = time.perf_counter()

    # ── Remède 0 : débloquer les endpoints, SANS rouvrir. ~5 ms. ─────────────
    #
    # 🔬 CE REMÈDE EST AUSSI UNE EXPÉRIENCE, et c'est sa principale raison
    # d'être. Question posée : « est-ce qu'on ne parasite pas la
    # wing en coupant le serveur d'un coup, comme une clé USB arrachée ? »
    #
    # `clear_halt` est un transfert de contrôle : il ne parle QU'À LA WING,
    # sans rien changer côté ordinateur. La réouverture, elle, refait tout
    # côté hôte — et inclut un clear_halt, donc les deux gestes y étaient
    # mélangés et on ne pouvait rien conclure.
    #
    # En les séparant, chaque occurrence tranche :
    #   • ce remède-ci suffit        → l'état fautif est DANS LA WING
    #     (l'hypothèse « on la parasite en coupant » se confirme)
    #   • il faut aller à la réouverture → l'état fautif est CÔTÉ ORDINATEUR
    #     (pile USB de macOS ou libusb ; la wing n'y est pour rien)
    #
    # Le journal écrit lequel a servi. À relire quand plusieurs occurrences
    # se seront accumulées — une seule ne prouvera rien.
    try:
        for ep in (EP_IN, EP_OUT):
            dev.clear_halt(ep)
        ms0 = mesurer_poll(dev)
        if ms0 is not None and ms0 <= POLL_LENT_MS:
            DERNIER_POLL_MS["ms"] = ms0
            _msg("journal.init.revenue_deblocage", ms=f"{ms0:.1f}",
                 s=f"{time.perf_counter() - _t0:.2f}")
            return dev
    except Exception as e:
        _msg("journal.init.deblocage_ko", err=e)

    # ── Remède 1 : rouvrir la liaison. ~0,5 s. ───────────────────────────────
    # Toujours essayé EN PREMIER : s'il suffit, on économise les 10 s du reset
    # de port, et l'utilisateur ne voit pratiquement rien passer.
    leger = _reouvrir(dev)
    if leger is not None:
        ms1 = mesurer_poll(leger)
        if ms1 is not None and ms1 <= POLL_LENT_MS:
            DERNIER_POLL_MS["ms"] = ms1
            _msg("journal.init.revenue_reouverture", ms=f"{ms1:.1f}",
                 s=f"{time.perf_counter() - _t0:.1f}")
            return leger
        dev = leger                    # on poursuit avec la poignée fraîche

    # ── Remède 2 : reset du port USB. ~10 s. ─────────────────────────────────
    neuf = _tenter_reveil(dev)
    if neuf is not None:
        ms2 = mesurer_poll(neuf)
        DERNIER_POLL_MS["ms"] = ms2
        if ms2 is not None and ms2 <= POLL_LENT_MS:
            _msg("journal.init.reveillee", s=f"{time.perf_counter() - _t0:.1f}",
                 ms=f"{ms2:.1f}")
            return neuf
        if ms2 is None:
            # Muette ≠ lente : la poignée ne lit plus rien. On rend `None`…
            #
            # ⚠️⚠️ …ET ON LA LIBÈRE. Le process ne meurt jamais (redémarrage en place) :
            # une poignée non rendue devient un verrou PERMANENT sur l'interface
            # (« Access denied » en boucle, que seul un débranchement levait).
            #
            # 🔑 RÈGLE : tout chemin qui rend None DOIT libérer ce qu'il tient.
            _liberer(neuf)
            _msg("journal.init.encore_muette")
            return None
        _msg("journal.init.toujours_lente", ms=f"{ms2:.0f}")
        dev = neuf
    elif dev is not None:
        # `_tenter_reveil` a échoué APRÈS avoir libéré `dev` : la poignée
        # qu'on tient est périmée. La rendre telle quelle ferait tourner la
        # boucle sur du vide. On préfère l'échec franc et un nouvel essai.
        _msg("journal.init.reveil_sans_effet")
        return None
    _msg("journal.init.lenteur_persiste")
    return dev


def _liberer(dev):
    for f in (lambda: usb.util.release_interface(dev, 0),
              lambda: usb.util.dispose_resources(dev)):
        try:
            f()
        except Exception:
            pass


# Nature du dernier échec d'init. `firmware_bloque` est le SEUL cas où
# réessayer est vraiment impossible sans coupure d'alimentation — une erreur
# transitoire (« Pipe error ») ne doit jamais faire afficher « débranche la
# wing ». `firmware_absent` : on n'a même PAS de firmware à envoyer — la
# réponse est « Paramètres → Configurer le firmware ». Voir full_init, cas 2.
DERNIER_ECHEC = {"firmware_bloque": False, "firmware_absent": False, "raison": "",
                  # `envoi_tente` : au moins un OCTET de firmware a été écrit
                  # sur le fil, que l'envoi ait fini par réussir ou non. Posé
                  # par `upload_firmware()` juste avant sa boucle de chunks —
                  # jamais par les refus qui précèdent (wing déjà applicative,
                  # Hello sans réponse, Hello applicatif, firmware non
                  # configuré) : dans ces cas-là, rien n'est parti. Sert à
                  # `full_init` pour ne pas horodater un envoi qui n'a jamais
                  # eu lieu — voir `_marquer_firmware_envoye`.
                  "envoi_tente": False}


# ── Détection « muette persistante » après un arrachage à chaud (WingUnplugged) ─
#
# Après un débranchement/rebranchement à chaud PENDANT que l'app tourne, la wing
# peut revenir énumérée « operationnelle » (12 Mb/s) mais MUETTE au poll. Seul un
# renvoi du firmware la ranime, en contournant EXPLICITEMENT le garde-fou
# d'upload_firmware (`force_operateur=True`). Écartés, mesurés : renvoi direct
# (refusé par le garde-fou), reset de port (reste muette).
#
# Conduite : RECONNEXION FORCÉE AUTOMATIQUE dès le 1er verdict muette de
# l'épisode (le cas 1 de full_init est exhaustif : 10 polls × 2 poignées,
# jamais un succès partiel). On arme `force_demande`, que la boucle USB — seule
# propriétaire du device — consomme au tour suivant.
#
# ⚠️ Portée : seulement dans un épisode ouvert par WingUnplugged (`episode`), et
# hors auto-démarrage tardif (`attend_rebranchement` faux).
#
# "episode"      : un épisode de reco après WingUnplugged est en cours.
# "force_demande": renvoi firmware forcé EN ATTENTE, exécuté par la boucle USB.
RECO_MUETTE = {"episode": False, "force_demande": False}


def _reco_muette_reset(episode: bool):
    """Repart d'un épisode propre. `episode`=True au déclenchement d'un
    WingUnplugged (nouvel épisode) ; =False sur une connexion réussie."""
    RECO_MUETTE["episode"] = episode
    RECO_MUETTE["force_demande"] = False

# ── Trace du dernier envoi de firmware ───────────────────────────────────────
# Mesurée à chaque envoi — image partie en entier ?, délai de sortie du bus,
# état au retour — pour qu'un « le firmware n'a pas démarré » soit lisible.
DERNIER_ENVOI = {"octets": 0, "depart_s": None, "retour_s": None, "etat": ""}

# ⏱️ La fenêtre des 25 ms qui suit FW_CFG_PKT (voir docs/HARDWARE.md, « La
# fenêtre après FW_CFG_PKT »), mesurée à chaque
# envoi. C'est le seul moment où la wing parle ENCORE après avoir reçu l'ordre
# de démarrer : ce qu'elle dit là, et jusqu'à quand, est directement comparable
# à `d.pcapng`. Rempli par `upload_firmware`, lu par `_trace_envoi`.
#
# 🔑 Ce que `depart_s` ne pouvait pas dire : il part d'APRÈS le drain et d'un
# `sleep(0.5)`, et se mesure par scrutation à 0,1 s. Il annonçait « quittée le
# bus en 0.5 s » à tous les coups — un plancher, pas une mesure. `partie_ms`
# date la sortie du bus à la milliseconde, à l'instant où elle se produit.
_DRAIN = {"paquets": 0, "octets": 0, "premier_ms": None, "dernier_ms": None,
          "signature": "", "partie_ms": None, "partie_par": "",
          "cfg_erreur": "", "cfg_octets": None,
          # 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — chunk_num/chunk_total
          # situent un échec DANS la séquence des ~68 écritures du firmware
          # (« chunk 43/68 ») ; chunk_erreur en donne la nature. Rempli par la
          # boucle d'upload dans `upload_firmware`, lu nulle part encore — le
          # seul but est qu'un prochain échec soit lisible dans `_DRAIN`
          # au lieu du seul « échec après 20 s d'attente ».
          "chunk_num": None, "chunk_total": None, "chunk_erreur": "",
          # 🔎 DIAGNOSTIC — cadence RÉELLE des 68 écritures. `chunk_max_gap_ms` est le
          # signal qui compte : un pic isolé trahit une contention (thread qui vole le
          # GIL entre deux écritures), qu'une moyenne masquerait. Référence MA2 onPC :
          # 0,174 ms/chunk en moyenne, 0,114-0,430 ms de plage.
          "chunks_duree_ms": None, "chunk_max_gap_ms": None,
          "chunk_max_gap_num": None}

# ── 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — entre la sortie du bus et le verdict
# d'attendre_reapparition() ────────────────────────────────────────────────────
#
# Sur 3 essais réels, `_DRAIN` était IDENTIQUE dans 2 échecs et 1 succès : ce qui
# départage se situe après, ici. Ce dict note chaque scrutation du bus pendant
# l'attente (vitesse d'énumération BRUTE — une heuristique, pas une preuve) et
# le sort horodaté de la poignée de main post-reboot (Hello2 / Config2 /
# polling), sur la MÊME frise `_t0` que `DERNIER_ENVOI`. Aucune décision ne le
# lit : il est rempli, rien de plus.
_REVEIL_DIAG = {
    "polls_disparition": [],    # [(t_ms, presente:bool)] — attendre_disparition
    "polls_reapparition": [],   # [(t_ms, presente:bool, vitesse_brute, etat)]
    "open2_ms": None, "open2_echec": "",
    "hello2_envoi_ms": None, "hello2_echec": "",
    "hello2_reponse_ms": None, "hello2_reponse": "",
    "config2_envoi_ms": None, "config2_echec": "",
    "config2_reponse_ms": None, "config2_reponse": "",
    "poll_essais": [],          # [(t_ms, ok:bool, octets)] — repond_au_poll
}

# Ce que MA2 onPC obtient au même endroit — la référence à battre.
DRAIN_REF = {"paquets": 17, "dernier_ms": 25.3, "signature": "0400079101000100",
             "silence_s": 1.287}


# ── L'anti-martèlement persistant (fichier d'état matériel) vit dans
# wing_etat_materiel.py — voir son en-tête.


def _trace_drain() -> str:
    """La fenêtre après FW_CFG, en une phrase comparable à la référence.

    ⚠️ Écrire les DEUX chiffres, le nôtre et celui de MA2 onPC. Une mesure sans
    son étalon ne se relit pas : « 3 paquets » ne veut rien dire dans six mois,
    « 3 paquets (réf. 17) » se juge d'un coup d'œil.
    """
    import wing_i18n
    n, ref = _DRAIN["paquets"], DRAIN_REF["paquets"]
    if not n:
        m = wing_i18n.L("journal.init.trace.muette", ref=ref)
    else:
        m = wing_i18n.L("journal.init.trace.paquets", n=n, o=_DRAIN['octets'],
                        ref=ref, dernier_ms=f"{_DRAIN['dernier_ms']:.1f}",
                        ref_ms=DRAIN_REF['dernier_ms'])
        if _DRAIN["signature"] and not _DRAIN["signature"].startswith(
                DRAIN_REF["signature"][:8]):
            m += wing_i18n.L("journal.init.trace.signature_diff",
                             signature=_DRAIN['signature'])
    if _DRAIN["partie_ms"] is not None:
        m += wing_i18n.L("journal.init.trace.sortie_bus",
                         ms=f"{_DRAIN['partie_ms']:.1f}", par=_DRAIN['partie_par'])
    if _DRAIN["cfg_erreur"]:
        m += wing_i18n.L("journal.init.trace.fwcfg_refuse", err=_DRAIN['cfg_erreur'])
    return m


def _trace_envoi() -> str:
    """Résume le dernier envoi de firmware, pour un message lisible.

    🔎 « Le firmware n'a pas démarré » ne disait rien de plus :
    impossible de savoir si l'image était partie en entier, ni combien de temps
    la wing avait mis à partir et revenir. Ces trois chiffres suffisent à
    trancher entre « transfert incomplet » et « image complète mais refusée ».
    """
    import wing_i18n
    o = DERNIER_ENVOI.get("octets") or 0
    dep = DERNIER_ENVOI.get("depart_s")
    ret = DERNIER_ENVOI.get("retour_s")
    bouts = [wing_i18n.L("journal.init.trace.octets_transmis", o=o)]
    # 🔎 DIAGNOSTIC — cadence réelle des 68 écritures. Référence
    # MA2 onPC : 7,65-28,84 ms au total, 0,114-0,430 ms par chunk en plage.
    cd = _DRAIN.get("chunks_duree_ms")
    if cd is not None:
        gap = _DRAIN.get("chunk_max_gap_ms")
        gap_txt = (wing_i18n.L("journal.init.trace.ecart_max", gap=f"{gap:.2f}",
                               chunk=_DRAIN.get('chunk_max_gap_num'))
                   if gap is not None else "")
        bouts.append(wing_i18n.L("journal.init.trace.chunks_cadence",
                                 ms=f"{cd:.2f}", ecart=gap_txt))
    # ⚠️ NE PAS lire `depart_s` comme une mesure : il démarre après un
    # `sleep(0.5)` et scrute à 0,1 s, donc il vaut 0,5 s dès que la wing part
    # vite — ce qui est le cas normal. Le chiffre qui date vraiment la sortie du
    # bus est `partie_ms`, dans la phrase du drain juste après.
    bouts.append(wing_i18n.L("journal.init.trace.absente_du_bus", s=f"{dep:.1f}")
                 if dep is not None
                 else wing_i18n.L("journal.init.trace.jamais_quitte_bus"))
    led = DERNIER_ENVOI.get("carte_led")
    if led is not None:
        ms = DERNIER_ENVOI.get("led_ms")
        quand = wing_i18n.L("journal.init.trace.a_plus_ms", ms=f"{ms:.1f}") \
                if ms is not None else ""
        bouts.append((wing_i18n.L("journal.init.trace.led_envoyee_o", o=led,
                                  quand=quand) if isinstance(led, int)
                      else wing_i18n.L("journal.init.trace.led_envoyee", led=led,
                                       quand=quand)))
    bouts.append(_trace_drain())
    vue = DERNIER_ENVOI.get("vue_s")
    if vue is not None:
        # ⚠️ C'EST CE CHIFFRE QUI COMPTE : le moment où la wing réapparaît
        #    vraiment sur le bus. Celui d'après n'est que la durée totale de
        #    l'attente, plafonnée par le délai — constante, donc muette.
        bouts.append(wing_i18n.L("journal.init.trace.revue_bus", s=f"{vue:.1f}"))
    if ret is not None:
        bouts.append(wing_i18n.L("journal.init.trace.etat_apres_attente",
                                 s=f"{ret:.1f}", etat=DERNIER_ENVOI.get('etat') or '?'))
    # ⏱️ Le trajet, et surtout : a-t-il bougé ? Un état figé pendant tout le
    # délai dit que continuer d'attendre ne sert à rien — et qu'on peut donc
    # rendre le verdict bien plus tôt.
    tr = DERNIER_ENVOI.get("trajet") or []
    if tr:
        vus = " → ".join(f"{e}@{s:.1f}s" for s, e in tr[:5])
        bouts.append(wing_i18n.L("journal.init.trace.trajet", vus=vus)
                     + ("" if len(tr) > 1
                        else wing_i18n.L("journal.init.trace.jamais_bouge")))
    anti = DERNIER_ENVOI.get("anticipe_s")
    if anti is not None:
        bouts.append(wing_i18n.L("journal.init.trace.verdict_anticipe",
                                 s=f"{anti:.1f}"))
    bouts.append(_trace_reveil())
    return " · ".join(bouts)


def _trace_reveil() -> str:
    """La zone post-reboot (disparition → réapparition → poignée de main),
    en une phrase lisible. 🔎 DIAGNOSTIC (PAS UN CORRECTIF).

    Le détail scrutation par scrutation vit dans `_REVEIL_DIAG` (listes
    `polls_disparition`/`polls_reapparition`/`poll_essais`) — cette fonction
    n'en donne qu'un RÉSUMÉ, sur le même principe que `_trace_drain()` pour
    `_DRAIN`. Motivée par un constat : `_DRAIN` seul rendait 2 échecs et un
    succès réels INDISTINGUABLES ; le fossé se situe dans cette zone-ci.
    """
    import wing_i18n
    d = _REVEIL_DIAG
    bouts = [wing_i18n.L("journal.init.trace.scrutations",
                         disp=len(d['polls_disparition']),
                         reapp=len(d['polls_reapparition']))]
    if d["open2_echec"]:
        bouts.append(wing_i18n.L("journal.init.trace.reouverture_echec",
                                 err=d['open2_echec']))
    elif d["open2_ms"] is not None:
        bouts.append(wing_i18n.L("journal.init.trace.reouverte",
                                 ms=f"{d['open2_ms']:.1f}"))
    if d["hello2_echec"]:
        bouts.append(wing_i18n.L("journal.init.trace.hello2_refuse",
                                 err=d['hello2_echec']))
    elif d["hello2_envoi_ms"] is not None:
        if d["hello2_reponse_ms"] is not None:
            bouts.append(wing_i18n.L(
                "journal.init.trace.hello2_reponse",
                ms=f"{d['hello2_reponse_ms'] - d['hello2_envoi_ms']:.1f}",
                rep=d['hello2_reponse']))
        else:
            bouts.append(wing_i18n.L("journal.init.trace.hello2_jamais_repondu",
                                     ms=f"{d['hello2_envoi_ms']:.1f}"))
    if d["config2_echec"]:
        bouts.append(wing_i18n.L("journal.init.trace.config2_refuse",
                                 err=d['config2_echec']))
    elif d["config2_envoi_ms"] is not None:
        if d["config2_reponse_ms"] is not None:
            bouts.append(wing_i18n.L(
                "journal.init.trace.config2_ack",
                ms=f"{d['config2_reponse_ms'] - d['config2_envoi_ms']:.1f}"))
        else:
            bouts.append(wing_i18n.L("journal.init.trace.config2_jamais_ack",
                                     ms=f"{d['config2_envoi_ms']:.1f}"))
    if d["poll_essais"]:
        n_ok = sum(1 for _, ok, _ in d["poll_essais"] if ok)
        t_premier_ok = next((t for t, ok, _ in d["poll_essais"] if ok), None)
        suite = wing_i18n.L("journal.init.trace.premier_ok",
                            ms=f"{t_premier_ok:.1f}") \
                if t_premier_ok is not None else ""
        bouts.append(wing_i18n.L("journal.init.trace.poll", n_ok=n_ok,
                                 total=len(d['poll_essais']), suite=suite))
    return " · ".join(bouts)


def full_init(verbose=True, force=False, force_operateur=False):
    """Séquence complète d'init. Retourne le device prêt, ou None.

    Décide d'abord À QUI elle parle (bootloader ou wing déjà opérationnelle)
    en lisant la vitesse d'énumération, au lieu de tenter à l'aveugle.

    ⚠️ `force_operateur=True` : reconnexion complète automatique. On SAUTE
    le cas 1 (« wing déjà opérationnelle ») pour aller au cas 2 et renvoyer le
    firmware MÊME à une wing en speed 2 — le seul moyen restant de sortir une wing
    muette-mais-énumérée d'un blocage que ni la boucle ni le reset de port ne
    lèvent. Armé par usb_loop quand `RECO_MUETTE["force_demande"]` l'est (au 1er
    verdict muette d'un épisode WingUnplugged). Le drapeau est transmis à
    `upload_firmware`, qui porte les garde-fous eux-mêmes.
    """
    DERNIER_ECHEC["firmware_bloque"] = False
    brut = _trouver()
    if brut is None:
        _msg("journal.init.wing_absente")
        return None
    etat_usb = etat_wing(brut)
    if verbose:
        print(f"[INIT] Wing trouvée — état : {etat_usb} "
              f"({VITESSE_LIB.get(getattr(brut, 'speed', None), '?')} Mb/s)")

    # ── Cas 1 : la wing tourne DÉJÀ ──────────────────────────────────────────
    # Le firmware reste en RAM tant que la wing est alimentée. Un débranchement
    # la remet en bootloader ; une reprise depuis une VM (Parallels rend le
    # périphérique SANS coupure d'alimentation) ne la remet PAS. Lui renvoyer
    # la séquence bootloader dans cet état ne mène nulle part.
    #
    # ⚠️ `force_operateur` SAUTE ce cas 1 : une reconnexion forcée par
    # l'utilisateur veut justement renvoyer le firmware à une wing en speed 2
    # (muette-mais-énumérée). On tombe alors directement dans le cas 2.
    if etat_usb == "operationnelle" and not force_operateur:
        dev = _open()
        # Sonde généreuse : on SAIT qu'elle devrait répondre, ça vaut le coup
        # d'insister. La version courte (4×200 ms) ratait le cas — vécu le
        # l'app refaisait un upload inutile sur une wing saine.
        if dev is not None and repond_au_poll(dev, essais=10, lecture_ms=400):
            _msg("journal.init.deja_operationnelle")
            wing_etat_materiel.effacer_etat_materiel()      # opérationnelle : plus de blocage
            return _valider_cadence(dev)

        # ── DEUXIÈME CHANCE, avec une poignée NEUVE ──────────────────────────
        # Un simple « Pipe error » faisait conclure « muette » et recharger le
        # firmware (reboot, ~15 s, une fois sur deux une wing lente au retour).
        # Refermer et rouvrir suffit — remède n°1 du réveil.
        if dev is not None:
            _liberer(dev)
        time.sleep(0.3)
        dev = _open()
        if dev is not None and repond_au_poll(dev, essais=10, lecture_ms=400):
            _msg("journal.init.operationnelle_2e_essai")
            wing_etat_materiel.effacer_etat_materiel()
            return _valider_cadence(dev)

        # ⛔⛔ ON S'ARRÊTE ICI. NE JAMAIS LAISSER CE CAS RETOMBER DANS LE CAS 2.
        #
        # 🔴 C'était LA cause d'entrée en bootloader : ce chemin retombait dans le cas 2
        # et envoyait le firmware du bootloader à une wing QUI TOURNE (prouvé par
        # simulation : 67 écritures de 512 o, 34 624 octets d'ARM dans le flux de
        # commandes — la wing en ressort dans son bootloader).
        #
        # Une wing opérationnelle mais muette est un problème CÔTÉ ORDINATEUR
        # (`clear_halt` seul, ou une poignée neuve, la répare) : on ne touche PAS au
        # matériel, on rend la main. `firmware_bloque` reste FAUX : aucun firmware
        # envoyé, donc aucune coupure requise.
        if dev is not None:
            _liberer(dev)
        DERNIER_ECHEC["firmware_bloque"] = False

        # ── RECONNEXION FORCÉE AUTOMATIQUE dès le 1er verdict muette ──────────
        # Portée stricte : épisode de reco ouvert par WingUnplugged (`episode`), hors
        # auto-démarrage tardif (`attend_rebranchement`), et pas déjà en passe forcée.
        # Un full_init hors épisode (ex. le test de fumée) n'arme RIEN. Un seul échec
        # suffit : ce cas 1 vient de faire un test exhaustif (10 polls × 2 poignées
        # neuves, jamais un succès partiel, 0/20). On NE touche PAS l'USB ici : on pose
        # `force_demande`, que la boucle USB consomme au tour suivant.
        import wing_ui as core
        if (RECO_MUETTE["episode"] and not etat.E.AUTO.get("attend_rebranchement")
                and not RECO_MUETTE["force_demande"]):
            RECO_MUETTE["force_demande"] = True
            _msg("journal.init.muette_arrachage")

        _msg("journal.init.operationnelle_muette")
        return None

    # ── Cas 2 : bootloader → envoi du firmware. UN SEUL ESSAI. ───────────────
    #
    # ⛔ D'ABORD : a-t-on un firmware à envoyer ? La wing en bootloader ne peut
    # démarrer QUE si on lui pousse le firmware — et la distribution OSS ne le
    # livre pas. Sans cache ni blob, on s'arrête ici, proprement : on ne touche
    # PAS à la wing (aucun octet), on renvoie vers l'écran de configuration, et
    # on ne pose PAS `firmware_bloque` (rien à débrancher — c'est une config
    # manquante, pas une wing coincée). L'interface lit `firmware_statut()` et
    # affiche le message ; on ne le journalise donc qu'UNE fois par état.
    if not wing_firmware.firmware_configure():
        if not DERNIER_ECHEC.get("firmware_absent"):
            _msg("journal.init.bootloader_fw_absent")
        DERNIER_ECHEC["firmware_absent"] = True
        DERNIER_ECHEC["firmware_bloque"] = False
        return None
    #
    # 🔑 RÈGLE ÉTABLIE PAR L'EXPÉRIENCE — ne pas la contourner :
    # quand un chargement de firmware échoue à démarrer, TOUS les suivants
    # échouent aussi, tant que la wing n'a pas été mise HORS TENSION.
    #
    #   • 6 essais consécutifs sans coupure  → 6 échecs identiques
    #   • coupure de 18 s puis 1 seul essai  → succès en 1,5 s
    #
    # Réessayer n'est donc pas seulement inutile : ça maintient la wing dans un
    # cycle de reboot permanent (LED qui clignotent) et empêche le seul remède
    # qui marche. C'est à l'appelant d'attendre un débranchement réel.
    #
    # ❌ Hypothèse RÉFUTÉE au passage : omettre FW_CFG_PKT ou le drain ne change
    # rien. Testé dans les deux sens, même échec. Ne pas y revenir.
    #
    # ⚠️⚠️ ANTI-MARTÈLEMENT INTER-PROCESS. Si on a DÉJÀ envoyé le
    # firmware il y a quelques secondes et que la wing est ENCORE en bootloader,
    # c'est qu'on la RÉ-ENFONCE — typiquement le process neuf d'un
    # « Réinitialiser » après un build. On refuse, exactement comme le script
    # manuel : un seul envoi par présence sur le bus, la suite attend une vraie
    # coupure. Voir _marquer_firmware_envoye / effacer_etat_materiel.
    if wing_etat_materiel.blocage_connu() and not force:
        DERNIER_ECHEC["firmware_bloque"] = True
        _msg("journal.init.bootloader_deja_tentee")
        return None
    # ⚠️ Même dérogation `and not force` que `blocage_connu()` juste au-dessus :
    # `force=True` vient d'un clic délibéré sur « Connecter la wing », le DERNIER
    # RECOURS garanti quand l'heuristique se trompe. Sans elle, ce deuxième verrou
    # (le cooldown anti-martèlement) retenait encore le clic.
    if wing_etat_materiel._firmware_envoye_recemment() and not force:
        DERNIER_ECHEC["firmware_bloque"] = True
        wing_etat_materiel._marquer_blocage()
        _msg("journal.init.bootloader_fw_deja_envoye")
        return None

    dev = _open()
    if dev is None:
        _msg("journal.init.wing_absente")
        return None
    ok = upload_firmware(dev, verbose=verbose, force_operateur=force_operateur)
    # ⚠️ On n'horodate que si quelque chose est RÉELLEMENT parti (`envoi_tente`) :
    # sinon un bootloader qui n'a reçu aucun octet (Hello sans réponse, Hello
    # applicatif refusé) déclenchait le cooldown, et une reconnexion légitime
    # quelques secondes plus tard échouait sur un « firmware déjà envoyé » fictif.
    if ok or DERNIER_ECHEC.get("envoi_tente"):
        wing_etat_materiel._marquer_firmware_envoye()      # on vient d'envoyer (ou tenté) : on l'horodate

    # ⚠️⚠️ ON NE LIBÈRE PAS LA POIGNÉE ICI — voir la mesure ci-dessous.
    #
    # 🔎 Relevé dans `d.pcapng` (la capture de MA2 onPC, seule
    # implémentation connue qui marche). Après l'End packet :
    #
    #   • le bootloader envoie 17 paquets, 17 408 o, en 25 ms ;
    #   • MA2 onPC les lit tous, puis reste SILENCIEUX 1,29 s ;
    #   • pendant ces 1,29 s il ne ferme RIEN — aucun transfert de contrôle,
    #     aucune libération d'interface. Il garde la poignée ouverte jusqu'à ce
    #     que la wing quitte le bus d'elle-même.
    #
    # Nous, on appelait `_liberer(dev)` ICI : release_interface + close, ~0,5 s
    # après l'End packet, donc EN PLEIN REBOOT de la wing. C'est le seul écart
    # net entre notre séquence et celle de MA2 onPC.
    #
    # ⚠️ HYPOTHÈSE, PAS UNE CAUSE DÉMONTRÉE. Rien ne prouve encore que fermer
    # pendant le reboot empêche le firmware de démarrer. Ce qui est établi,
    # c'est que la référence ne le fait pas et que nous le faisions. Quand on
    # ne comprend pas une panne, se recaler sur l'implémentation qui marche
    # coûte peu et retire une variable.
    #
    # 🔑 On libère donc APRÈS le départ du bus (ou au bout de l'attente, pour
    # ne jamais garder une poignée indéfiniment — règle : tout chemin doit
    # rendre ce qu'il tient).
    if not ok:
        _liberer(dev)
        # ⚠️ Le bootloader n'a même pas répondu au Hello : la wing est dans l'état
        # bloqué. Poser le verrou est ESSENTIEL — sans lui, l'app renvoie le firmware
        # toutes les 3 s et l'entretient dedans (~15 envois en 2 minutes le jour où ce
        # verrou a été rendu conditionnel par erreur).
        DERNIER_ECHEC["firmware_bloque"] = True
        wing_etat_materiel._marquer_blocage()
        # ⚠️ NE PAS écrire « échec de l'envoi » : dans tous les cas connus,
        # rien n'a été envoyé — on s'est arrêté à la poignée de main. Le
        # message d'origine faisait croire à un transfert interrompu, et
        # envoyait donc chercher le problème du mauvais côté.
        _msg("journal.init.fw_pas_envoye",
             raison=(DERNIER_ECHEC.get("raison") or "le bootloader n'a pas répondu"))
        return None

    # ⚠️⚠️ ORDRE OBLIGATOIRE : attendre qu'elle PARTE, puis qu'elle REVIENNE.
    # Juste après l'envoi, l'ANCIENNE énumération (le bootloader, 480 Mb/s) reste
    # visible un moment : la retrouver n'est PAS un échec du firmware. (Même remède
    # que dans `_tenter_reveil` : un remède connu s'applique à TOUS les chemins
    # qui ont le même mal.)
    DERNIER_ENVOI.update(depart_s=None, retour_s=None, etat_usb="")
    _t0 = time.perf_counter()
    time.sleep(0.5)          # laisser le reboot commencer
    parti = attendre_disparition(5.0, _t0=_t0)
    DERNIER_ENVOI["depart_s"] = (time.perf_counter() - _t0) if parti else None
    # La wing est partie (ou l'attente a expiré) : c'est MAINTENANT qu'on rend
    # la liaison, comme MA2 onPC. Jamais avant — cf. le commentaire plus haut.
    _liberer(dev)
    # Généreux à dessein : se tromper coûte un faux « débranche-la », le pire
    # message de cette app. ⚡ Verdict anticipé : un état figé depuis 5 s tranche (le
    # délai de 15 s était consommé en entier à chaque échec, 10/10, pour un état
    # figé depuis +1 s). 5 s et pas 3 : un réveil spontané ~25 s plus tard a été
    # consigné une fois — on garde de la marge.
    brut, etat_usb = attendre_reapparition(timeout_s=15.0, fige_s=5.0, _t0=_t0)
    DERNIER_ENVOI["retour_s"] = time.perf_counter() - _t0
    DERNIER_ENVOI["etat"] = etat_usb or "absente"
    if brut is None:
        DERNIER_ECHEC["firmware_bloque"] = True
        wing_etat_materiel._marquer_blocage()
        _msg("journal.init.fw_pas_reapparue", trace=_trace_envoi())
        return None

    if etat_usb == "bootloader":
        # Elle est bien REVENUE, et toujours en bootloader : cette fois le
        # firmware n'a réellement pas démarré (on a attendu qu'elle parte, donc
        # ce n'est plus l'ancienne énumération).
        #
        # 🐛 l'AUTO-DÉMARRAGE TARDIF est géré EN AVAL, sans bloquer
        # ici : le firmware est en RAM, la wing finit parfois son boot toute
        # seule (speed 3→2) SANS quitter le bus, mais le délai est TROP variable
        # (mesuré de ~7 s à >25 s) pour une fenêtre bloquante dans full_init. On
        # rend donc la main normalement, et c'est `usb_loop` (wing_connexion.py)
        # qui surveille la vitesse pendant « tentatives suspendues » et reprend
        # en cas 1 dès qu'elle repasse applicative. Voir le banc `essai_autoboot.py`.
        DERNIER_ECHEC["firmware_bloque"] = True
        wing_etat_materiel._marquer_blocage()
        # ⚠️ MESSAGE COURT ET ACTIONNABLE. L'ancien criait en
        # capitales et expliquait la théorie. L'utilisateur n'a besoin que du
        # geste. La mesure, elle, part dans le journal juste en dessous : c'est
        # elle qui servira au diagnostic, pas les majuscules.
        _msg("journal.init.bootloader_fw_pas_demarre")
        _msg("journal.init.detail_diag", trace=_trace_envoi())
        return None

    # ⏱️ LA MESURE PART AUSSI QUAND ÇA MARCHE.
    #
    # 🔑 Une mesure qu'on ne prend que sur les échecs ne se compare à RIEN : on
    # accumulerait dix relevés de panne et zéro témoin, et on ne pourrait jamais
    # dire si la fenêtre des 25 ms distingue un démarrage d'un refus — ni même
    # si elle varie. C'est le témoin qui donne sa valeur au relevé d'échec.
    _msg("journal.init.fw_reussi", trace=_trace_envoi())

    # ── Phase 2 : poignée de main post-reboot ────────────────────────────────
    #
    # 🔎 DIAGNOSTIC (PAS UN CORRECTIF) — voir _REVEIL_DIAG en tête
    # de fichier. Chaque étape est horodatée sur la frise `_t0`. Les `except`
    # internes NE FONT QUE noter puis `raise` : le comportement observable
    # (message, libération de la poignée, `return None`) reste entièrement
    # celui du `try/except` englobant, identique à avant cette instrumentation.
    dev2 = _open()
    if dev2 is None:
        import wing_i18n
        _REVEIL_DIAG["open2_echec"] = wing_i18n.L("journal.init.introuvable_apres_reboot")
        _msg("journal.init.introuvable_reboot")
        return None
    _REVEIL_DIAG["open2_ms"] = round((time.perf_counter() - _t0) * 1000.0, 1)
    if verbose:
        print(f"  [INIT] Wing re-énumérée : {dev2.bus}/{dev2.address} — {etat_usb}")
    try:
        try:
            _REVEIL_DIAG["hello2_envoi_ms"] = round(
                (time.perf_counter() - _t0) * 1000.0, 1)
            dev2.write(EP_OUT, HELLO2_PKT, timeout=TIMEOUT_MS)
        except Exception as e:
            _REVEIL_DIAG["hello2_echec"] = _err_usb_texte(e)
            raise
        resp2 = _read(dev2, 1000)
        _REVEIL_DIAG["hello2_reponse_ms"] = (
            round((time.perf_counter() - _t0) * 1000.0, 1) if resp2 else None)
        _REVEIL_DIAG["hello2_reponse"] = resp2.hex() if resp2 else ""
        if CONFIG2_PKT:
            try:
                _REVEIL_DIAG["config2_envoi_ms"] = round(
                    (time.perf_counter() - _t0) * 1000.0, 1)
                dev2.write(EP_OUT, CONFIG2_PKT, timeout=TIMEOUT_MS)
            except Exception as e:
                _REVEIL_DIAG["config2_echec"] = _err_usb_texte(e)
                raise
        ack = _read(dev2, 1000)
        _REVEIL_DIAG["config2_reponse_ms"] = (
            round((time.perf_counter() - _t0) * 1000.0, 1) if ack else None)
        _REVEIL_DIAG["config2_reponse"] = ack.hex() if ack else ""
    except Exception as e:
        _msg("journal.init.handshake_reboot_ko", err=e)
        _liberer(dev2)
        return None
    if verbose:
        print(f"    Hello2 → {resp2.hex() if resp2 else 'timeout'}")
        print(f"    ACK    → {ack.hex() if ack else 'timeout'}")

    # Preuve de vie : le geste réel que fera la boucle de polling.
    if not repond_au_poll(dev2, essais=POLL_ESSAIS, lecture_ms=300, _t0=_t0):
        DERNIER_ECHEC["firmware_bloque"] = True
        wing_etat_materiel._marquer_blocage()
        _msg("journal.init.demarree_muette")
        _msg("journal.init.detail_hello_ack",
             hello=('ok' if resp2 else 'sans réponse'),
             ack=('ok' if ack else 'sans réponse'))
        _msg("journal.init.detail_post_reboot", trace=_trace_reveil())  # 🔎 DIAGNOSTIC
        _liberer(dev2)
        return None

    if verbose:
        print("  [INIT] Wing prête pour le polling !")
    wing_etat_materiel.effacer_etat_materiel()              # firmware démarré : blocage levé
    return _valider_cadence(dev2)


if __name__ == "__main__":
    dev = full_init(verbose=True)
    if dev:
        print("\n✓ Wing initialisée et prête !")
    else:
        print("\n✗ Échec init")


# ── Noms DÉMÉNAGÉS (audit du 25/09/2026, D3) : toute lecture ou écriture lève,
# pour qu'un test qui les patcherait encore ici ne patche pas dans le vide.
import wing_demenagement
wing_demenagement.garder(__name__, {
    **{n: f"wing_firmware.{n}" for n in (
        "FW_BUNDLE", "FW_LONGUEUR", "FW_SHA256", "FW_BIN", "_FW_SHA_CACHE",
        "chemin_cache_firmware", "resoudre_firmware", "firmware_configure",
        "firmware_statut", "enregistrer_firmware")},
    **{n: f"wing_etat_materiel.{n}" for n in (
        "ETAT_FICHIER", "FW_REHAMMER_S", "BLOCAGE_PEREMPTION_DEMARRAGE_S",
        "_ecrire_etat_fichier", "_marquer_firmware_envoye", "_marquer_blocage",
        "_adresse_courante", "blocage_connu", "_firmware_envoye_recemment",
        "effacer_etat_materiel", "reconcilier_blocage_au_demarrage")},
})
