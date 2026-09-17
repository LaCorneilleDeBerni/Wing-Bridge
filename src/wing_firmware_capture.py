#!/usr/bin/env python3
"""
wing_firmware_capture.py — capture intégrée du firmware via USBPcap
=====================================================================
Windows x64 uniquement — PAS Windows ARM (⚠️ garde `sys.platform` partout —
importé sans erreur sur macOS, où toute fonction publique répond juste
« indisponible »).

⚠️ Windows ARM est exclu, pas par prudence : les deux briques dont dépend la
capture n'existent qu'en x64. USBPcap ne fournit qu'un pilote-filtre noyau
x86/x64 (aucun binaire ARM64 signé — il ne se chargerait pas sur un noyau
ARM64) ; grandMA2 onPC — LA source du firmware ici — n'est distribué qu'en x64
par MA Lighting, et son pilote de wing (`OnPCWingDeviceClass`) est lui aussi un
pilote noyau. Sur Windows ARM, `capture_supportee()` répond faux : l'UI masque
entièrement la carte de capture intégrée, il reste le repli manuel (capture sur
un PC Windows x64, puis import du `.bin`).

Le firmware appartient à MA Lighting (voir docs/HARDWARE.md, « D'où vient
wing_firmware.bin ») : cette distribution ne le contient pas. Jusqu'à ce
chantier, l'utilisateur devait installer Wireshark à la main, lancer une
capture, la sauver en .pcapng, puis l'importer (toujours possible — repli
manuel, voir _post_firmware_import_capture). Ce module fait tout ça pour lui,
en une seule action :

    1. installer USBPcap (le composant de capture, vendoré dans
       src/vendor/usbpcap/) SEULEMENT s'il n'est pas déjà là ;
    2. capturer le trafic USB pendant que grandMA2 onPC pousse le firmware à
       la wing ;
    3. extraire et vérifier le blob (wing_firmware_extract, déjà utilisé par
       l'import manuel — même garantie sha256) ;
    4. RETIRER USBPcap si c'est CE module qui l'a installé — jamais s'il
       était déjà présent avant (`usbpcap_installe_par_nous`, persisté dans
       le même fichier que l'anti-martèlement firmware, wing_etat_materiel.ETAT_FICHIER
       / wing_hw_state.json — même mécanisme lire-fusionner-écrire que
       `wing_etat_materiel._marquer_blocage`).

⚠️ EXIGENCE PRODUIT : RIEN ne doit rester sur la machine si USBPcap
n'y était pas déjà. Le flag `usbpcap_installe_par_nous` existe pour ça — et
UNIQUEMENT pour ça : ne jamais désinstaller ce qu'on n'a pas soi-même posé.

── Une seule élévation, pas deux ──────────────────────────────────────────
Installer un pilote ET capturer avec USBPcapCMD.exe demandent TOUS LES DEUX
les droits admin (vérifié dans le source amont, USBPcapCMD/cmd.c :
IsElevated(), et le pilote lui-même ne s'ouvre qu'élevé). Si on élevait deux
fois (une fois pour l'install, une fois pour la capture), l'utilisateur verrait
DEUX invites UAC pour un seul clic. On élève donc UNE FOIS un unique script
PowerShell (wing_firmware_capture_eleve.ps1) qui enchaîne installation →
capture → désinstallation tout seul, pendant que CE module (non élevé) pilote
sa progression en pollant un fichier de statut JSON et fait lui-même
l'extraction (wing_firmware_extract est pur Python : pas besoin d'élévation
pour LIRE un .pcap sur disque, seulement pour le PRODUIRE).

── Pourquoi capturer sur TOUS les root hubs USBPcap ────────────────────────
Le script élevé ne sait pas d'avance sur quel root hub la wing va apparaître
— elle peut être débranchée au moment où l'utilisateur clique. Identifier le
bon hub à l'avance demanderait de faire correspondre un port USB physique à
un index `USBPcapN`, ce que `USBPcapCMD.exe --extcap-config` ne permet PAS de
façon fiable (vérifié en lisant USBPcapCMD/enum.c : la description qu'il
imprime par périphérique vient de `CM_DRP_DEVICEDESC`, une chaîne humaine du
Gestionnaire de périphériques — PAS le VID/PID, qui n'apparaît nulle part dans
cette sortie). Capturer sur CHAQUE root hub en parallèle est donc le choix
robuste, pas un repli dégradé — quelques process USBPcapCMD.exe pour ~45 s
coûte peu. Voir docs/WINDOWS.md, « Capture firmware intégrée ».
"""

import etat
import ctypes
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import wing_firmware
import wing_etat_materiel

USBPCAP_VERSION = "1.5.4.0"
USBPCAP_SHA256 = "87a7edf9bbbcf07b5f4373d9a192a6770d2ff3add7aa1e276e82e38582ccb622"

# Même repli que wing_init._DIR : ressources à côté du script, ou dans
# sys._MEIPASS en app figée (PyInstaller --add-data, voir build_windows.ps1).
if getattr(sys, "frozen", False):
    _DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    _DIR = os.path.dirname(os.path.abspath(__file__))

INSTALLER      = os.path.join(_DIR, "vendor", "usbpcap",
                              f"USBPcapSetup-{USBPCAP_VERSION}.exe")
SCRIPT_CAPTURE = os.path.join(_DIR, "wing_firmware_capture_eleve.ps1")
SCRIPT_RETIRER = os.path.join(_DIR, "wing_firmware_retirer_eleve.ps1")

# 🔒 Empreintes des deux scripts lancés ÉLEVÉS — vérifiées par l'amorce
# (`_amorce_verifiee`) sur la COPIE qu'elle exécute. ⚠️ À mettre à jour à
# chaque modification d'un .ps1 : le contrôle test_amorce_elevee_verifiee
# (smoke_securite.py) échoue tant qu'elles ne correspondent pas aux fichiers.
SCRIPT_CAPTURE_SHA256 = "33f3bf9ef5dc3cd1a85ddd0a9d1976a1ec9a5b6461d2b8e7867f54a55230fc0c"
SCRIPT_RETIRER_SHA256 = "101453a274f155e55096902244ee129ed97f9335844e86dc44c2cf4b559d684a"

# ── État de progression, lu par /api/status à CHAQUE poll (400 ms, voir
# ui/init.js) — c'est ce qui permet à l'interface d'afficher l'assistant pas à
# pas EN DIRECT pendant l'opération (installation USBPcap comprise, ~1-3 min).
#
# `phase` (1→7) + `phase_titre` alimentent la barre d'étapes de l'interface :
#   1. Lance grandMA2 onPC sur ce PC
#   2. Débranche ta wing
#   3. Préparation de l'enregistrement
#   4. Branche ta wing — puis ne la débranche plus
#   5. Ferme grandMA2 onPC            ← il TIENT la wing tant qu'il tourne
#   6. Débranche ta wing              ← bus au calme → retrait PROPRE de USBPcap
#   7. Rebranche ta wing → Wing connectée
# `chemin` : où le firmware a atterri, affiché à la fin.
#
# ⚠️ `usb_exclusif` : vrai UNIQUEMENT pendant les phases 3-4 + le nettoyage
# USBPcap (le seul moment où l'app doit LÂCHER le bus — voir wing_connexion.
# usb_loop). Les phases 1-2 (pré-vols) et 5-7 (fermeture MA2, rebranchement,
# attente de connexion) ont au contraire BESOIN que usb_loop tourne pour que
# Wing Bridge reprenne la wing.
PHASES_TOTAL = 7
CAPTURE_STATE = {"actif": False, "etape": "", "ok": None, "raison": None,
                 "note": None, "besoin_redemarrage": False, "annule": False,
                 "phase": 0, "phase_total": PHASES_TOTAL, "phase_titre": "",
                 "chemin": None, "usb_exclusif": False}

# ── Annulation « à tout moment » ─────────────────────────────────────────────
# Bouton « Annuler la démarche » de l'assistant (dispo tout du long). On NE TUE
# RIEN de force : on pose ce drapeau, que la boucle de capture et `_attendre`
# surveillent. Si l'utilitaire élevé (USBPcap) tourne déjà, la boucle lui donne
# le feu vert de désinstallation (stop.flag + cleanup.flag) et attend qu'il
# confirme AVANT de rendre la main — USBPcap ne reste jamais installé derrière
# une annulation. Un `threading.Event` : posé depuis le thread HTTP, lu depuis
# le thread de capture.
_ANNULER = threading.Event()

# Combien de temps l'assistant attend une action de l'utilisateur avant
# d'abandonner PROPREMENT (message actionnable, reprise en recliquant).
TIMEOUT_ATTENTE_MA2   = 300.0    # « lance grandMA2 onPC »
TIMEOUT_DEBRANCHEMENT = 120.0    # « débranche ta wing »
TIMEOUT_FERMER_MA2    = 180.0    # « ferme grandMA2 onPC »
TIMEOUT_REBRANCHER    = 120.0    # « rebranche ta wing »
TIMEOUT_CONNEXION     = 60.0     # attente de « Wing connectée » par usb_loop

GMA2_ONPC_IMAGE = "gma2onpc.exe"   # process de grandMA2 onPC (vérifié en réel)


def _windows_arm() -> bool:
    """Windows tourne-t-il sur un hôte ARM64 ?

    On lit l'architecture RÉELLE de l'OS, pas celle du process : un Python x64
    émulé sur Windows ARM verrait `platform.machine()` == 'AMD64'. Windows pose
    `PROCESSOR_ARCHITEW6432` = 'ARM64' pour tout process x86/x64 sous émulation ;
    `PROCESSOR_ARCHITECTURE` sert de repli pour un process nativement ARM64.
    """
    if not sys.platform.startswith("win"):
        return False
    arch = (os.environ.get("PROCESSOR_ARCHITEW6432")
            or os.environ.get("PROCESSOR_ARCHITECTURE") or "")
    return "ARM" in arch.upper()


def capture_supportee() -> bool:
    """La capture intégrée peut-elle tourner sur cette machine ?

    Windows x64 seulement — voir l'en-tête du module pour le pourquoi (USBPcap
    et grandMA2 onPC n'existent qu'en x64). L'UI s'en sert pour masquer
    entièrement la carte de capture (comme pour `s.capture == null` hors
    Windows), pas juste la désactiver.
    """
    return sys.platform.startswith("win") and not _windows_arm()


# ── Délai minimum de LISIBILITÉ d'une étape ───────────────────────────────────
# L'auto-détection franchit une étape dès que sa condition est vraie — parfois
# INSTANTANÉMENT : wing déjà débranchée, grandMA2 onPC déjà lancé. L'auteur a
# raté « débranche ta wing » (étape 2) parce qu'elle l'était déjà et l'étape a
# défilé en une fraction de seconde. Chaque étape reste donc affichée AU MOINS
# `_PHASE_MIN_S` (ou la valeur `tenir=` passée à `_phase()`) avant que la
# suivante ne la remplace : l'instruction ne doit jamais « clignoter ». Le
# délai n'est ajouté QUE si l'étape précédente a duré moins que ça — une étape
# où l'assistant attend vraiment l'utilisateur (`_attendre`) est déjà au-dessus.
#
# ⚠️ Étape 2 (« Débranche ta wing ») : 10 s. 2,5 s ne suffisaient pas quand la
# wing était déjà débranchée (retour de l'auteur) — c'est le geste
# le plus facile à manquer, et le rater fait échouer toute la capture
# (grandMA2 onPC ne repousse le firmware qu'à un BRANCHEMENT).
_PHASE_MIN_S = 2.5
_PHASE_TENIR = {2: 10.0}       # surcharges par numéro d'étape
_phase_horodate = [0.0]        # time.monotonic() du dernier _phase() ; liste = mutable
_phase_min = [_PHASE_MIN_S]    # combien de temps tenir l'étape EN COURS avant la suivante


def _reset_state():
    CAPTURE_STATE.update({"actif": False, "etape": "", "ok": None,
                          "raison": None, "note": None,
                          "besoin_redemarrage": False, "annule": False,
                          "phase": 0, "phase_total": PHASES_TOTAL,
                          "phase_titre": "", "chemin": None,
                          "usb_exclusif": False})
    _phase_horodate[0] = 0.0   # une 2e capture dans le même process repart propre
    _phase_min[0] = _PHASE_MIN_S
    _ANNULER.clear()           # une annulation ne déborde pas sur la capture suivante


def _L(cle, **params):
    """Résout une clé i18n dans la LANGUE courante — surfaces du wizard
    (étapes, raisons d'échec affichées). Le journal disque reste anglais
    via wing_reglages._log_to_file."""
    import wing_i18n
    return wing_i18n.L(cle, **params)


def _etape(cle_ou_texte, **params):
    """`cle_ou_texte` : une clé `firmware.*` (résolue dans la LANGUE courante
    pour le wizard) ou un texte nu (statut brut du script PowerShell élevé)."""
    if isinstance(cle_ou_texte, str) and cle_ou_texte.startswith("firmware."):
        import wing_i18n
        CAPTURE_STATE["etape"] = wing_i18n.L(cle_ou_texte, **params)
    else:
        CAPTURE_STATE["etape"] = cle_ou_texte


def _log(cle_ou_texte, **params):
    """Trace dans le journal du serveur — pour avoir une CHRONOLOGIE de la
    capture (chaque étape horodatée), le seul moyen de diagnostiquer après coup
    un échec « aucun transfert détecté » sans être devant l'écran.

    `cle_ou_texte` : une clé `journal.fw.*` (+ params) ou un texte nu."""
    try:
        import wing_reglages
        wing_reglages.log(cle_ou_texte, **params)
    except Exception:
        pass


def _phase(n, titre, etape=None, **params):
    # Tenir l'étape PRÉCÉDENTE à l'écran le temps qu'elle soit lue (_phase_min,
    # posé par l'appel _phase() précédent) — sauf pour la toute première
    # (_phase_horodate encore à 0). Interrompu net par une annulation.
    if _phase_horodate[0]:
        reste = _phase_min[0] - (time.monotonic() - _phase_horodate[0])
        while reste > 0 and not _ANNULER.is_set():
            time.sleep(min(reste, 0.25))
            reste = _phase_min[0] - (time.monotonic() - _phase_horodate[0])
    import wing_i18n
    CAPTURE_STATE["phase"] = n
    CAPTURE_STATE["phase_titre"] = wing_i18n.L(titre, **params)
    if etape is not None:
        CAPTURE_STATE["etape"] = wing_i18n.L(etape, **params)
    _phase_horodate[0] = time.monotonic()
    _phase_min[0] = _PHASE_TENIR.get(n, _PHASE_MIN_S)
    _log("journal.fw.capture_phase", n=n, total=PHASES_TOTAL,
         titre=wing_i18n.L_en(titre, **params))


def _archiver_diagnostic(run_dir: Path):
    """Copie les .pcap + le statut d'une capture RATÉE à côté des profils.

    Le dossier de travail (`tempfile.mkdtemp`) est supprimé aussitôt la
    fonction finie : sans cette copie, on ne peut jamais savoir si le .pcap
    était vide (filtre pas actif), plein mais sans le Hello (mauvaise
    interface / device manqué), ou tronqué (fenêtre trop courte). Écrit
    seulement en cas d'échec — sur succès le blob suffit.
    """
    try:
        import wing_init
        base = Path(wing_firmware.chemin_cache_firmware()).parent
    except Exception:
        base = Path(tempfile.gettempdir())
    dest = base / ("capture_debug_" + time.strftime("%Y%m%d_%H%M%S"))
    try:
        dest.mkdir(parents=True, exist_ok=True)
    except OSError:
        return
    tailles = []
    for f in sorted(run_dir.glob("*")):
        if not f.is_file():
            continue
        try:
            shutil.copy2(f, dest / f.name)
            if f.suffix == ".pcap":
                tailles.append(f"{f.name}={f.stat().st_size} o")
        except OSError:
            pass
    _log("journal.fw.capture_diag_conserve", dest=dest,
         tailles=(", ".join(tailles) if tailles else _L("firmware.aucun_pcap")))


def _attendre(cond, timeout_s: float, intervalle: float = 1.0) -> bool:
    """Sonde `cond` jusqu'à ce qu'elle rende vrai, ou expiration. Rend bool.

    Sert aux étapes 1 et 2 de l'assistant : on laisse l'utilisateur agir
    (lancer grandMA2 onPC, débrancher la wing) et la détection fait avancer
    l'étape toute seule dès que c'est fait.

    Rend `False` IMMÉDIATEMENT si l'utilisateur a demandé l'annulation
    (`_ANNULER`) : l'appelant vérifie alors `_ANNULER` et prend le chemin
    d'arrêt propre plutôt que le message d'échec d'un timeout.
    """
    fin = time.time() + timeout_s
    while time.time() < fin:
        if _ANNULER.is_set():
            return False
        try:
            if cond():
                return True
        except Exception:
            pass
        time.sleep(intervalle)
    return False


def annuler_capture() -> dict:
    """Demande l'arrêt PROPRE de la capture en cours (bouton « Annuler la
    démarche »). Idempotent, ne tue rien de force.

    Pose `_ANNULER` : `_attendre` et la boucle de `capturer_firmware` le
    surveillent. Si l'utilitaire élevé tourne déjà, la boucle lui envoie
    stop.flag + cleanup.flag et attend sa confirmation — USBPcap est retiré
    avant que la démarche ne se termine.
    """
    if not CAPTURE_STATE["actif"]:
        return {"ok": True, "note": "aucune capture en cours"}
    _ANNULER.set()
    _etape("firmware.etape.annulation")
    _log("journal.fw.capture_annul_demande")
    return {"ok": True, "annulation": True}


# ══ DÉTECTIONS QUI DÉBLOQUENT LES ÉTAPES ════════════════════════════════
def gma2_onpc_lance() -> bool:
    """grandMA2 onPC (gma2onpc.exe) tourne-t-il sur cette machine ?

    Même principe « à chaud » que wing_ma3.ma3_reachable sous Windows : on
    ré-interroge la liste des process à chaque appel, aucun cache de PID.
    `tasklist` est présent sur tout Windows — pas de dépendance psutil, qui
    romprait la contrainte « distribuable sans l'environnement de build »
    (GUIDE_PROJET.md).
    """
    if not sys.platform.startswith("win"):
        return False
    no_window = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        r = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {GMA2_ONPC_IMAGE}", "/NH"],
            capture_output=True, text=True, timeout=5.0,
            errors="replace", creationflags=no_window)
        return GMA2_ONPC_IMAGE.lower() in (r.stdout or "").lower()
    except Exception:
        return False


def wing_sur_bus() -> bool:
    """La wing est-elle présente sur le bus USB ? (lecture seule, sans revendication)

    Réutilise wing_init._trouver() — EXACTEMENT le primitif que usb_loop et la
    scrutation passive de vitesse (#220) emploient déjà : une énumération
    libusb en lecture, aucune poignée ouverte. Pas de conflit de concurrence
    avec la boucle USB (cf. docs/WINDOWS.md, « scrutation passive,
    non bloquante »). Pendant une capture il n'y a de toute façon pas de
    firmware en cache, donc l'app ne tient pas la wing.
    """
    try:
        import wing_init
        return wing_init._trouver() is not None
    except Exception:
        return False

# ══ DÉTECTION ════════════════════════════════════════════════════════════
def usbpcap_present() -> bool:
    """USBPcapCMD.exe est-il utilisable MAINTENANT (avant qu'on y touche) ?

    ⚠️ Vérifie la présence du DOSSIER d'installation (USBPcapCMD.exe), pas le
    service (`sc query`). Testé en réel : après une
    désinstallation (même « réussie », code 0), le service USBPcap reste
    visible dans `sc query` — RUNNING — jusqu'au prochain redémarrage
    (Windows ne peut pas décharger à chaud un pilote-filtre de root hub
    activement en service ; il pose juste `DeleteFlag=1` dans le registre et
    finit au reboot). Se fier à `sc query` ferait donc croire « déjà présent »
    juste après notre propre désinstallation, alors que USBPcapCMD.exe —
    ce dont on a RÉELLEMENT besoin — a bien disparu. Le dossier est le seul
    signal qui reflète ce qu'on peut effectivement exécuter.
    """
    if not sys.platform.startswith("win"):
        return False
    for base in (os.environ.get("ProgramFiles"),
                os.environ.get("ProgramFiles(x86)")):
        if base and os.path.exists(os.path.join(base, "USBPcap", "USBPcapCMD.exe")):
            return True
    return False


# ══ FLAG PERSISTANT « installé par nous » ═══════════════════════════════
#
# Même fichier, même mécanisme lire-fusionner-écrire que
# wing_etat_materiel._marquer_blocage() / blocage_connu() — un seul fichier d'état
# matériel (wing_hw_state.json), pas un deuxième à tenir cohérent.
def _lire_etat_installe() -> bool:
    import wing_init
    if wing_etat_materiel.ETAT_FICHIER is None or not wing_etat_materiel.ETAT_FICHIER.exists():
        return False
    try:
        d = json.loads(wing_etat_materiel.ETAT_FICHIER.read_text(encoding="utf-8"))
        return bool(d.get("usbpcap_installe_par_nous"))
    except Exception:
        return False


def _doit_garder_flag_installe(installed_by_us: bool, uninstall_ok) -> bool:
    """Le flag persistant doit-il rester VRAI après une capture ?

    VRAI seulement si on a installé ET que le nettoyage n'a PAS confirmé sa
    réussite (`uninstall_ok` vaut `None` — jamais tenté/tronqué — ou
    `False`) : c'est exactement (et seulement) le cas où le bouton de secours
    « Retirer le composant de capture » doit apparaître. Fonction PURE, sans
    effet de bord — testée isolément par le smoke test (`test_firmware_capture`,
    smoke_firmware.py) : c'est la garantie « on ne désinstalle jamais ce qu'on
    n'a pas soi-même posé », au cœur de l'exigence produit de ce module.
    """
    return bool(installed_by_us) and uninstall_ok is not True


def _garder_flag_verifie(installed_by_us, uninstall_ok) -> bool:
    """`_doit_garder_flag_installe` + VÉRITÉ TERRAIN.

    Le statut du script élevé peut dire « pas retiré » à tort : le handle de
    `ShellExecuteExW(runas)` s'est révélé peu fiable (mort signalée avant la
    fin du nettoyage → faux avertissement). Si `USBPcapCMD.exe`
    n'est PLUS là, USBPcap est bien parti, point — on n'affiche pas
    d'avertissement ni de bouton de secours pour rien.
    """
    if not _doit_garder_flag_installe(installed_by_us, uninstall_ok):
        return False
    if usbpcap_present():
        return True
    _log("journal.fw.capture_usbpcap_parti")
    return False


def _ecrire_etat_installe(valeur: bool):
    import wing_init
    if wing_etat_materiel.ETAT_FICHIER is None:
        return
    try:
        d = {}
        if wing_etat_materiel.ETAT_FICHIER.exists():
            try:
                d = json.loads(wing_etat_materiel.ETAT_FICHIER.read_text(encoding="utf-8"))
            except Exception:
                d = {}
        d["usbpcap_installe_par_nous"] = bool(valeur)
        # Écriture ATOMIQUE, partagée avec wing_init.py (même fichier,
        # même règle — voir _ecrire_etat_fichier()).
        wing_etat_materiel._ecrire_etat_fichier(d)
    except Exception:
        pass


# ══ ÉLÉVATION — ShellExecuteExW verb=runas, UNE fois ════════════════════
class _SHELLEXECUTEINFOW(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_ulong),
        ("fMask", ctypes.c_ulong),
        ("hwnd", ctypes.c_void_p),
        ("lpVerb", ctypes.c_wchar_p),
        ("lpFile", ctypes.c_wchar_p),
        ("lpParameters", ctypes.c_wchar_p),
        ("lpDirectory", ctypes.c_wchar_p),
        ("nShow", ctypes.c_int),
        ("hInstApp", ctypes.c_void_p),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", ctypes.c_wchar_p),
        ("hkeyClass", ctypes.c_void_p),
        ("dwHotKey", ctypes.c_ulong),
        ("hIconOrMonitor", ctypes.c_void_p),
        ("hProcess", ctypes.c_void_p),
    ]


_SEE_MASK_NOCLOSEPROCESS = 0x00000040
_SW_HIDE = 0
_WAIT_TIMEOUT = 0x102


# ══ AMORCE ÉLEVÉE VÉRIFIÉE (audit du 25/09/2026) ══════════════════════════
#
# 🔴 Avant : l'empreinte de l'installeur était vérifiée ICI (process non
# élevé), puis `powershell -File <script du dossier de l'app>` s'exécutait
# ÉLEVÉ et lançait l'installeur ORIGINAL. Script et installeur vivent dans un
# dossier modifiable par l'utilisateur, et l'invite UAC n'affiche que
# « Windows PowerShell » (signé Microsoft) : un programme du même compte
# pouvait remplacer l'un ou l'autre entre la vérification et l'exécution, et
# obtenir les droits administrateur sur un clic que l'utilisateur croyait
# légitime.
#
# Après : le point d'entrée élevé n'est plus un FICHIER. C'est une amorce
# courte, passée en `-EncodedCommand` (donc dans la ligne de commande que CE
# process construit), qui :
#   1. crée `%ProgramData%\WingBridge-<guid>` AVEC son ACL en une seule
#      opération (`Directory.CreateDirectory(chemin, DirectorySecurity)`) :
#      Administrateurs + SYSTEM seulement, sans héritage. Nom imprévisible,
#      aucune fenêtre où un non-admin pourrait y déposer quoi que ce soit ;
#   2. y COPIE le script (et l'installeur), puis vérifie Get-FileHash sur la
#      COPIE contre les empreintes figées dans ce fichier ;
#   3. n'exécute QUE la copie, puis efface le dossier.
# Un écart d'empreinte écrit `termine` + `erreur` dans le fichier de statut
# et n'exécute rien.
#
# ⚠️ Ce qui N'EST PAS couvert : un programme qui modifie l'APP elle-même
# (l'exécutable Python) avant son lancement — il changerait aussi les
# empreintes attendues. Le dossier de l'app est la frontière de confiance.
# ⚠️ Jamais exécuté sur une vraie machine Windows depuis ce changement :
# vérifié par lecture et par le contrôle test_amorce_elevee_verifiee
# (structure de l'amorce décodée), PAS par une exécution réelle.

_AMORCE = r"""
$ErrorActionPreference = 'Stop'
$statut = __STATUT__
$d = $null
# ⚠️ DÉCOUVERT EN RÉEL (test Windows du 26/09/2026) : $statut vit dans un
# dossier créé par Python NON élevé (tempfile.mkdtemp) ; un fichier que CE
# process ÉLEVÉ y écrit hérite d'un ACL qui refuse la LECTURE au process non
# élevé qui doit le relire (PermissionError systématique). Le correctif vivait
# seulement dans les scripts eux-mêmes (capture : $WorkDir ; retrait, ajouté
# après coup) — mais Stop-Amorce peut écrire AVANT qu'aucun des deux ne
# tourne (empreinte inattendue, dossier %ProgramData% déjà présent…), et ce
# message-là restait alors invisible côté Python (juste un timeout, aucune
# raison). Corrigé ICI, avant toute autre chose : que l'amorce réussisse ou
# échoue, le fichier de statut reste toujours lisible par l'appelant.
try {
    $wd = Split-Path -Path $statut -Parent
    $lecteur = $null
    try {
        $lecteur = (Get-Acl -LiteralPath $wd).GetOwner(
            [System.Security.Principal.SecurityIdentifier]).Value
    } catch { }
    if (-not $lecteur) {
        $lecteur = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    }
    icacls $wd /grant "*${lecteur}:(OI)(CI)RX" /T | Out-Null
} catch { }
function Stop-Amorce([string]$m) {
    try {
        $o = @{ etape = 'amorce'; termine = $true; erreur = $m;
                uninstall_ok = $false; uninstall_error = $m } | ConvertTo-Json -Compress
        $t = $statut + '.tmp'
        [System.IO.File]::WriteAllText($t, $o, (New-Object System.Text.UTF8Encoding $false))
        Move-Item -LiteralPath $t -Destination $statut -Force
    } catch { }
    if ($d) { Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue }
    exit 3
}
try {
    $d = Join-Path $env:ProgramData ('WingBridge-' + [guid]::NewGuid().ToString('N'))
    if (Test-Path -LiteralPath $d) { $x = $d; $d = $null; Stop-Amorce ('dossier deja present : ' + $x) }
    $sec = New-Object System.Security.AccessControl.DirectorySecurity
    $sec.SetAccessRuleProtection($true, $false)
    foreach ($sid in @('S-1-5-32-544', 'S-1-5-18')) {
        $id = New-Object System.Security.Principal.SecurityIdentifier $sid
        $sec.AddAccessRule((New-Object System.Security.AccessControl.FileSystemAccessRule(
            $id, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow')))
    }
    [void][System.IO.Directory]::CreateDirectory($d, $sec)
    # ⚠️ Liste construite par Add() : `@(@('a','b','c'))` avec UN SEUL élément
    # est APLATI par PowerShell en 3 chaînes — le script de retrait (un seul
    # fichier à copier) aurait itéré sur des caractères.
    $copies = New-Object System.Collections.ArrayList
__FICHIERS__
    foreach ($f in $copies) {
        $dst = Join-Path $d $f[1]
        Copy-Item -LiteralPath $f[0] -Destination $dst
        $h = (Get-FileHash -LiteralPath $dst -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($h -ne $f[2]) { Stop-Amorce ('empreinte inattendue pour ' + $f[1] + ' : ' + $h) }
    }
    $p = __PARAMS__
    & (Join-Path $d 'script.ps1') @p
} catch {
    Stop-Amorce $_.Exception.Message
}
if ($d) { Remove-Item -LiteralPath $d -Recurse -Force -ErrorAction SilentlyContinue }
"""


def _ps_litteral(v) -> str:
    """Littéral PowerShell entre apostrophes (' doublée) — aucune
    interpolation possible, quel que soit le chemin."""
    return "'" + str(v).replace("'", "''") + "'"


def _amorce_verifiee(script_src, script_sha, params: dict, status_file,
                     fichiers: dict = None) -> str:
    """Texte de l'amorce élevée. `params` : paramètres nommés du script ;
    `fichiers` : {nom_du_paramètre: (chemin_original, sha256)} — chacun est
    copié puis vérifié, et le paramètre reçoit le chemin de la COPIE."""
    copies = [(str(script_src), "script.ps1", script_sha.lower())]
    p = {k: _ps_litteral(v) for k, v in params.items()}
    for nom, (src, sha) in (fichiers or {}).items():
        dst = f"{nom}{Path(str(src)).suffix}"
        copies.append((str(src), dst, sha.lower()))
        p[nom] = f"(Join-Path $d {_ps_litteral(dst)})"
    liste = "\n".join("    [void]$copies.Add(@(" + ", ".join(_ps_litteral(x) for x in c)
                       + "))" for c in copies)
    table = "@{ " + "; ".join(f"{k} = {v}" for k, v in p.items()) + " }"
    return (_AMORCE.replace("__STATUT__", _ps_litteral(status_file))
                   .replace("__FICHIERS__", liste)
                   .replace("__PARAMS__", table))


def _commande_eleve(script_src, script_sha, params, status_file,
                    fichiers=None) -> str:
    """Paramètres de powershell.exe : l'amorce en `-EncodedCommand`
    (UTF-16LE puis base64 — aucun problème de guillemets)."""
    import base64
    code = _amorce_verifiee(script_src, script_sha, params, status_file,
                            fichiers)
    b64 = base64.b64encode(code.encode("utf-16-le")).decode("ascii")
    return subprocess.list2cmdline(
        ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", b64])


def _powershell_systeme() -> str:
    """Chemin ABSOLU de powershell.exe : un nom nu serait résolu par la
    recherche de Windows (dossier courant, PATH) — un endroit de plus où
    glisser un faux powershell.exe avant l'élévation."""
    racine = os.environ.get("SystemRoot") or os.environ.get("windir") or r"C:\Windows"
    return os.path.join(racine, "System32", "WindowsPowerShell", "v1.0",
                        "powershell.exe")


def _lancer_eleve(script_path, script_sha, params: dict, status_file,
                  fichiers: dict = None):
    """Lance le script ÉLEVÉ (une invite UAC), à travers l'amorce vérifiée.

    Rend (handle_process, ok, erreur). `ok=False` couvre aussi bien le refus
    de l'invite par l'utilisateur que powershell.exe introuvable — les deux
    sont des échecs « on n'a rien pu lancer », traités pareil par l'appelant.
    """
    params = _commande_eleve(script_path, script_sha, params, status_file,
                             fichiers)
    info = _SHELLEXECUTEINFOW()
    info.cbSize = ctypes.sizeof(_SHELLEXECUTEINFOW)
    info.fMask = _SEE_MASK_NOCLOSEPROCESS
    info.hwnd = None
    info.lpVerb = "runas"
    info.lpFile = _powershell_systeme()
    info.lpParameters = params
    info.lpDirectory = None
    info.nShow = _SW_HIDE
    ok = ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info))
    if not ok:
        err = ctypes.GetLastError()
        # 1223 = ERROR_CANCELLED : l'utilisateur a cliqué « Non » sur l'UAC.
        raison = (_L("firmware.raison_elevation_refusee") if err == 1223
                  else _L("firmware.raison_shellexecute_echec", code=err))
        return None, False, raison
    return info.hProcess, True, None


def _process_vivant(handle) -> bool:
    if not handle:
        return False
    try:
        r = ctypes.windll.kernel32.WaitForSingleObject(handle, 0)
        return r == _WAIT_TIMEOUT
    except Exception:
        return False


def _lire_status(chemin: Path):
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except Exception:
        return None


def _attendre_termine(status_file: Path, handle, timeout_s: float = 120.0):
    """Sonde le statut jusqu'à `termine`.

    Après le feu vert de nettoyage (`cleanup.flag`), le script élevé retire
    USBPcap (~20-30 s : remontage des root hubs + Uninstall.exe + balayage)
    puis se marque `termine`. On attend d'ABORD `termine` : le handle de
    `ShellExecuteExW(runas)` s'est révélé peu fiable ici (signalé « mort »
    AVANT la fin du nettoyage, d'où un faux « USBPcap pas retiré » le
    process mort). On ne renonce sur « process mort » qu'après 8 s de grâce
    (le `Write-Status` final peut encore atterrir).
    """
    fin = time.time() + timeout_s
    st = _lire_status(status_file) or {}
    mort_depuis = None
    while time.time() < fin:
        nouveau = _lire_status(status_file)
        if nouveau:
            st = nouveau
            if st.get("termine"):
                _log("journal.fw.capture_script_termine",
                     uninstall_ok=st.get('uninstall_ok'))
                return st
        if _process_vivant(handle):
            mort_depuis = None
        elif mort_depuis is None:
            mort_depuis = time.time()
        elif time.time() - mort_depuis > 8.0:
            _log("journal.fw.capture_script_disparu", etape=st.get('etape'))
            return _lire_status(status_file) or st
        time.sleep(0.5)
    _log("journal.fw.capture_nettoyage_expire", s=int(timeout_s))
    return _lire_status(status_file) or st


# Combien de temps le composant capture APRÈS que la wing soit revenue sur le
# bus, si aucun blob exploitable n'a encore été extrait. grandMA2 onPC pousse
# le firmware en ~2-3 s au rebranchement : 60 s de marge couvrent largement un
# onPC lent à réagir, sans faire lanterner l'utilisateur sur un échec réel.
GRACE_APRES_WING_S = 60.0

# ══ CAPTURE ══════════════════════════════════════════════════════════════
def capturer_firmware(timeout_s: float = 150.0) -> dict:
    """Installe (si besoin) → capture → extrait → désinstalle (si posé par nous).

    Synchrone — pensé pour tourner dans un thread à part (voir
    demarrer_capture_async), comme core.connect_wing(). Rend le même genre de
    dict que wing_firmware.enregistrer_firmware : {"ok": bool, "raison": str,
    "longueur": int}. Met CAPTURE_STATE à jour tout du long pour
    /api/status → majCapture() côté UI (ui/parametres.js).
    """
    if not sys.platform.startswith("win"):
        return {"ok": False, "raison": _L("firmware.echec.windows_only")}
    if _windows_arm():
        return {"ok": False, "raison": _L("firmware.echec.arm")}
    if CAPTURE_STATE["actif"]:
        return {"ok": False, "raison": _L("firmware.echec.deja_en_cours")}

    import wing_firmware_extract as fwx
    import wing_init

    _reset_state()
    CAPTURE_STATE["actif"] = True
    run_dir = None
    try:
        _etape("firmware.etape.verif_installeur")
        if not os.path.exists(INSTALLER):
            return _echec(_L("firmware.echec.installeur_absent", chemin=INSTALLER))
        sha = hashlib.sha256(Path(INSTALLER).read_bytes()).hexdigest()
        if sha != USBPCAP_SHA256:
            return _echec(_L("firmware.echec.installeur_empreinte", sha=sha))
        if not os.path.exists(SCRIPT_CAPTURE):
            return _echec(_L("firmware.echec.script_absent", chemin=SCRIPT_CAPTURE))

        # ── Étape 1/7 — grandMA2 onPC doit tourner : c'est LUI qui pousse le
        #    firmware à la wing. Sans lui, il n'y a rien à enregistrer. ───────
        _phase(1, "firmware.phase.1.titre", "firmware.phase.1.etape")
        if not gma2_onpc_lance():
            _etape("firmware.etape.ma2_absent")
            if not _attendre(gma2_onpc_lance, TIMEOUT_ATTENTE_MA2):
                if _ANNULER.is_set():
                    return _annule_resultat()
                return _echec(_L("firmware.echec.ma2_non_detecte"))
        _etape("firmware.etape.ma2_ok")

        # ── Étape 2/7 — la wing doit être DÉBRANCHÉE au départ : grandMA2 onPC
        #    ne (re)pousse le firmware qu'à un branchement, c'est cet instant
        #    précis qu'on enregistre. ────────────────────────────────────────
        _phase(2, "firmware.phase.2.titre", "firmware.phase.2.etape")
        if wing_sur_bus():
            _etape("firmware.etape.debranche_wing")
            if not _attendre(lambda: not wing_sur_bus(), TIMEOUT_DEBRANCHEMENT):
                if _ANNULER.is_set():
                    return _annule_resultat()
                return _echec(_L("firmware.echec.wing_branchee"))
            time.sleep(1.0)   # laisser l'énumération USB se stabiliser
        _etape("firmware.etape.wing_debranchee")
        if _ANNULER.is_set():        # annulée avant toute élévation : rien à nettoyer
            return _annule_resultat()

        deja_present = usbpcap_present()
        # Lu AVANT que ce run ne réécrive le flag : si une tentative PRÉCÉDENTE
        # a laissé USBPcap en place exprès (cas « redémarrage requis », voir
        # wing_firmware_capture_eleve.ps1), ce run le trouvera « déjà présent »
        # (deja_present=True) sans savoir que c'est NOUS qui l'avons posé — sauf
        # à consulter ce flag persistant. Sert au nettoyage différé en fin de
        # fonction, une fois la capture enfin réussie.
        installe_par_nous_avant = _lire_etat_installe()
        run_dir = Path(tempfile.mkdtemp(prefix="wingfw_"))
        status_file = run_dir / "status.json"
        stop_flag = run_dir / "stop.flag"
        cleanup_flag = run_dir / "cleanup.flag"

        # ── Étape 3/7 — une seule invite UAC, puis le script élevé installe
        #    USBPcap (si absent) et lance la capture. ─────────────────────────────
        # D'ici à la fin du nettoyage USBPcap, l'app LÂCHE le bus USB (usb_loop
        # consulte `usb_exclusif`) : le script élevé redémarre les root hubs, et
        # grandMA2 onPC doit pouvoir pousser le firmware.
        # ⚠️ Poser le drapeau ne fait qu'ANNONCER l'intention : on ATTEND la preuve que
        # la poignée est relâchée (`etat.E.DEV[0] is None`) avant de lancer l'élévation
        # — sinon usb_loop pouvait être en plein `dev.read()` au redémarrage des hubs.
        # (Pas USB_ARRET : rien ici ne relancerait usb_loop.) Non vérifié sur une vraie
        # machine Windows.
        CAPTURE_STATE["usb_exclusif"] = True
        try:
            import wing_ui as core
            fin = time.time() + 2.0
            while etat.E.DEV[0] is not None and time.time() < fin:
                time.sleep(0.05)
            if etat.E.DEV[0] is not None:
                _log("journal.fw.capture_boucle_pas_relachee")
        except Exception:
            pass
        _phase(3, "firmware.phase.3.titre", "firmware.phase.3.etape")
        # 🔒 L'installeur passe par `fichiers` : l'amorce le COPIE et le
        # revérifie côté élevé — la vérification de plus haut, faite ici en
        # non élevé, ne sert plus qu'à échouer tôt avec un message clair.
        handle, ok_lance, err = _lancer_eleve(
            SCRIPT_CAPTURE, SCRIPT_CAPTURE_SHA256, {
                "DejaPresent": "1" if deja_present else "0",
                "TimeoutS": str(int(timeout_s)),
                "StatusFile": str(status_file),
                "StopFlag": str(stop_flag),
                "WorkDir": str(run_dir),
                "CleanupFlag": str(cleanup_flag),
            }, status_file,
            fichiers={"InstallerPath": (INSTALLER, USBPCAP_SHA256)})
        if not ok_lance:
            return _echec(_L("firmware.echec.elevation", err=err))

        blob = None
        pcap_vus = []
        wing_vue_ts = None          # quand la wing est réapparue pendant l'étape 4
        deadline = time.time() + timeout_s + 60.0   # marge install + désinstall
        st = {}
        while time.time() < deadline:
            if _ANNULER.is_set():
                _log("journal.fw.capture_annul_pendant")
                try:
                    stop_flag.write_text("stop", encoding="utf-8")
                except OSError:
                    pass
                break
            nouveau = _lire_status(status_file)
            if nouveau:
                st = nouveau
                pcap_vus = st.get("pcap_files") or pcap_vus
                et = st.get("etape") or ""
                # Le script élevé passe en capture → étape 4 : « branche ta
                # wing ». On remplace le « capture en cours sur N interface(s) »
                # brut par une consigne qui suit l'USB en direct.
                if "capture en cours" in et and CAPTURE_STATE["phase"] < 4:
                    _phase(4, "firmware.phase.4.titre")
                    _log("journal.fw.capture_iface", et=et)
                if (blob is None and CAPTURE_STATE["phase"] == 4
                        and not st.get("termine")):
                    _etape("firmware.etape.wing_detectee" if wing_sur_bus()
                           else "firmware.etape.branche_wing")
                elif CAPTURE_STATE["phase"] < 4 and et:
                    _etape(et)

            # ── Marge après retour de la wing ───────────────────────────────
            # Une fois la wing revue sur le bus pendant l'étape 4, on donne
            # GRACE_APRES_WING_S à grandMA2 onPC pour pousser le firmware et à
            # l'extraction pour trouver un blob. Passé ce délai sans rien :
            # on arrête la capture proprement (stop.flag) plutôt que d'attendre
            # le timeout complet — l'échec est déjà certain.
            if (blob is None and CAPTURE_STATE["phase"] == 4
                    and not st.get("termine")):
                if wing_sur_bus():
                    if wing_vue_ts is None:
                        wing_vue_ts = time.time()
                        _log("journal.fw.capture_fenetre", s=int(GRACE_APRES_WING_S))
                    elif time.time() - wing_vue_ts > GRACE_APRES_WING_S:
                        _log("journal.fw.capture_sans_transfert", s=int(GRACE_APRES_WING_S))
                        try:
                            stop_flag.write_text("stop", encoding="utf-8")
                        except OSError:
                            pass

            if blob is None:
                for pf in pcap_vus:
                    if not os.path.exists(pf):
                        continue
                    try:
                        candidat = fwx.extract_from_pcapng(pf)
                    except Exception:
                        continue
                    ok_v, _msg = fwx.verify(candidat)
                    if ok_v:
                        blob = candidat
                        _etape("firmware.etape.blob_ok")
                        _log("journal.fw.capture_blob_ok")
                        try:
                            stop_flag.write_text("stop", encoding="utf-8")
                        except OSError:
                            pass
                        break

            if st.get("termine") or st.get("capture_finie"):
                # `capture_finie` : le script élevé a fini de capturer et ATTEND
                # notre feu vert de nettoyage (cleanup.flag). Le blob est trouvé
                # ou ne le sera plus — on sort pour enchaîner les étapes 5-7.
                break
            if not _process_vivant(handle) and not st.get("termine"):
                # Le script élevé a disparu sans se marquer « terminé » —
                # crash, ou tué de l'extérieur. On ne bloque pas indéfiniment.
                time.sleep(1.0)
                st = _lire_status(status_file) or st
                break
            time.sleep(1.0)

        def _feu_vert_nettoyage():
            try:
                cleanup_flag.write_text("go", encoding="utf-8")
            except OSError:
                pass

        # ── ÉCHEC ou ANNULATION : rien capturé — libérer le script élevé pour
        #    qu'il nettoie USBPcap tout de suite, puis rendre la main. ─────────
        if blob is None:
            annule = _ANNULER.is_set()
            _feu_vert_nettoyage()
            st = _attendre_termine(status_file, handle) or st
            installed_by_us = bool(st.get("installed_by_us"))
            uninstall_ok = st.get("uninstall_ok")
            garder_flag = _garder_flag_verifie(installed_by_us, uninstall_ok)
            _ecrire_etat_installe(garder_flag)
            residu = ""
            if garder_flag:
                residu = _L("firmware.residu.usbpcap_pas_retire_a")
            if annule:
                # garder_flag → _ecrire_etat_installe(True) déjà fait ⇒
                # statut_bouton_secours() renverra True (bouton de secours).
                _log("journal.fw.capture_annulee_usbpcap_retire" if not garder_flag
                     else "journal.fw.capture_annulee_usbpcap_garde")
                return _annule_resultat(residu)
            _log("journal.fw.capture_echec_detail",
                 iface=st.get('iface_count', '?'),
                 pcap=st.get('pcap_sizes') or 'aucun',
                 err=st.get('erreur') or '—')
            if st.get("besoin_redemarrage"):
                CAPTURE_STATE["besoin_redemarrage"] = True
                return _echec(st.get("erreur") or
                              _L("firmware.echec.besoin_redemarrage"))
            raison = _L("firmware.echec.aucun_transfert") + residu
            erreur_script = st.get("erreur")
            if erreur_script:
                raison = f"{erreur_script}{residu}"
            return _echec(raison)

        # ── SUCCÈS : persister le firmware AVANT toute autre manip ───────────
        res = wing_firmware.enregistrer_firmware(blob)
        if not res.get("ok"):
            _feu_vert_nettoyage()
            _attendre_termine(status_file, handle)
            return _echec(_L("firmware.echec.rejete", raison=res.get('raison')))
        chemin = wing_firmware.chemin_cache_firmware()
        CAPTURE_STATE["chemin"] = chemin

        try:
            import wing_ui as core
        except Exception:
            core = None
        residu_reprise = ""

        # ── Étape 5/7 — Ferme grandMA2 onPC : son pilote (OnPCWingDeviceClass,
        #    « onPC Wing for onPC2 Software ») TIENT la wing tant qu'il tourne —
        #    Wing Bridge (libusb/WinUSB) ne peut pas la reprendre avant, ET un
        #    root hub occupé par MA2 ne se remonte pas proprement (le retrait de
        #    USBPcap ci-dessous laisserait alors le service bloqué). ──────────
        _phase(5, "firmware.phase.5.titre", "firmware.phase.5.etape")
        ma2_ferme = True
        if gma2_onpc_lance():
            ma2_ferme = _attendre(lambda: not gma2_onpc_lance(), TIMEOUT_FERMER_MA2)
            if not ma2_ferme:
                residu_reprise = _L("firmware.residu.ma2_reste_ouvert")

        # ── Étape 6/7 — Débranche ta wing : bus au calme (MA2 fermé + wing
        #    partie) = la seule condition pour retirer USBPcap sans laisser le
        #    service bloqué jusqu'au reboot. ─────────────────────────────────
        if ma2_ferme:
            time.sleep(1.5)   # laisser le pilote de MA2 relâcher la wing
            _phase(6, "firmware.phase.6.titre", "firmware.phase.6.etape")
            if wing_sur_bus():
                if not _attendre(lambda: not wing_sur_bus(), TIMEOUT_DEBRANCHEMENT):
                    _log("journal.fw.capture_wing_pas_debranchee")
            time.sleep(1.0)

        # ── Feu vert : le script élevé retire USBPcap MAINTENANT ─────────────
        _etape("firmware.etape.retrait_composant")
        _log("journal.fw.capture_feu_vert")
        _feu_vert_nettoyage()
        st = _attendre_termine(status_file, handle) or st

        installed_by_us = bool(st.get("installed_by_us"))
        uninstall_ok = st.get("uninstall_ok")
        garder_flag = _garder_flag_verifie(installed_by_us, uninstall_ok)
        _ecrire_etat_installe(garder_flag)
        residu = ""
        if garder_flag:
            residu = _L("firmware.residu.usbpcap_pas_retire_b")

        # Nettoyage différé (USBPcap laissé par une tentative antérieure).
        if not installed_by_us and installe_par_nous_avant and usbpcap_present():
            _etape("firmware.etape.nettoyage_precedent")
            res_retrait = retirer_composant_capture()
            residu = "" if res_retrait.get("ok") else (
                _L("firmware.residu.usbpcap_tentative_precedente"))

        # ── L'app peut reprendre le bus pour l'étape 7 ──────────────────────
        CAPTURE_STATE["usb_exclusif"] = False

        # ── Étape 7/7 — Rebranche ta wing → Wing Bridge la reprend ──────────
        if not residu_reprise:
            _phase(7, "firmware.phase.7.titre", "firmware.phase.7.etape")
            if not (core and etat.E.STATE.get("wing")):
                _attendre(wing_sur_bus, TIMEOUT_REBRANCHER)
                time.sleep(1.0)
                if core is not None and not etat.E.STATE.get("wing"):
                    try:
                        threading.Thread(
                            target=lambda: core.connect_wing(force=True),
                            daemon=True).start()
                    except Exception:
                        pass
                if not _attendre(lambda: bool(core and etat.E.STATE.get("wing")),
                                 TIMEOUT_CONNEXION):
                    residu_reprise = _L("firmware.residu.wing_pas_reprise")

        note_finale = (residu or "") + residu_reprise
        ok_complet = not residu_reprise
        _phase(7 if ok_complet else 6,
               "firmware.phase.fin.titre_ok" if ok_complet
               else "firmware.phase.fin.titre_partiel",
               "firmware.phase.fin.etape_ok" if ok_complet
               else "firmware.phase.fin.etape_partiel",
               o=res['longueur'], chemin=chemin, residu=residu_reprise)
        CAPTURE_STATE["ok"] = True
        CAPTURE_STATE["note"] = note_finale or None
        return {"ok": True, "longueur": res["longueur"], "residu": note_finale,
                "chemin": chemin}
    finally:
        CAPTURE_STATE["usb_exclusif"] = False
        if run_dir is not None:
            if CAPTURE_STATE.get("ok") is not True:
                try:
                    _archiver_diagnostic(run_dir)
                except Exception:
                    pass
            shutil.rmtree(run_dir, ignore_errors=True)
        CAPTURE_STATE["actif"] = False


def _echec(raison: str) -> dict:
    CAPTURE_STATE["ok"] = False
    CAPTURE_STATE["raison"] = raison
    return {"ok": False, "raison": raison}


def _annule_resultat(residu: str = "") -> dict:
    """Fin PROPRE sur annulation utilisateur — pas un échec, pas un succès.

    `annule:True` : l'UI (majCapture) affiche un message neutre, pas la
    bannière rouge des vrais échecs, et NE propose pas l'aiguillage de fin.
    Un `residu` (USBPcap pas retiré) est repris tel quel.
    """
    txt = _L("firmware.annulee") + (residu or "")
    CAPTURE_STATE["ok"] = False
    CAPTURE_STATE["annule"] = True
    CAPTURE_STATE["raison"] = txt
    CAPTURE_STATE["etape"] = txt
    return {"ok": False, "annule": True, "raison": txt}


# ══ RETRAIT À LA DEMANDE (bouton de secours des Paramètres) ═════════════
def retirer_composant_capture() -> dict:
    """Désinstalle USBPcap sur demande explicite — même mécanisme d'élévation.

    Bouton de secours SEULEMENT : visible dans l'UI uniquement quand USBPcap
    est présent ET que `usbpcap_installe_par_nous` est vrai (un nettoyage
    automatique a précédemment échoué). Sans rapport avec une capture — pas
    de CAPTURE_STATE ici, juste ok/raison.
    """
    if not sys.platform.startswith("win"):
        return {"ok": False, "raison": _L("firmware.echec.hors_windows")}
    if not os.path.exists(SCRIPT_RETIRER):
        return {"ok": False, "raison": _L("firmware.echec.script_retrait_absent", chemin=SCRIPT_RETIRER)}
    if not usbpcap_present():
        _ecrire_etat_installe(False)
        return {"ok": True, "raison": _L("firmware.info.usbpcap_deja_parti")}

    run_dir = Path(tempfile.mkdtemp(prefix="wingfw_rm_"))
    try:
        status_file = run_dir / "status.json"
        handle, ok_lance, err = _lancer_eleve(
            SCRIPT_RETIRER, SCRIPT_RETIRER_SHA256,
            {"StatusFile": str(status_file)}, status_file)
        if not ok_lance:
            return {"ok": False, "raison": _L("firmware.echec.elevation", err=err)}
        deadline = time.time() + 30.0
        st = {}
        while time.time() < deadline:
            nouveau = _lire_status(status_file)
            if nouveau:
                st = nouveau
            if st.get("termine"):
                break
            if not _process_vivant(handle):
                time.sleep(0.5)
                st = _lire_status(status_file) or st
                break
            time.sleep(0.5)
        ok = bool(st.get("uninstall_ok"))
        _ecrire_etat_installe(not ok)
        if ok:
            return {"ok": True}
        return {"ok": False, "raison": st.get("uninstall_error")
                or _L("firmware.retrait_pas_confirme")}
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)


def statut_bouton_secours() -> bool:
    """Le bouton « Retirer le composant de capture » doit-il apparaître ?

    Seulement si USBPcap est là ET qu'on est celui qui l'a mis — jamais pour
    un USBPcap que l'utilisateur avait installé lui-même (Wireshark, etc.) :
    ce n'est pas à nous d'y toucher.
    """
    if not sys.platform.startswith("win"):
        return False
    return usbpcap_present() and _lire_etat_installe()
