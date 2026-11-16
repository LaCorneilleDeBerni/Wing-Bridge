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
SCRIPT_CAPTURE_SHA256 = "7cbf50865043c809ab93e925d30d912e41ade3870904d1287c0d8cf4af39b0cb"
SCRIPT_RETIRER_SHA256 = "101453a274f155e55096902244ee129ed97f9335844e86dc44c2cf4b559d684a"

# ── État de progression, lu par /api/status à CHAQUE poll (400 ms, voir
# ui/init.js) — c'est ce qui permet à l'interface d'afficher l'assistant pas à
# pas EN DIRECT pendant l'opération (installation USBPcap comprise, ~1-3 min).
#
# `phase` (1→7) = le CARTON courant de l'assistant semi-automatique (décision
# de l'auteur du 13/11/2026 : plus rien n'avance tout seul — chaque carton
# attend un clic « Suivant », actif seulement quand ses détections sont
# vertes ; 🟠 = geste de l'utilisateur, ⚙️ = automatique, lancé PAR le clic
# « Suivant » du carton précédent) :
#   1. 🟠 Préparation : wing DÉBRANCHÉE (absence durable) + grandMA2 onPC lancé
#   2. ⚙️ Autorisation Windows (UAC), installation d'USBPcap, enregistrement
#   3. 🟠 Branche ta wing → ⚙️ transfert + extraction → « firmware capturé »
#   4. 🟠 Ferme grandMA2 onPC          ← il TIENT la wing tant qu'il tourne
#   5. 🟠 Débranche ta wing            ← bus au calme → retrait PROPRE de USBPcap
#   6. ⚙️ Retrait d'USBPcap
#   7. 🟠 Rebranche ta wing → Wing connectée (fin, sans clic)
# `phase_titre` : titre résolu du carton (journal) ; `chemin` : où le firmware
# a atterri, affiché à la fin.
#
# Champs du mode « cartons » (lus par ui/parametres.js, _fwCaptureCartons) :
#   `attente_utilisateur` : vrai pendant qu'un `_attendre_suivant()` tourne ;
#   `pastilles`          : [{cle, etat: "vert"|"rouge"|"orange", texte}] — les
#                          détections du carton courant, texte déjà résolu
#                          dans la langue de l'app (comme `etape`) ;
#   `suivant_possible`   : vrai SEULEMENT si on attend un clic ET qu'aucune
#                          pastille n'est rouge (orange = avertissement non
#                          bloquant) — c'est l'unique chose qui active le
#                          bouton « Suivant » côté interface (fwSuivantActif) ;
#   `suivant_cle`        : clé i18n du libellé du bouton (il dit ce que le clic
#                          DÉCLENCHE : « autoriser Windows », « retirer USBPcap »…).
#
# ⚠️ `usb_exclusif` : vrai UNIQUEMENT des cartons 2-3 jusqu'à la fin du
# retrait d'USBPcap (carton 6) — le seul moment où l'app doit LÂCHER le bus
# (voir wing_connexion.usb_loop). Le carton 1 (pré-vol) et le carton 7
# (rebranchement, attente de connexion) ont au contraire BESOIN que usb_loop
# tourne pour que Wing Bridge reprenne la wing.
PHASES_TOTAL = 7
CAPTURE_STATE = {"actif": False, "etape": "", "ok": None, "raison": None,
                 "note": None, "besoin_redemarrage": False, "annule": False,
                 "phase": 0, "phase_total": PHASES_TOTAL, "phase_titre": "",
                 "chemin": None, "usb_exclusif": False,
                 "attente_utilisateur": False, "pastilles": [],
                 "suivant_possible": False, "suivant_cle": None,
                 "interrompu_au": None}

# ── Annulation « à tout moment » ─────────────────────────────────────────────
# Bouton « Annuler la démarche » de l'assistant (dispo tout du long). On NE TUE
# RIEN de force : on pose ce drapeau, que la boucle de capture et `_attendre`
# surveillent. Si l'utilitaire élevé (USBPcap) tourne déjà, la boucle lui donne
# le feu vert de désinstallation (stop.flag + cleanup.flag) et attend qu'il
# confirme AVANT de rendre la main — USBPcap ne reste jamais installé derrière
# une annulation. Un `threading.Event` : posé depuis le thread HTTP, lu depuis
# le thread de capture.
_ANNULER = threading.Event()

# ── Le clic « Suivant » ──────────────────────────────────────────────────────
# Posé par la route POST /api/firmware/capture/suivant (thread HTTP), consommé
# par `_attendre_suivant()` (thread de capture). Un clic n'est PRIS que si la
# détection du carton est verte à l'instant où la boucle le voit ; sinon il est
# ignoré et journalisé. Remis à zéro à l'entrée de chaque carton : un clic
# resté en suspens ne peut jamais valider le carton suivant.
_SUIVANT = threading.Event()

# ── Filets de temps, PAS des moteurs d'avancement ───────────────────────────
# Depuis l'assistant à cartons (13/11/2026), aucun délai ne fait avancer quoi
# que ce soit : seul le clic « Suivant » avance. Ces constantes bornent juste
# l'attente pour que l'assistant finisse toujours PROPREMENT (USBPcap retiré,
# message clair) si l'utilisateur disparaît.
TIMEOUT_CLIC_S        = 900.0    # 15 min sans clic « Suivant » sur un carton
TIMEOUT_PREPARATION_S = 300.0    # carton 2 : UAC + installation + attache à chaud

# Cartons 1 et 5 (« wing débranchée ») : nombre d'échantillons CONSÉCUTIFS « wing
# absente » (sondés à 1 s d'intervalle) exigés avant de tenir la wing pour
# réellement débranchée — 6 sondes d'affilée = absence vue pendant 5 s.
#
# Pourquoi pas 1 (l'ancien comportement) : un seul échantillon ne distingue pas
# un débranchement d'une RÉ-ÉNUMÉRATION. Quand grandMA2 onPC pousse le
# firmware, la wing quitte le bus ~1,3 s avant de réapparaître (mesuré,
# docs/HARDWARE.md « Init à froid », étape 6) ; et une wing coincée en
# bootloader décroche seule du bus pendant ses reboots. Sur l'Asus le
# 12/11/2026, l'étape 2 a avancé SANS débranchement — hypothèse (non prouvée,
# pas de trace USB) : une telle ré-énumération prise pour un retrait.
#
# Pourquoi 5 s : c'est LE seuil déjà éprouvé par la boucle USB pour la même
# question « la wing est-elle vraiment partie ? » — `ABSENCE_REELLE_S = 5.0`
# dans wing_ui.py (lu par wing_connexion.py près de `autodemarrage_tardif`) :
# en dessous, c'est la wing qui décroche seule pendant un reboot ; une coupure
# humaine dure bien plus de 5 s. Deux seuils différents pour la même question
# seraient une incohérence à expliquer plus tard. La valeur est RECOPIÉE ici
# plutôt qu'importée : ce module ne charge pas wing_ui au niveau module (il
# doit s'importer léger, sur toute plateforme) ; le test de fumée (section 49)
# vérifie que (6 − 1) × 1 s ≥ wing_ui.ABSENCE_REELLE_S, pour que les deux ne
# dérivent pas l'un de l'autre en silence.
ABSENCE_DURABLE_ECHANTILLONS = 6
TIMEOUT_REBRANCHER    = 120.0    # carton 7 : « rebranche ta wing » (sans clic)
TIMEOUT_CONNEXION     = 60.0     # carton 7 : « Wing connectée » par usb_loop

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


# ── Délai minimum de LISIBILITÉ d'un carton ──────────────────────────────────
# Les transitions entre cartons sont presque toutes déclenchées par un clic
# « Suivant » : l'utilisateur a lu avant de cliquer, aucun risque de
# « clignotement ». Il reste les transitions AUTOMATIQUES (carton 7 →
# « Wing connectée », titres de fin) : chaque carton reste affiché AU MOINS
# `_PHASE_MIN_S` avant que le suivant ne le remplace, seulement si le
# précédent a duré moins que ça. L'ancienne surcharge de 10 s sur « Débranche
# ta wing » (`_PHASE_TENIR`) n'a plus d'objet : ce geste est désormais un
# carton à clic, il ne peut plus défiler sans être vu.
_PHASE_MIN_S = 2.5
_phase_horodate = [0.0]        # time.monotonic() du dernier _phase() ; liste = mutable
_phase_min = [_PHASE_MIN_S]    # combien de temps tenir le carton EN COURS avant le suivant


def _reset_state():
    CAPTURE_STATE.update({"actif": False, "etape": "", "ok": None,
                          "raison": None, "note": None,
                          "besoin_redemarrage": False, "annule": False,
                          "phase": 0, "phase_total": PHASES_TOTAL,
                          "phase_titre": "", "chemin": None,
                          "usb_exclusif": False,
                          "attente_utilisateur": False, "pastilles": [],
                          "suivant_possible": False, "suivant_cle": None,
                          "interrompu_au": None})
    _phase_horodate[0] = 0.0   # une 2e capture dans le même process repart propre
    _phase_min[0] = _PHASE_MIN_S
    _ANNULER.clear()           # une annulation ne déborde pas sur la capture suivante
    _SUIVANT.clear()           # ni un clic « Suivant » resté en suspens


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
    _phase_min[0] = _PHASE_MIN_S
    # Un carton neuf repart sans pastille ni « Suivant » : c'est la détection
    # du carton (ou _attendre_suivant) qui les reposera.
    CAPTURE_STATE["pastilles"] = []
    CAPTURE_STATE["suivant_possible"] = False
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


def _attendre(cond, timeout_s: float, intervalle: float = 1.0,
              consecutifs: int = 1) -> bool:
    """Sonde `cond` jusqu'à ce qu'elle rende vrai, ou expiration. Rend bool.

    Sert au carton 7 (le seul sans clic : « Rebranche ta wing » → « Wing
    connectée ») et à `wing_absente_durablement()`. Pour tout carton qui
    attend un geste de l'utilisateur, c'est `_attendre_suivant()` : la
    détection ne fait plus avancer, elle ne fait qu'ACTIVER le clic.

    `consecutifs` : nombre de sondes `cond()` vraies D'AFFILÉE exigées (1 par
    défaut = le premier vrai suffit). Un échantillon faux — ou une exception —
    remet la série à zéro. Sert à exiger une condition DURABLE (étape 2 : la
    wing absente du bus pendant plusieurs secondes, pas un clignement).

    Rend `False` IMMÉDIATEMENT si l'utilisateur a demandé l'annulation
    (`_ANNULER`) : l'appelant vérifie alors `_ANNULER` et prend le chemin
    d'arrêt propre plutôt que le message d'échec d'un timeout.
    """
    fin = time.time() + timeout_s
    vus = 0                      # sondes vraies consécutives
    while time.time() < fin:
        if _ANNULER.is_set():
            return False
        try:
            vrai = bool(cond())
        except Exception:
            vrai = False
        vus = vus + 1 if vrai else 0
        if vus >= consecutifs:
            return True
        time.sleep(intervalle)
    return False


class _SondeAbsenceDurable:
    """Une sonde À ÉTAT : « la wing est-elle PARTIE du bus — pour de bon ? »

    Chaque appel prend UN échantillon `wing_sur_bus()` ; rend vrai seulement
    après ABSENCE_DURABLE_ECHANTILLONS échantillons « absente » CONSÉCUTIFS
    (voir la constante : une ré-énumération de ~1,3 s ne doit pas passer pour
    un débranchement). Un échantillon « présente » — ou une exception —
    remet la série à zéro. `vus` expose le compte courant, pour que la
    pastille dise « absente depuis N s — confirmation » plutôt qu'un rouge
    muet. C'est LA seule implémentation de la règle « absence durable » :
    `wing_absente_durablement()` (chantier A) et les cartons 1 et 5 de
    l'assistant passent tous par elle.
    """

    def __init__(self):
        self.vus = 0

    def __call__(self) -> bool:
        try:
            absente = not wing_sur_bus()
        except Exception:
            absente = False
        self.vus = self.vus + 1 if absente else 0
        return self.vus >= ABSENCE_DURABLE_ECHANTILLONS


def wing_absente_durablement(timeout_s: float, intervalle: float = 1.0) -> bool:
    """Bloquant : sonde jusqu'à une absence DURABLE de la wing, ou expiration.

    Vrai seulement après ABSENCE_DURABLE_ECHANTILLONS sondes « absente »
    consécutives (_SondeAbsenceDurable). Faux sur expiration ou annulation
    (`_ANNULER`), comme _attendre(). Conservé du chantier A ; les cartons de
    l'assistant utilisent la sonde directement, dans `_attendre_suivant()`.
    """
    return _attendre(_SondeAbsenceDurable(), timeout_s, intervalle=intervalle)


# ══ L'ATTENTE D'UN CLIC « SUIVANT » ═══════════════════════════════════════
def _pastille(cle: str, couleur: str, texte_cle: str, **params) -> dict:
    """Une détection affichable : `couleur` ∈ vert (détecté), rouge (pas
    détecté, bloque « Suivant »), orange (avertissement, ne bloque pas) —
    publiée sous la clé `etat` (le paramètre ne s'appelle pas `etat` : il
    masquerait le module d'état partagé, contrôle 81). Le texte est résolu
    dans la langue de l'app, comme `etape`."""
    return {"cle": cle, "etat": couleur, "texte": _L(texte_cle, **params)}


def _publier_pastilles(pastilles, attente: bool) -> bool:
    """Pose les pastilles dans CAPTURE_STATE et en déduit `suivant_possible`.

    `suivant_possible` n'est vrai QUE si l'on attend un clic (`attente`) ET
    qu'aucune pastille n'est rouge. Pendant une partie automatique
    (attente=False) il reste faux : le bouton « Suivant » de l'interface ne
    peut pas mentir. La liste est REMPLACÉE, jamais modifiée en place :
    /api/status la sérialise depuis un autre thread.
    """
    liste = list(pastilles)
    possible = bool(attente) and bool(liste) and all(
        p.get("etat") != "rouge" for p in liste)
    CAPTURE_STATE["pastilles"] = liste
    CAPTURE_STATE["suivant_possible"] = possible
    return possible


def _attendre_suivant(n: int, detection, timeout_s: float = TIMEOUT_CLIC_S,
                      intervalle: float = 1.0,
                      suivant_cle: str = "firmware.suivant.defaut",
                      abandon=None) -> bool:
    """Le cœur de l'assistant semi-automatique : attendre le clic « Suivant ».

    Boucle 1×/s : évalue `detection()` (→ liste de pastilles, voir
    `_pastille`), publie l'état pour l'interface, et ne rend la main QUE
    quand l'utilisateur a cliqué « Suivant » (`_SUIVANT`, posé par la route
    POST /api/firmware/capture/suivant) ALORS QUE la détection est verte au
    moment où le clic est vu. Un clic arrivé au rouge est ignoré et
    journalisé — jamais mis de côté pour plus tard.

    Rend `True` sur clic valide, `False` sur annulation (`_ANNULER`), sur
    `abandon()` vrai (une condition extérieure a rendu le carton caduc — ex.
    l'enregistrement s'est arrêté avant le clic) ou à l'expiration du filet
    `timeout_s` (TIMEOUT_CLIC_S, 15 min) ; l'appelant choisit alors la fin
    propre qui convient. Les délais ne font JAMAIS avancer.
    """
    _SUIVANT.clear()
    CAPTURE_STATE["suivant_cle"] = suivant_cle
    CAPTURE_STATE["attente_utilisateur"] = True
    fin = time.monotonic() + timeout_s
    try:
        while True:
            if _ANNULER.is_set():
                return False
            if abandon is not None:
                try:
                    caduc = bool(abandon())
                except Exception:
                    caduc = False
                if caduc:
                    _log("journal.fw.capture_carton_abandon", n=n)
                    return False
            try:
                pastilles = list(detection())
            except Exception:
                pastilles = [_pastille("detection", "rouge",
                                       "firmware.pastille.detection_erreur")]
            possible = _publier_pastilles(pastilles, attente=True)
            if _SUIVANT.is_set():
                _SUIVANT.clear()
                if _ANNULER.is_set():      # clic et annulation dans le même tick : l'annulation gagne
                    return False
                if possible:
                    _log("journal.fw.capture_suivant_clic", n=n)
                    return True
                _log("journal.fw.capture_suivant_ignore", n=n)
            if time.monotonic() >= fin:
                _log("journal.fw.capture_suivant_expire", n=n,
                     min=int(round(timeout_s / 60.0)))
                return False
            # Réveil immédiat sur clic ou annulation, sinon au prochain tick.
            _SUIVANT.wait(intervalle)
    finally:
        CAPTURE_STATE["attente_utilisateur"] = False
        CAPTURE_STATE["suivant_possible"] = False


def suivant_capture() -> dict:
    """Route POST /api/firmware/capture/suivant : le clic « Suivant ».

    Ne décide RIEN : pose `_SUIVANT`, que `_attendre_suivant()` consomme en
    vérifiant la détection à cet instant. Refus (code 409) si aucune capture
    n'est active ou si l'assistant n'attend pas de clic (partie automatique
    en cours) — un clic qui n'a pas de carton à valider n'est pas gardé.
    """
    if not CAPTURE_STATE["actif"]:
        return {"ok": False, "code": 409, "raison": _L("err.capture_aucune")}
    if not CAPTURE_STATE["attente_utilisateur"]:
        return {"ok": False, "code": 409,
                "raison": _L("err.capture_pas_en_attente")}
    _SUIVANT.set()
    return {"ok": True, "carton": CAPTURE_STATE["phase"],
            "detection_verte": bool(CAPTURE_STATE["suivant_possible"])}


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
def _fenetre_script_s(timeout_s: float) -> int:
    """Durée de capture (`TimeoutS`) passée au script élevé — un FILET.

    ⚠️ Ce n'est plus la fenêtre d'enregistrement « utile » (c'est `timeout_s`,
    tenue côté Python au carton 3). Depuis l'assistant à cartons,
    l'enregistrement démarre au carton 2 et n'est arrêté (stop.flag) qu'au
    feu vert de nettoyage, APRÈS les clics des cartons 3, 4 et 5 — parce que
    le script élevé, une fois sa capture finie, n'attend le feu vert que
    360 s avant de retirer USBPcap TOUT SEUL (wing_firmware_capture_eleve.ps1,
    attente de $CleanupFlag — le script ne bouge pas, ses empreintes sont
    figées). Avec des cartons à clic, ces 360 s pouvaient expirer pendant que
    grandMA2 onPC tourne encore → retrait à bus occupé, service coincé
    jusqu'au reboot (docs/WINDOWS.md, « À BUS CALME »). On laisse donc la
    capture ouverte (quelques Mo de .pcap de plus, rien d'autre) et on
    dimensionne `TimeoutS` pour que ce soient TOUJOURS les filets Python
    (4 cartons × TIMEOUT_CLIC_S + l'enregistrement) qui tombent en premier.
    """
    return int(4 * TIMEOUT_CLIC_S + timeout_s + GRACE_APRES_WING_S + 120.0)


def _pastille_absence(sonde: "_SondeAbsenceDurable") -> dict:
    """Prend UN échantillon de la sonde et le traduit en pastille : rouge
    « wing encore là », rouge « absente depuis N s — confirmation », vert
    « débranchée (plus de 5 s) »."""
    sonde()
    n = ABSENCE_DURABLE_ECHANTILLONS - 1       # secondes d'absence exigées à 1 Hz
    if sonde.vus >= ABSENCE_DURABLE_ECHANTILLONS:
        return _pastille("wing_absente", "vert",
                         "firmware.pastille.wing_absente_ok", s=n)
    if sonde.vus > 0:
        return _pastille("wing_absente", "rouge",
                         "firmware.pastille.wing_absente_confirmation",
                         s=sonde.vus - 1, total=n)
    return _pastille("wing_absente", "rouge", "firmware.pastille.wing_branchee")


def capturer_firmware(timeout_s: float = 150.0) -> dict:
    """Assistant semi-automatique à 7 cartons : installe (si besoin) → capture
    → extrait → désinstalle (si posé par nous) — chaque partie automatique
    n'étant lancée QUE par le clic « Suivant » du carton précédent
    (`_attendre_suivant`), actif seulement quand la détection est verte.

    Synchrone — pensé pour tourner dans un thread à part (voir
    wing_handler._post_firmware_capture), comme core.connect_wing(). Rend le
    même genre de dict que wing_firmware.enregistrer_firmware : {"ok": bool,
    "raison": str, "longueur": int}. Met CAPTURE_STATE à jour tout du long
    pour /api/status → majCapture() côté UI (ui/parametres.js).

    `timeout_s` : fenêtre d'enregistrement « utile » du carton 3 (temps laissé
    pour brancher la wing), PAS la durée passée au script élevé — voir
    `_fenetre_script_s`.
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
    minutes_clic = int(round(TIMEOUT_CLIC_S / 60.0))
    try:
        _etape("firmware.etape.verif_installeur")
        if not os.path.exists(INSTALLER):
            return _echec(_L("firmware.echec.installeur_absent", chemin=INSTALLER))
        sha = hashlib.sha256(Path(INSTALLER).read_bytes()).hexdigest()
        if sha != USBPCAP_SHA256:
            return _echec(_L("firmware.echec.installeur_empreinte", sha=sha))
        if not os.path.exists(SCRIPT_CAPTURE):
            return _echec(_L("firmware.echec.script_absent", chemin=SCRIPT_CAPTURE))

        # ── Carton 1/7 — 🟠 Préparation : wing DÉBRANCHÉE et grandMA2 onPC
        #    lancé. La wing doit être partie AVANT que l'enregistrement ne
        #    s'ouvre : grandMA2 onPC ne (re)pousse le firmware qu'à un
        #    branchement, et c'est cet instant précis qu'on enregistre. Absence
        #    DURABLE exigée (_SondeAbsenceDurable, chantier A) : sur l'Asus le
        #    12/11/2026 un seul échantillon « absente » avait suffi à avancer
        #    sans débranchement. Et c'est grandMA2 onPC qui pousse le firmware :
        #    sans lui, rien à enregistrer. Les deux pastilles vertes ⇒ le clic
        #    « Suivant » (qui lance l'autorisation Windows) devient possible. ──
        _phase(1, "firmware.phase.1.titre", "firmware.phase.1.etape")
        sonde1 = _SondeAbsenceDurable()

        def _detection_1():
            ma2 = gma2_onpc_lance()
            return [_pastille_absence(sonde1),
                    _pastille("ma2", "vert" if ma2 else "rouge",
                              "firmware.pastille.ma2_ok" if ma2
                              else "firmware.pastille.ma2_ko")]

        if not _attendre_suivant(1, _detection_1,
                                 suivant_cle="firmware.suivant.autorisation"):
            if _ANNULER.is_set():      # annulée avant toute élévation : rien à nettoyer
                return _annule_resultat()
            return _echec(_L("firmware.echec.clic_expire", n=1, min=minutes_clic))

        deja_present = usbpcap_present()
        # Lu AVANT que ce run ne réécrive le flag : si une tentative PRÉCÉDENTE
        # a laissé USBPcap en place exprès (cas « redémarrage requis », voir
        # wing_firmware_capture_eleve.ps1), ce run le trouvera « déjà présent »
        # (deja_present=True) sans savoir que c'est NOUS qui l'avons posé — sauf
        # à consulter ce flag persistant. Sert au nettoyage différé au carton 6,
        # une fois la capture enfin réussie.
        installe_par_nous_avant = _lire_etat_installe()
        run_dir = Path(tempfile.mkdtemp(prefix="wingfw_"))
        status_file = run_dir / "status.json"
        stop_flag = run_dir / "stop.flag"
        cleanup_flag = run_dir / "cleanup.flag"

        # ── Carton 2/7 — ⚙️ Lancé par le clic du carton 1 : une seule invite
        #    UAC, puis le script élevé installe USBPcap (si absent), attache le
        #    filtre à chaud et ouvre l'enregistrement. ───────────────────────────
        # D'ici à la fin du retrait d'USBPcap (carton 6), l'app LÂCHE le bus USB
        # (usb_loop consulte `usb_exclusif`) : le script élevé redémarre les
        # root hubs, et grandMA2 onPC doit pouvoir pousser le firmware.
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
        _phase(2, "firmware.phase.2.titre", "firmware.phase.2.etape")
        _publier_pastilles([_pastille("autorisation", "rouge",
                                      "firmware.pastille.preparation")],
                           attente=False)
        # 🔒 L'installeur passe par `fichiers` : l'amorce le COPIE et le
        # revérifie côté élevé — la vérification de plus haut, faite ici en
        # non élevé, ne sert plus qu'à échouer tôt avec un message clair.
        handle, ok_lance, err = _lancer_eleve(
            SCRIPT_CAPTURE, SCRIPT_CAPTURE_SHA256, {
                "DejaPresent": "1" if deja_present else "0",
                "TimeoutS": str(_fenetre_script_s(timeout_s)),
                "StatusFile": str(status_file),
                "StopFlag": str(stop_flag),
                "WorkDir": str(run_dir),
                "CleanupFlag": str(cleanup_flag),
            }, status_file,
            fichiers={"InstallerPath": (INSTALLER, USBPCAP_SHA256)})
        if not ok_lance:
            return _echec(_L("firmware.echec.elevation", err=err))

        st_box = [{}]           # dernier statut lu du script élevé (boîte = mutable)

        def _statut() -> dict:
            nouveau = _lire_status(status_file)
            if nouveau:
                st_box[0] = nouveau
            return st_box[0]

        def _demander_arret():
            try:
                stop_flag.write_text("stop", encoding="utf-8")
            except OSError:
                pass

        def _feu_vert_nettoyage():
            # stop.flag D'ABORD : depuis l'assistant à cartons, l'enregistrement
            # tourne encore à cet instant (voir _fenetre_script_s) — sans lui le
            # script attendrait sa propre échéance avant de voir cleanup.flag.
            _demander_arret()
            try:
                cleanup_flag.write_text("go", encoding="utf-8")
            except OSError:
                pass

        blob = None
        pcap_vus = []
        enregistrement = False      # le script a-t-il annoncé « capture en cours » ?
        wing_vue_ts = None          # quand la wing est réapparue pendant le carton 3
        # ── Ce que le carton 3 a VU — lecture seule, ne pilote rien ─────────
        # `wing_deja_la` : la wing était DÉJÀ sur le bus à l'ouverture du
        # carton 3. Constat Asus 12/11/2026 : wing jamais débranchée, firmware
        # poussé AVANT l'enregistrement → « aucun transfert », et l'ancien
        # message envoyait vérifier grandMA2 onPC, qui tournait. `None` tant
        # que le carton 3 n'est pas ouvert. Sert UNIQUEMENT à choisir le
        # message d'échec (`_cle_aucun_transfert`).
        wing_deja_la = None

        def _fin_echec(raison_filet: str = None) -> dict:
            """ÉCHEC ou ANNULATION : rien capturé — libérer le script élevé
            pour qu'il nettoie USBPcap tout de suite, puis rendre la main.
            `raison_filet` : raison imposée par un filet de temps (clic
            « Suivant » jamais venu), prioritaire sur le diagnostic « aucun
            transfert », mais pas sur une erreur rapportée par le script."""
            annule = _ANNULER.is_set()
            _feu_vert_nettoyage()
            st = _attendre_termine(status_file, handle) or st_box[0]
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
            # `etape` : la DERNIÈRE ligne de statut écrite par le script élevé.
            # Sans elle, un script figé avant son premier `iface_count` ne
            # laissait dans le journal que `interfaces=?, script_error=—`
            # (cas Dell XPS 7590, 11 échecs illisibles — voir WINDOWS.md).
            _log("journal.fw.capture_echec_detail",
                 iface=st.get('iface_count', '?'),
                 pcap=st.get('pcap_sizes') or 'aucun',
                 err=st.get('erreur') or '—',
                 etape=st.get('etape') or '—')
            if st.get("besoin_redemarrage"):
                CAPTURE_STATE["besoin_redemarrage"] = True
                return _echec(st.get("erreur") or
                              _L("firmware.echec.besoin_redemarrage"))
            # Contexte de l'échec, pour le diagnostic après coup : ce que le
            # carton 3 a vu, et si grandMA2 onPC tourne encore à cet instant.
            ma2_tourne = gma2_onpc_lance()
            _log("journal.fw.capture_echec_contexte",
                 deja=wing_deja_la,
                 s=(int(time.time() - wing_vue_ts) if wing_vue_ts else "—"),
                 ma2=ma2_tourne)
            erreur_script = st.get("erreur")
            if erreur_script:
                raison = f"{erreur_script}{residu}"
            elif raison_filet:
                raison = raison_filet + residu
            elif not enregistrement:
                # La préparation (carton 2) n'a jamais ouvert l'enregistrement :
                # dire OÙ le script en était, pas « aucun transfert » (le Dell
                # XPS 7590 a eu droit onze fois à ce message hors sujet).
                raison = _L("firmware.echec.preparation_pas_aboutie",
                            s=int(TIMEOUT_PREPARATION_S),
                            etape=st.get("etape") or "—") + residu
            else:
                raison = _L(_cle_aucun_transfert(
                    enregistrement_ouvert=CAPTURE_STATE["phase"] >= 3,
                    wing_deja_la=wing_deja_la,
                    wing_vue=wing_vue_ts is not None,
                    ma2_tourne=ma2_tourne)) + residu
            if CAPTURE_STATE["phase"] >= 3:
                # La pastille « firmware capturé » du carton 3 porte la raison,
                # en rouge — l'interface y accroche « Réessayer ».
                _publier_pastilles([
                    _pastille("wing_vue", "vert" if wing_vue_ts else "rouge",
                              "firmware.pastille.wing_vue_ok" if wing_vue_ts
                              else "firmware.pastille.wing_vue_ko"),
                    _pastille("blob", "rouge", "firmware.pastille.blob_ko",
                              raison=raison)], attente=False)
            return _echec(raison)

        # Préparation (UAC, installation, attache à chaud) : on suit le statut
        # brut du script jusqu'à « capture en cours ». Filet :
        # TIMEOUT_PREPARATION_S — le Dell XPS 7590 est resté figé ici 5 min 30.
        fin_prep = time.time() + TIMEOUT_PREPARATION_S
        while True:
            if _ANNULER.is_set():
                _log("journal.fw.capture_annul_pendant")
                break
            st = _statut()
            et = st.get("etape") or ""
            if et:
                _etape(et)          # statut brut du script élevé (installation, hubs…)
            if "capture en cours" in et and not st.get("termine"):
                enregistrement = True
                pcap_vus = st.get("pcap_files") or pcap_vus
                _log("journal.fw.capture_iface", et=et)
                break
            if st.get("termine") or st.get("capture_finie"):
                break
            if not _process_vivant(handle) and not st.get("termine"):
                # Le script élevé a disparu sans se marquer « terminé » —
                # crash, ou tué de l'extérieur. On ne bloque pas indéfiniment.
                time.sleep(1.0)
                _statut()
                break
            if time.time() >= fin_prep:
                _log("journal.fw.capture_preparation_expiree",
                     s=int(TIMEOUT_PREPARATION_S))
                break
            time.sleep(1.0)
        if not enregistrement:
            return _fin_echec()

        # L'enregistrement tourne : pastille verte, « Suivant » possible. Le
        # carton reste tant que l'utilisateur ne clique pas — l'enregistrement
        # continue pendant ce temps (voir _fenetre_script_s). `abandon` : si
        # le script s'arrête avant le clic, le carton est caduc.
        n_iface = st_box[0].get("iface_count", "?")

        def _enregistrement_tourne() -> bool:
            st = _statut()
            return (not st.get("termine") and not st.get("capture_finie")
                    and _process_vivant(handle))

        def _detection_2():
            tourne = _enregistrement_tourne()
            return [_pastille("enregistrement", "vert" if tourne else "rouge",
                              "firmware.pastille.enregistrement_ok" if tourne
                              else "firmware.pastille.enregistrement_ko",
                              n=n_iface)]

        _etape("firmware.phase.2.etape_fait")
        if not _attendre_suivant(2, _detection_2,
                                 abandon=lambda: not _enregistrement_tourne()):
            if _ANNULER.is_set() or not _enregistrement_tourne():
                return _fin_echec()
            return _fin_echec(_L("firmware.echec.clic_expire", n=2,
                                 min=minutes_clic))

        # ── Carton 3/7 — 🟠 Branche ta wing → ⚙️ attente du transfert +
        #    extraction. La wing doit apparaître MAINTENANT, pendant que
        #    l'enregistrement tourne ; grandMA2 onPC lui pousse son firmware
        #    en ~2-3 s, l'extraction tourne sur les .pcap en cours d'écriture. ─
        _phase(3, "firmware.phase.3.titre", "firmware.phase.3.etape")
        # Un seul échantillon, pris à l'ouverture du carton 3 (donc APRÈS le
        # remontage des hubs du script élevé, et avant que la consigne
        # « branche ta wing » ait pu être suivie). Wing présente ici = elle n'a
        # pas été (re)branchée pendant l'enregistrement.
        wing_deja_la = wing_sur_bus()
        if wing_deja_la:
            _log("journal.fw.capture_wing_deja_la")
        # `grace_signalee` : la fenêtre de grâce ne s'écrit qu'UNE fois au
        # journal (sans ce drapeau, la ligne repartait à chaque tour de 1 s
        # jusqu'à ce que le script élevé confirme l'arrêt).
        grace_signalee = False
        deadline = time.time() + timeout_s
        while True:
            if _ANNULER.is_set():
                _log("journal.fw.capture_annul_pendant")
                _demander_arret()
                break
            st = _statut()
            pcap_vus = st.get("pcap_files") or pcap_vus
            sur_bus = wing_sur_bus()
            if blob is None and not st.get("termine"):
                _etape("firmware.etape.wing_detectee" if sur_bus
                       else "firmware.etape.branche_wing")

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
                        # ⚠️ PAS de stop.flag ici (contrairement à l'assistant
                        # automatique d'avant) : arrêter la capture ferait
                        # démarrer les 360 s au bout desquelles le script
                        # retire USBPcap seul — voir _fenetre_script_s. Le
                        # stop vient avec le feu vert, au carton 6.
                        break

            # ── Marge après retour de la wing ───────────────────────────────
            # Une fois la wing revue sur le bus pendant le carton 3, on donne
            # GRACE_APRES_WING_S à grandMA2 onPC pour pousser le firmware et à
            # l'extraction pour trouver un blob. Passé ce délai sans rien :
            # on demande l'arrêt de la capture (stop.flag) plutôt que d'attendre
            # la fenêtre complète.
            # ⚠️ Ce bloc vient APRÈS la passe d'extraction, et son message ne
            # conclut PAS : le verdict n'est pas acquis ici. Sur l'Asus le
            # 12/11/2026, « sans transfert exploitable — arrêt de la capture »
            # est sorti juste AVANT « blob valide extrait » — l'extraction
            # continue tant que le script élevé n'a pas confirmé l'arrêt
            # (`capture_finie`), et c'est cette dernière passe qui a trouvé le
            # firmware. stop.flag et délais sont inchangés.
            if blob is None and not st.get("termine"):
                if sur_bus:
                    if wing_vue_ts is None:
                        wing_vue_ts = time.time()
                        # La grâce doit pouvoir aller à son terme même si la
                        # wing arrive en toute fin de fenêtre.
                        deadline = max(deadline,
                                       wing_vue_ts + GRACE_APRES_WING_S + 15.0)
                        _log("journal.fw.capture_fenetre", s=int(GRACE_APRES_WING_S))
                    elif time.time() - wing_vue_ts > GRACE_APRES_WING_S:
                        if not grace_signalee:
                            grace_signalee = True
                            _log("journal.fw.capture_fenetre_ecoulee",
                                 s=int(GRACE_APRES_WING_S))
                        _demander_arret()

            _publier_pastilles([
                _pastille("wing_vue", "vert" if sur_bus else "rouge",
                          "firmware.pastille.wing_vue_ok" if sur_bus
                          else "firmware.pastille.wing_vue_ko"),
                _pastille("blob", "vert" if blob is not None else "rouge",
                          "firmware.pastille.blob_ok" if blob is not None
                          else "firmware.pastille.blob_attente",
                          o=len(blob) if blob is not None else 0)],
                attente=False)
            if blob is not None:
                break
            if st.get("termine") or st.get("capture_finie"):
                # `capture_finie` : le script élevé a fini de capturer (grâce
                # écoulée → stop.flag) et ATTEND notre feu vert de nettoyage.
                # Le blob est trouvé ou ne le sera plus.
                break
            if not _process_vivant(handle) and not st.get("termine"):
                time.sleep(1.0)
                _statut()
                break
            if time.time() >= deadline:
                break
            time.sleep(1.0)

        if blob is None:
            return _fin_echec()

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
        # `interrompu` : annulation ou filet APRÈS la sauvegarde du firmware.
        # On ne jette rien (le firmware est en place), on saute les gestes
        # restants et on va droit au retrait d'USBPcap, puis à une fin
        # « partielle » qui dit ce qui reste à faire. `interrompu_au` : le
        # carton où ça s'est arrêté (l'interface marque les suivants « sautés »,
        # pas « faits »).
        interrompu = False

        def _interrompre():
            nonlocal interrompu
            if not interrompu:
                interrompu = True
                CAPTURE_STATE["interrompu_au"] = CAPTURE_STATE["phase"]

        # Le firmware est SAUVÉ : la pastille le dit, « Suivant » s'ouvre. La
        # wing peut rester branchée ou non (orange, sans incidence).
        def _detection_3():
            sur_bus = wing_sur_bus()
            return [_pastille("wing_vue", "vert" if sur_bus else "orange",
                              "firmware.pastille.wing_vue_ok" if sur_bus
                              else "firmware.pastille.wing_vue_info"),
                    _pastille("blob", "vert", "firmware.pastille.blob_ok",
                              o=res["longueur"])]

        if not _attendre_suivant(3, _detection_3):
            _interrompre()

        # ── Carton 4/7 — 🟠 Ferme grandMA2 onPC : son pilote (OnPCWingDeviceClass,
        #    « onPC Wing for onPC2 Software ») TIENT la wing tant qu'il tourne —
        #    Wing Bridge (libusb/WinUSB) ne peut pas la reprendre avant, ET un
        #    root hub occupé par MA2 ne se remonte pas proprement (le retrait de
        #    USBPcap au carton 6 laisserait alors le service bloqué). ──────────
        if not interrompu:
            _phase(4, "firmware.phase.4.titre", "firmware.phase.4.etape")

            def _detection_4():
                ouvert = gma2_onpc_lance()
                return [_pastille("ma2_ferme", "rouge" if ouvert else "vert",
                                  "firmware.pastille.ma2_ferme_ko" if ouvert
                                  else "firmware.pastille.ma2_ferme_ok")]

            if not _attendre_suivant(4, _detection_4):
                _interrompre()
                residu_reprise = _L("firmware.residu.ma2_reste_ouvert")

        # ── Carton 5/7 — 🟠 Débranche ta wing : bus au calme (MA2 fermé + wing
        #    partie) = la seule condition pour retirer USBPcap sans laisser le
        #    service bloqué jusqu'au reboot. Absence DURABLE, même sonde qu'au
        #    carton 1. Le clic « Suivant » lance le retrait. ─────────────────
        if not interrompu:
            time.sleep(1.5)   # laisser le pilote de MA2 relâcher la wing
            _phase(5, "firmware.phase.5.titre", "firmware.phase.5.etape")
            sonde5 = _SondeAbsenceDurable()
            if not _attendre_suivant(5, lambda: [_pastille_absence(sonde5)],
                                     suivant_cle="firmware.suivant.retrait"):
                _interrompre()
                _log("journal.fw.capture_wing_pas_debranchee")
            time.sleep(1.0)

        # ── Carton 6/7 — ⚙️ Retrait d'USBPcap, lancé par le clic du carton 5 :
        #    stop.flag + cleanup.flag → le script élevé arrête la capture,
        #    détache le filtre et désinstalle. ────────────────────────────────
        _phase(6, "firmware.phase.6.titre", "firmware.phase.6.etape")
        _etape("firmware.etape.retrait_composant")
        _publier_pastilles([_pastille("retrait", "rouge",
                                      "firmware.pastille.retrait_en_cours")],
                           attente=False)
        _log("journal.fw.capture_feu_vert")
        _feu_vert_nettoyage()
        st = _attendre_termine(status_file, handle) or st_box[0]

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

        # ── L'app peut reprendre le bus pour le carton 7 ────────────────────
        CAPTURE_STATE["usb_exclusif"] = False

        if residu:
            # Orange : avertissement non bloquant — le firmware est en place,
            # le bouton de secours et le message de fin prennent le relais.
            pastille6 = _pastille("retrait", "orange", "firmware.pastille.retrait_ko")
        elif installed_by_us or installe_par_nous_avant:
            pastille6 = _pastille("retrait", "vert", "firmware.pastille.retrait_ok")
        else:
            pastille6 = _pastille("retrait", "vert",
                                  "firmware.pastille.retrait_sans_objet")
        _etape("firmware.phase.6.etape_fait")
        if not interrompu:
            if not _attendre_suivant(6, lambda: [pastille6],
                                     suivant_cle="firmware.suivant.rebrancher"):
                _interrompre()
        else:
            _publier_pastilles([pastille6], attente=False)

        # ── Carton 7/7 — 🟠 Rebranche ta wing → Wing Bridge la reprend. Le seul
        #    carton sans clic : « Wing connectée » EST la fin. ────────────────
        if not interrompu:
            _phase(7, "firmware.phase.7.titre", "firmware.phase.7.etape")

            def _etat_7():
                sur_bus = wing_sur_bus()
                connectee = bool(core and etat.E.STATE.get("wing"))
                _publier_pastilles([
                    _pastille("rebranche", "vert" if (sur_bus or connectee) else "rouge",
                              "firmware.pastille.rebranche_ok" if (sur_bus or connectee)
                              else "firmware.pastille.rebranche_ko"),
                    _pastille("connectee", "vert" if connectee else "rouge",
                              "firmware.pastille.connectee_ok" if connectee
                              else "firmware.pastille.connectee_ko")],
                    attente=False)
                return sur_bus, connectee

            if not _etat_7()[1]:
                _attendre(lambda: _etat_7()[0], TIMEOUT_REBRANCHER)
                time.sleep(1.0)
                if core is not None and not etat.E.STATE.get("wing"):
                    try:
                        threading.Thread(
                            target=lambda: core.connect_wing(force=True),
                            daemon=True).start()
                    except Exception:
                        pass
                if not _attendre(lambda: _etat_7()[1], TIMEOUT_CONNEXION):
                    residu_reprise = _L("firmware.residu.wing_pas_reprise")

        if interrompu and not residu_reprise:
            residu_reprise = _L("firmware.residu.assistant_interrompu")
        pastilles_fin = list(CAPTURE_STATE["pastilles"])
        note_finale = (residu or "") + residu_reprise
        ok_complet = not residu_reprise
        _phase(7 if ok_complet else CAPTURE_STATE["phase"],
               "firmware.phase.fin.titre_ok" if ok_complet
               else "firmware.phase.fin.titre_partiel",
               "firmware.phase.fin.etape_ok" if ok_complet
               else "firmware.phase.fin.etape_partiel",
               o=res['longueur'], chemin=chemin, residu=residu_reprise)
        _publier_pastilles(pastilles_fin, attente=False)   # _phase() les avait vidées
        CAPTURE_STATE["ok"] = True
        CAPTURE_STATE["note"] = note_finale or None
        return {"ok": True, "longueur": res["longueur"], "residu": note_finale,
                "chemin": chemin}
    finally:
        CAPTURE_STATE["usb_exclusif"] = False
        CAPTURE_STATE["attente_utilisateur"] = False
        CAPTURE_STATE["suivant_possible"] = False
        if run_dir is not None:
            if CAPTURE_STATE.get("ok") is not True:
                try:
                    _archiver_diagnostic(run_dir)
                except Exception:
                    pass
            shutil.rmtree(run_dir, ignore_errors=True)
        CAPTURE_STATE["actif"] = False


def _cle_aucun_transfert(enregistrement_ouvert: bool, wing_deja_la,
                         wing_vue: bool, ma2_tourne: bool) -> str:
    """Clé i18n de l'échec « aucun transfert », choisie d'après ce que la
    capture a VU — jamais d'après une supposition. Fonction PURE, testée
    sur toutes les combinaisons utiles par le contrôle `test_firmware_capture`.

    Ordre de priorité (du constat le plus fort au plus générique) :
      1. la wing était DÉJÀ sur le bus à l'ouverture de l'enregistrement →
         tout transfert a eu lieu avant (Asus, 12/11/2026 : grandMA2 onPC
         tournait, l'ancien message envoyait pourtant le vérifier) ;
      2. la wing n'est JAMAIS apparue pendant l'enregistrement → elle n'a
         pas été branchée quand l'assistant le demandait ;
      3. grandMA2 onPC ne tourne plus au moment du verdict → c'est lui qui
         pousse le firmware ;
      4. sinon : générique, causes plausibles dans l'ordre utile (wing pas
         vraiment débranchée / rebranchée trop tôt, PUIS seulement onPC).
    Sans étape 4 ouverte (script élevé mort avant la capture), on ne sait
    rien de la wing : générique.
    """
    if not enregistrement_ouvert:
        return "firmware.echec.aucun_transfert"
    if wing_deja_la:
        return "firmware.echec.aucun_transfert_wing_deja_la"
    if not wing_vue:
        return "firmware.echec.aucun_transfert_wing_jamais_vue"
    if not ma2_tourne:
        return "firmware.echec.aucun_transfert_ma2_ferme"
    return "firmware.echec.aucun_transfert"


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
