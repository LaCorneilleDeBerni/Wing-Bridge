"""Connexion USB à la wing, boucle de lecture/écriture, injection DMX.

⚠️ Même motif que les modules déjà extraits : `import wing_ui as core` DANS
chaque fonction, et toute donnée qui reste dans `wing_ui.py` s'y accède par
`core.X`, jamais en référence nue — y compris entre fonctions de CE fichier
quand le nom est monkeypatché par `smoke_test.py` sur `wing_ui` (voir plus
bas, `connect_wing`/`cycle_dmx`/`log`/`full_init`).

L'ÉTAT PARTAGÉ se lit et s'écrit via `etat.E.<champ>` (etat.py, audit du
25/09/2026, D1) — jamais via `wing_ui`, dont les anciens noms lèvent.
Constantes lues via `core.X` : `ABSENCE_REELLE_S`, `LED_FULL`,
`FADER_ORDER` ; `_boucle_tic` est une fonction de `wing_ui.py`.

⚠️⚠️ `connect_wing` ET `cycle_dmx` sont monkeypatchés par `smoke_test.py` en
RÉASSIGNATION COMPLÈTE sur `wing_ui` (`ui.connect_wing = faux_connect`,
`ui.cycle_dmx = faux_cycle` — pas une mutation). `usb_loop()` les appelle
tous les deux, et `_flux_muet()` appelle `connect_wing` — ces appels
internes, bien que dans ce même fichier, sont donc qualifiés
`core.connect_wing(...)`/`core.cycle_dmx(...)`, jamais nus.

⚠️ `full_init` (de `wing_init.py`, importé par `wing_ui.py`) est LUI AUSSI
monkeypatché en réassignation complète sur `wing_ui` (`ui.full_init = …`,
contrôle 39 notamment). `connect_wing()` l'appelle donc en `core.full_init(...)`,
pas via un import direct de `wing_init.full_init`. Le reste de `wing_init`
(`wing_absente`, `DERNIER_ECHEC`, `effacer_etat_materiel`, `blocage_connu`,
`JOURNAL`) est un singleton comme `wb`/`wm` : accédé en `wing_init.X` nu,
sans passer par `core` — un monkeypatch posé dessus mute l'objet module
lui-même, visible de partout qui l'importe.

⚠️ `log` a déménagé dans `wing_reglages.py` (étape 8) mais reste accessible
en `core.log(...)` d'ici comme de partout ailleurs — même motif.

🔒 Un contrôle de `smoke_test.py` (« Les deux sorties rendent la wing ») fait
un audit de SOURCE : il cherche `def restart_self(` dans le texte des
fichiers `.py` du projet et vérifie qu'`arreter_usb(`/`_release_device(`
apparaît dans les 1200 caractères qui suivent. Il balaie tous les `.py`
(pas seulement `wing_ui.py`) pour survivre à ce découpage et aux suivants —
même principe que `test_messages_actionnables`.

`USB_ARRET`/`USB_SORTIE`/`WING_FLUX`/`WingUnplugged` déménagent mais restent
RÉ-EXPORTÉS : `smoke_test.py` les mute/instancie directement
(`.set()`/`.wait()`/`.clear()`, `WING_FLUX["..."]`, `ui.WingUnplugged()`),
et `Handler`/`main()` (pas encore découpés) les lisent/démarrent en bare.
Aucun n'est jamais RÉASSIGNÉ en bloc par ce code externe.
"""

import etat
import os
import subprocess
import sys
import threading
import time

import usb.core
import usb.util

import wing_bridge as wb
import wing_init
import wing_etat_materiel


# ── Connexion wing ─────────────────────────────────────────────────────────────

def _release_device():
    """Libère proprement la poignée USB courante."""
    import wing_ui as core
    # Poignée et drapeau changent ENSEMBLE, sous verrou : un lecteur de STATE
    # ne doit jamais voir « wing connectée » sans poignée (ou l'inverse).
    with etat.E.LOCK:
        dev = etat.E.DEV[0]
        etat.E.DEV[0] = None
        etat.E.STATE["wing"] = False
    # Remise à zéro de la santé du flux : une nouvelle poignée USB ne doit pas
    # hériter du « muette » de la précédente, ni de son erreur.
    WING_FLUX.update(last_ok=0.0, muette=False, erreur="", signale=False)
    if dev is not None:
        # release_interface AVANT dispose_resources, et explicitement : c'est
        # la revendication exclusive de l'interface qui bloque la suivante si
        # elle n'est pas rendue. On ne s'en remet pas au ménage implicite.
        try:
            usb.util.release_interface(dev, 0)
        except Exception:
            pass
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


def connect_wing(force: bool = False, quiet: bool = False,
                 force_operateur: bool = False):
    """(Re)connecte la wing. force=True ré-initialise même si déjà 'connectée'.
    quiet=True (auto-reconnexion) : ne journalise pas les tentatives ratées,
    pour ne pas noyer le log pendant que la wing est absente.
    force_operateur=True : reconnexion complète — transmis à full_init pour
    renvoyer le firmware même à une wing en speed 2 (muette après arrachage à
    chaud). Passé UNIQUEMENT par usb_loop quand `RECO_MUETTE["force_demande"]` est
    armé (automatiquement au 1er verdict muette). Défaut False partout ailleurs :
    le garde-fou de upload_firmware reste actif pour tout autre appelant."""
    import wing_ui as core
    core.etat_poser(want_connected=True)   # intention : garder la wing active

    # 🔒 Test-et-pose ATOMIQUE sous etat.E.LOCK : usb_loop, le fil de `_flux_muet`
    # et la route « Connecter » peuvent appeler ceci en même temps ; test et pose
    # séparés laissaient passer deux `full_init()` sur le même device.
    with etat.E.LOCK:
        if etat.E.STATE["connecting"]:
            return
        if etat.E.STATE["wing"] and not force:
            return
        etat.E.STATE["connecting"] = True

    # Un essai lancé par un BOUTON repousse AUSSI l'auto-reconnexion
    # (`AUTO["last_try"]`) : sinon la boucle repartait aussitôt et touchait au
    # firmware une 2e fois. Un essai est un essai, quelle que soit son origine.
    etat.E.AUTO["last_try"] = time.time()
    core.etat_poser(mode="idle")          # arrêter le bridge pendant la (ré)init

    # ⚠️ NE JAMAIS RELÂCHER LE DEVICE PENDANT QU'UN AUTRE THREAD LIT/ÉCRIT
    # DESSUS. `usb_loop` ne teste jamais `STATE["mode"]` et continue ses
    # `dev.write()`/`dev.read()` indépendamment tant qu'il tient un `dev`.
    #
    # Même protocole que `arreter_usb()` : poser `USB_ARRET`, attendre
    # `USB_SORTIE` — mais SEULEMENT si un device est effectivement tenu. Si
    # `DEV[0]` est déjà `None`, c'est `usb_loop` LUI-MÊME qui vient de nous
    # appeler depuis sa branche « dev is None » (aucun `dev` en vol à
    # protéger) : attendre sa propre sortie ferait un blocage mutuel, puisqu'il
    # ne peut pas revenir en tête de boucle tant qu'il est ici, dans cet appel.
    reprise_boucle = etat.E.DEV[0] is not None
    if reprise_boucle:
        USB_ARRET.set()
        if not USB_SORTIE.wait(USB_SORTIE_ATTENTE_S):
            core.log("journal.wing.boucle_pas_arret")

    _release_device()                # repartir d'une poignée propre
    time.sleep(0.3)
    if not quiet:
        core.log("journal.wing.connexion")
    try:
        # `force` vient du bouton : un clic délibéré passe outre un blocage
        # persistant. C'est le dernier recours garanti si l'heuristique
        # d'adresse USB se trompe.
        dev = core.full_init(verbose=False, force=force,
                             force_operateur=force_operateur)
        if dev is not None:
            # 🧹 Purge du canal de lecture avant le premier tour — conservée comme
            # simple filet. ⚠️ Elle ne règle PAS la cadence à deux états (30 Hz / 2,8 Hz) :
            # mesurée SANS effet sur ce symptôme, dont la cause a été supprimée ailleurs.
            # → docs/HARDWARE.md#cadence-de-boucle-a-deux-etats-30-hz-ou-2-7-hz-une-fois-sur-deux
            try:
                wb.drain(dev, 40, timeout_ms=5)
            except Exception:
                pass
            with etat.E.LOCK:
                etat.E.DEV[0] = dev
                etat.E.STATE["wing"] = True
            etat.E.AUTO["echecs"] = 0
            etat.E.AUTO["interval"] = 2.0            # l'espacement repart à zéro
            etat.E.AUTO["attend_rebranchement"] = False
            # Connexion réussie : l'épisode de reco est clos, compteur d'escalade
            # remis à zéro (le prochain arrachage rouvrira un épisode neuf).
            wing_init._reco_muette_reset(episode=False)
            core.log("journal.wing.connectee")
            # Reprise du bridge, quelle que soit l'ORIGINE de la connexion
            # (démarrage, bouton, ou boucle d'auto-reconnexion). `resume_mode`
            # est posé soit par un arrachage de câble, soit par un « Démarrer »
            # cliqué alors qu'aucune wing n'était là — les deux méritent le
            # même traitement.
            # Test ET bascule dans le même bloc : `_post_mode` peut désarmer
            # `resume_mode` au même instant (clic « Arrêter »).
            with etat.E.LOCK:
                reprise = etat.E.STATE["resume_mode"]
                if reprise:
                    etat.E.STATE["mode"] = reprise
                    etat.E.STATE["resume_mode"] = None
            if reprise:
                core.log("journal.wing.bridge_auto")
        else:
            _echec_init(quiet)
    except Exception as e:
        _echec_init(quiet, f" ({type(e).__name__}: {e})")
    finally:
        # `usb_loop` a rendu la main plus haut : on la relance, succès ou non —
        # sinon plus personne ne pilote la wing ni l'auto-reconnexion.
        #
        # ⚠️ ORDRE : relancer AVANT de relâcher `connecting` (sinon un second
        # `connect_wing()` se glisse entre les deux et lance SA boucle), et changer de
        # GÉNÉRATION avant d'effacer `USB_ARRET` : une ancienne boucle restée coincée
        # dans un tour plus long que l'attente se retire alors d'elle-même au lieu de
        # repartir à côté de la neuve (2 boucles mesurées avant ce correctif, chaque
        # geste envoyé deux fois à MA3). Contrôle test_une_seule_boucle_usb.
        if reprise_boucle:
            with etat.E.LOCK:
                etat.E.USB_GEN += 1
                gen = etat.E.USB_GEN
            USB_ARRET.clear()
            USB_SORTIE.clear()
            threading.Thread(target=usb_loop, args=(gen,), daemon=True,
                             name="usb_loop").start()
        core.etat_poser(connecting=False)


def _echec_init(quiet: bool, detail: str = ""):
    """Un essai d'init a échoué → on ARRÊTE d'essayer jusqu'au rebranchement.

    🔑 Établi expérimentalement : quand un chargement de firmware
    échoue à démarrer, tous les suivants échouent aussi TANT QUE la wing n'a
    pas été mise hors tension. 6 essais d'affilée → 6 échecs ; une coupure de
    18 s puis 1 seul essai → succès en 1,5 s.

    Réessayer est donc pire qu'inutile : chaque essai renvoie le firmware et
    fait rebooter la wing (LED qui clignotent), ce qui l'entretient dans son
    état bloqué. On pose donc un verrou, levé UNIQUEMENT quand la wing a
    réellement disparu du bus — preuve qu'elle a été débranchée.
    """
    import wing_ui as core
    etat.E.AUTO["echecs"] += 1

    # ⚠️ Le verrou ne concerne QUE « wing présente, firmware qui ne démarre
    # pas ». Wing absente : rien à verrouiller — sinon il se posait et se levait
    # chaque seconde, et noyait le journal.
    if wing_init.wing_absente():
        return

    # ⚠️ …et seulement quand le FIRMWARE refuse de démarrer, seul cas où une
    # coupure d'alimentation est indispensable. Une erreur transitoire (endpoint en
    # halt, « Pipe error ») se règle seule : ne jamais envoyer quelqu'un
    # débrancher son matériel pour rien, en pleine régie.
    if not wing_init.DERNIER_ECHEC.get("firmware_bloque"):
        # Espacement progressif : 2 s, 3 s, 4,5 s… plafonné à 10 s. Un échec
        # transitoire se règle au 1er ou 2e essai ; s'il persiste, insister
        # toutes les 2 s ne fait que remplir le journal (vécu : 9 lignes
        # identiques en 28 s).
        etat.E.AUTO["interval"] = min(etat.E.AUTO["interval"] * 1.5, 10.0)
        # ⚠️ ON PARLE AUSSI EN MODE AUTOMATIQUE — mais UNE SEULE FOIS par
        # branchement (`essais_presence == 1`). `quiet` servait à ne pas noyer
        # le journal quand la wing est absente ; il finissait par cacher
        # l'échec lui-même. Un branchement raté ne laissait donc rien derrière
        # lui, ce qui rend l'observation de l'entrée en bootloader impossible.
        if not quiet or etat.E.AUTO["essais_presence"] == 1:
            core.log("journal.wing.init_echouee", detail=detail,
                     s=f"{etat.E.AUTO['interval']:.0f}")
        return

    etat.E.AUTO["attend_rebranchement"] = True
    if not quiet or etat.E.AUTO["echecs"] == 1:
        core.log("journal.wing.non_initialisee", detail=detail)
    # ⚠️ NE PAS RÉPÉTER LA CONSIGNE. `wing_init` vient de dire, à
    # la ligne précédente, quel geste faire. Ce message-ci arrivait derrière et
    # redonnait la même instruction en CAPITALES : l'utilisateur lisait deux
    # fois « débranche », ce qui donne l'impression d'un problème plus grave
    # qu'il n'est. Ici on ne dit plus que ce que l'autre ne dit pas : que les
    # tentatives s'arrêtent, et qu'elles repartiront seules.
    core.log("journal.wing.suspendu")


# ── Redémarrage du moteur ────────────────────────────────────────────────────
#
# ⚠️⚠️ `os.execv`, ET NE PAS INVERSER — cette règle a DÉJÀ été retournée une
#    fois, sur un raisonnement plausible et faux (« même PID = interface USB
#    jamais rendue », réfuté par la mesure : `claim: ok` pendant la panne).
#
# 🔢 CE SONT LES CHIFFRES QUI TRANCHENT, ils restent donc ici :
#       execv        (même PID) : 24 sessions,  0 wing absente
#       process neuf            : 15 sessions, 11 absentes
#    Un process qui MEURT fait re-énumérer la wing, qui revient lente une fois
#    sur deux. Le process neuf n'est qu'un repli si execv échoue.
#    → docs/HARDWARE.md#redemarrage-du-moteur-os-execv-et-pourquoi-l-inverse-a-ete-essaye
USB_SORTIE_ATTENTE_S = 2.0      # connect_wing : attente max de la sortie de boucle
USB_ARRET  = threading.Event()   # demande d'arrêt de la boucle USB
USB_SORTIE = threading.Event()   # la boucle confirme qu'elle en est sortie


def arreter_usb(delai: float = 2.0):
    """Arrête la boucle USB et rend l'interface au système.

    On ATTEND que la boucle soit sortie d'une éventuelle lecture en cours
    (jusqu'à 300 ms de délai d'attente) avant de libérer quoi que ce soit :
    disposer d'un device pendant qu'un autre thread lit dessus, c'est
    exactement ce qui laisse le matériel dans un état incertain.
    """
    import wing_ui as core
    USB_ARRET.set()
    if not USB_SORTIE.wait(delai):
        core.log("journal.wing.boucle_pas_arret")
    _release_device()


def restart_self():
    """Redémarre le moteur EN PLACE, après avoir rendu la wing proprement.

    ⚠️⚠️ RETOUR À `os.execv` APRÈS MESURE. Ne pas re-basculer sur un process
    neuf sans preuve ; voici la preuve qui a fait revenir :

        `os.execv` (même PID) : 24 sessions,  0 wing absente au démarrage
        process neuf          : 15 sessions, 11 absentes — 100 % sur la fin

    Un process qui meurt fait fermer la liaison USB par le système, et LA WING
    RE-ÉNUMÈRE. Une fois sur deux environ, elle revient à 670 ms par lecture au
    lieu de 0,4. Avec execv le process ne meurt pas, la liaison n'est jamais
    fermée par le système, et la wing ne re-énumère pas.

    Le passage au process neuf reposait sur une hypothèse — la réservation
    d'interface perdue par execv — que la mesure a RÉFUTÉE (`claim: ok`
    pendant la panne). Elle a donc coûté sans rien apporter : d'occasionnel,
    le problème est devenu systématique.

    Ce qui est CONSERVÉ de cette tentative, et qui vaut :
      • `arreter_usb()` ci-dessous — la boucle ne se fait plus couper en
        pleine lecture, ce qui est juste dans tous les cas ;
      • la mesure du temps de réponse et le réveil automatique.
    """
    import wing_ui as core
    arreter_usb()
    # 🪟 Windows : os.execv est ÉMULÉ (spawn+exit), pas un remplacement d'image
    # en place. Il ÉCHOUE quand le chemin de l'exécutable contient un espace
    # (« Wing Bridge ») — le C-runtime mal-quote la ligne de commande — et il ne
    # lève PAS d'exception (mesuré : moteur tué, successeur jamais démarré,
    # repli jamais atteint). On passe donc DIRECTEMENT par le relancement
    # subprocess (arguments en LISTE, robustes aux espaces, avec vérification du
    # démarrage). Le PID change — normal et assumé sous Windows (contrairement au
    # même-PID de l'execv macOS).
    if sys.platform == "win32":
        _relancer_process_neuf()
        return
    try:
        core.vider_journal()       # execv remplace le process : rien ne survit
        os.execv(sys.executable, sys.argv)
    except Exception as e:
        core.log("journal.wing.restart_place_ko", err=e)
    _relancer_process_neuf()


def _relancer_process_neuf():
    """Relance le moteur dans un process NEUF, puis quitte celui-ci.

    Chemin PRINCIPAL sous Windows (os.execv y est cassé, voir restart_self) ;
    repli sous macOS si os.execv lève. Le PID change ; la wing peut ré-énumérer.

    ⚠️ Deux garde-fous, chèrement acquis :
    • Arguments passés en LISTE à subprocess — jamais une chaîne reconstruite —
      c'est ce qui évite le bug d'espace dans le chemin qui casse `os.execv`.
    • PAS de sortie AVEUGLE : on vérifie que le successeur a bien démarré (et
      n'est pas mort aussitôt) AVANT de laisser mourir ce process. On ne peut PAS
      attendre que son HTTP réponde ici : il lie le MÊME port 8765 et n'y accède
      qu'APRÈS notre mort (handshake WING_ATTENDRE_PID + retry « port occupé » au
      démarrage). Mais un successeur encore vivant après ~1,2 s écarte
      l'échec-au-lancement SILENCIEUX qu'avait `os.execv` sous Windows.
    """
    import wing_ui as core
    # Le successeur doit ATTENDRE notre mort avant de toucher à l'USB : on lui
    # passe notre PID. Sans ça il ouvrait la wing pendant qu'on la tenait
    # encore — voir _attendre_instance_precedente().
    env = os.environ.copy()
    env["WING_ATTENDRE_PID"] = str(os.getpid())
    try:
        proc = subprocess.Popen(
            [sys.executable] + sys.argv[1:],
            start_new_session=True,          # survit à la mort de ce process
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        core.log("journal.wing.relance_ko", err=e)
        return
    # Le successeur attend notre mort (WING_ATTENDRE_PID) : il doit être VIVANT
    # (poll() is None) ici. S'il est déjà mort, son lancement a échoué → on
    # N'exécute PAS la sortie, ce process reste debout (pas de moteur fantôme).
    time.sleep(1.2)
    if proc.poll() is not None:
        core.log("journal.wing.relance_morte", code=proc.returncode)
        return
    core.log("journal.wing.moteur_relance")
    core.vider_journal()             # la ligne doit partir AVANT de mourir
    os._exit(0)


class WingUnplugged(Exception):
    """La wing a été débranchée (erreur USB 'No such device')."""


# ── Santé du flux USB ─────────────────────────────────────────────────────────
#
# Une wing « connectée » peut ne plus rien envoyer. Toute erreur USB autre que
# « débranchée » rendait `None` en silence : un état mort ressemblait à un état
# sain. On mesure donc le flux réel, et on garde le texte de l'erreur USB.
WING_FLUX = {
    "last_ok":   0.0,    # horodatage du dernier paquet valide
    "muette":    False,  # wing présente mais plus aucun paquet
    "erreur":    None,   # dernière erreur USB : (clé i18n, params) ou None —
                         # résolue dans la LANGUE COURANTE à la lecture
                         # (_flux_muet), jamais figée à l'écriture
    "signale":   False,  # le silence a déjà été écrit dans le journal
}
FLUX_SEUIL_S = 3.0       # au-delà, on considère la wing muette


def _flux_ok():
    """Un paquet valide vient d'arriver."""
    import wing_ui as core
    WING_FLUX["last_ok"] = time.time()
    if WING_FLUX["muette"]:
        WING_FLUX["muette"] = False
        WING_FLUX["signale"] = False
        core.log("journal.wing.bavarde")


# Dernière reconnexion déclenchée par le filet « wing muette ».
#
# ⚠️ VOLONTAIREMENT HORS de WING_FLUX, qui est remis à zéro par
# `_release_device()`. Un correctif de ce genre a déjà été retiré une fois
# parce que son garde-fou vivait dans une structure réinitialisée
# par la reconnexion elle-même : il se relançait donc en boucle. Ici le délai
# de garde survit à tout.
RECO_AUTO = {"t": 0.0}
RECO_AUTO_DELAI = 20.0       # jamais plus d'une reconnexion auto / 20 s


def _flux_muet():
    """Aucun paquet exploitable. Ne parle qu'une fois, pas à chaque tour."""
    import wing_ui as core
    maintenant = time.time()
    if WING_FLUX["last_ok"] == 0.0:          # première boucle : on amorce
        WING_FLUX["last_ok"] = maintenant
        return
    if maintenant - WING_FLUX["last_ok"] < FLUX_SEUIL_S:
        return
    WING_FLUX["muette"] = True
    if not WING_FLUX["signale"]:
        WING_FLUX["signale"] = True
        import wing_i18n
        detail = wing_i18n.L("journal.wing.detail_erreur_usb",
                             erreur=WING_FLUX["erreur"]) \
                 if WING_FLUX["erreur"] else ""
        core.log("journal.wing.muette", s=f"{FLUX_SEUIL_S:.0f}", detail=detail)

    # Une wing qui n'envoie plus RIEN pendant plusieurs secondes est
    # inutilisable : on reconnecte. (Ne faire que le signaler a coûté 42 s de panne
    # pour un cas que la reconnexion règle en 2 s.)
    if (etat.E.STATE["want_connected"] and not etat.E.STATE["connecting"]
            and maintenant - RECO_AUTO["t"] > RECO_AUTO_DELAI):
        RECO_AUTO["t"] = maintenant
        core.log("journal.wing.reco_auto")
        threading.Thread(target=lambda: core.connect_wing(force=True, quiet=True),
                         daemon=True).start()


def cycle_dmx(dev):
    """
    Cycle USB avec injection DMX. Lève WingUnplugged si la wing a disparu
    (No such device) → la boucle repasse en 'déconnecté' proprement.
    """
    import wing_ui as core
    _t0_cycle = time.perf_counter()
    try:
        dev.write(wb.EP_OUT, wb.POLL, timeout=wb.TIMEOUT_MS)
    except usb.core.USBError as e:
        # ⚠️ MÊME classificateur que le reste du code (`wing_init._partie_du_bus`,
        # qui lit `errno` ET `backend_error_code` — macOS remplit l'un ou l'autre) :
        # un test local plus étroit ratait un débranchement pendant l'écriture DMX.
        if wing_init._partie_du_bus(e):
            raise WingUnplugged()
        # Toute AUTRE erreur : on la garde. Avant, elle était perdue et la
        # boucle tournait dans le vide sans que personne puisse le savoir.
        import wing_i18n
        WING_FLUX["erreur"] = wing_i18n.L("err.usb.ecriture_errno",
                                          errno=e.errno, e=e)
        time.sleep(0.05)
        return None
    except Exception as e:
        import wing_i18n
        WING_FLUX["erreur"] = wing_i18n.L("err.usb.ecriture_type",
                                          type=type(e).__name__, e=e)
        time.sleep(0.1)
        return None
    etat.E.BOUCLE["t_write"] = (time.perf_counter() - _t0_cycle) * 1000
    _t_read = time.perf_counter()
    data = wb.read_pkt(dev, timeout_ms=300)
    etat.E.BOUCLE["t_read"] = (time.perf_counter() - _t_read) * 1000

    # ── Quels paquets envoyer ce tour-ci ? ───────────────────────────────────
    # Chaque écriture coûte son écriture PLUS son drain (~10 ms). Les univers DMX
    # ne partent que si la sortie est active, ou une fois par seconde pour
    # maintenir le blackout. La carte des LEDs, elle, part À CHAQUE TOUR — voir
    # juste en dessous.
    paquets = []
    now = time.time()

    if etat.E.DMX["enabled"]:
        paquets.append(wb.LED_A[:8] + bytes(etat.E.DMX["buf"][0]))   # XLR A
        paquets.append(wb.LED_B[:8] + bytes(etat.E.DMX["buf"][1]))   # XLR B
        etat.E.ENVOI["dmx"] = now
    elif now - etat.E.ENVOI["dmx"] >= 1.0:
        paquets.append(wb.LED_A)                              # blackout
        paquets.append(wb.LED_B)
        etat.E.ENVOI["dmx"] = now

    # ⚠️ La carte des LEDs part à CHAQUE tour, même inchangée : c'est cette
    # écriture (et son drain) qui entretient l'échange avec la wing. Ne l'envoyer
    # que si elle change effondre le cycle au repos à 337 ms (2,8 Hz) — les faders
    # ne sont plus échantillonnés que 3 fois par seconde.
    paquets.append(wb.CMD_264[:4] + bytes(etat.E.LED["buf"]))

    _t_ecr = time.perf_counter()
    etat.E.BOUCLE["n_pkt"] = len(paquets)
    for pkt in paquets:
        try:
            dev.write(wb.EP_OUT, pkt, timeout=wb.TIMEOUT_MS)
        except Exception as e:
            # 👁 Ne plus avaler EN SILENCE (audit du 25/09/2026) : une sortie DMX
            # ou une carte de LEDs qui n'arrive plus à la wing était invisible.
            # On ne lève toujours pas — un paquet de LED perdu ne doit pas
            # arrêter la boucle —, mais on compte, et l'interface l'affiche
            # (pastille Bridge). Contrôle test_ecritures_usb_comptees.
            etat.E.BOUCLE["ecritures_ko"] = etat.E.BOUCLE.get("ecritures_ko", 0) + 1
            etat.E.BOUCLE["ecriture_err"] = f"{type(e).__name__}: {e}"[:120]
        # ⚠️ NE PAS RÉDUIRE ce délai. Essayé à 1 ms : la cadence
        # s'est EFFONDRÉE de 17 Hz à 2,8 Hz (324 ms par tour). Le drain ne perd
        # pas du temps, il VIDE la file de la wing — sans lui les paquets
        # s'accumulent et la lecture suivante bloque. Mesuré, pas supposé.
        wb.drain(dev, 2)
    etat.E.BOUCLE["t_ecr"] = (time.perf_counter() - _t_ecr) * 1000
    return data


# Ports d'écoute DMX réseau. Constantes de module (et non des littéraux) pour
# que le contrôle test_dmx_local écoute sur un port LIBRE : sur une machine où
# l'app tourne déjà, 6454/5568 sont pris et ses paquets de test partaient chez
# elle.
ARTNET_PORT = 6454
SACN_PORT = 5568


def _source_dmx_acceptee(ip: str, local_seulement: bool) -> bool:
    """Un paquet DMX réseau venant de `ip` est-il accepté ?

    « Local uniquement » (réglage `dmx_local`) : seule l'adresse de bouclage
    (127.0.0.0/8, ::1) passe — la cible du projet est MA3 onPC sur CETTE
    machine. ⚠️ Filtre sur la SOURCE plutôt que `bind("127.0.0.1")` : le sACN
    arrive en MULTICAST (239.255.x.y), et une socket liée à une adresse
    unicast ne reçoit plus le multicast. Contrôle test_dmx_local."""
    if not local_seulement:
        return True
    try:
        import ipaddress
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def dmx_listener():
    """
    Écoute le sACN (E1.31, UDP 5568 multicast) et l'Art-Net (UDP 6454)
    émis par grandMA3, et remplit DMX["buf"] pour l'univers configuré.
    """
    import select as sel
    import socket
    import wing_ui as core

    art = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    art.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        art.bind(("", ARTNET_PORT))
    except OSError:
        art = None
        core.log("journal.dmx.artnet_occupe")

    sacn      = None
    sacn_unis = None

    while True:
        etat.E.DMX["t_tour"] = time.time()      # battement de cœur — voir
                                               # core.threads_morts()
        unis = tuple(etat.E.DMX["uni"])
        local = bool(etat.E.SETTINGS.get("dmx_local", False))

        # (Re)créer la socket sACN si les univers — ou le mode local — ont
        # changé : l'adhésion multicast dépend de l'interface.
        if sacn is None or (unis, local) != sacn_unis:
            if sacn:
                try: sacn.close()
                except Exception: pass
            sacn = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sacn.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sacn.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            except (AttributeError, OSError):
                pass
            try:
                sacn.bind(("", SACN_PORT))
            except OSError as e:
                core.log("journal.dmx.sacn_ko", err=e)
                sacn = None
            if sacn is not None:
                # Join multicast pour chaque univers (facultatif : unicast OK sans)
                for u in set(unis):
                    try:
                        group = socket.inet_aton(f"239.255.{(u >> 8) & 0xff}.{u & 0xff}")
                        # Local : adhésion sur l'interface de bouclage, là où
                        # MA3 onPC émet quand on lui donne 127.0.0.1.
                        mreq  = group + socket.inet_aton("127.0.0.1" if local
                                                         else "0.0.0.0")
                        sacn.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)
                    except OSError:
                        core.log("journal.dmx.multicast_ko")
                        break
            sacn_unis = (unis, local)

        socks = [s for s in (sacn, art) if s]
        if not socks:
            time.sleep(1)
            continue

        ready, _, _ = sel.select(socks, [], [], 0.5)
        for s in ready:
            try:
                data, expediteur = s.recvfrom(1024)
            except OSError:
                continue
            if not _source_dmx_acceptee(expediteur[0], local):
                etat.E.DMX["refuses"] += 1
                continue

            # ── sACN / E1.31 ──────────────────────────────────────────
            if s is sacn and len(data) > 126 and data[4:12] == b"ASC-E1.1":
                pkt_uni = int.from_bytes(data[113:115], "big")
                if pkt_uni in unis and data[125] == 0:     # start code 0
                    dmx = data[126:126 + 512]
                    for idx in (0, 1):
                        if unis[idx] == pkt_uni:
                            etat.E.DMX["buf"][idx][:len(dmx)] = dmx
                    etat.E.DMX["source"] = "sACN"
                    etat.E.DMX["_count"] += 1

            # ── Art-Net (ArtDMX) ──────────────────────────────────────
            elif s is art and len(data) > 18 and data[:8] == b"Art-Net\x00":
                opcode = int.from_bytes(data[8:10], "little")
                if opcode == 0x5000:
                    pkt_uni = int.from_bytes(data[14:16], "little") + 1  # Art-Net 0-based
                    if pkt_uni in unis:
                        length = int.from_bytes(data[16:18], "big")
                        dmx = data[18:18 + min(length, 512)]
                        for idx in (0, 1):
                            if unis[idx] == pkt_uni:
                                etat.E.DMX["buf"][idx][:len(dmx)] = dmx
                        etat.E.DMX["source"] = "Art-Net"
                        etat.E.DMX["_count"] += 1

        # Paquets/seconde
        now = time.time()
        if now - etat.E.DMX["_t"] >= 1.0:
            etat.E.DMX["pps"]    = etat.E.DMX["_count"]
            etat.E.DMX["_count"] = 0
            etat.E.DMX["_t"]     = now


def _generation_perimee(gen) -> bool:
    """Cette boucle a-t-elle été remplacée par une plus récente ?
    `gen=None` : `_usb_boucle` appelée directement, hors superviseur (tests
    seulement) — elle n'est alors retirée que par USB_ARRET. `usb_loop`, lui,
    fixe TOUJOURS une génération."""
    import wing_ui as core
    return gen is not None and etat.E.USB_GEN != gen


def _usb_boucle(gen=None):
    import wing_ui as core
    prev_faders   = None
    prev_encs     = None
    startup_skip  = 3
    ENC_IS32      = (True, False, True, False)
    last_mode     = "idle"
    # Poignée USB du tour précédent. Sert à repérer une liaison NEUVE — voir le
    # bloc « valeurs fantômes » plus bas, qui explique pourquoi le changement de
    # mode ne suffisait pas.
    dernier_dev   = None

    while True:
        etat.E.BOUCLE["t_tour"] = time.time()      # battement de cœur, à chaque tour
        # 🛟 FILET PAR TOUR (audit du 25/09/2026). Un tour qui lève ne doit
        # PLUS tuer le thread : avant, une seule exception (profil mal typé,
        # valeur inattendue de MA3…) gelait la wing jusqu'à un clic manuel.
        # On journalise, on compte, on repart d'une ligne de base propre au
        # tour suivant. Contrôle test_profil_mal_type (smoke_securite.py).
        try:
            # 🔢 Remplacée par une boucle plus récente (connect_wing) : on se
            # retire SANS toucher à rien — ni USB_SORTIE (il appartient à la
            # génération courante), ni la poignée (c'est celle de la neuve).
            if _generation_perimee(gen):
                return
            # Arrêt demandé (redémarrage du moteur) : on sort de la boucle AVANT
            # de relancer une lecture, et on le confirme. C'est ce qui permet à
            # arreter_usb() de libérer l'interface sans couper une lecture en vol.
            if USB_ARRET.is_set():
                USB_SORTIE.set()
                return

            # ── Capture firmware, phase USB exclusive : l'app se RETIRE du bus ────
            # Pendant l'enregistrement + le nettoyage USBPcap (drapeau
            # `usb_exclusif`, posé par wing_firmware_capture pour les seules phases
            # 3-4 + désinstallation), la capture installe USBPcap, redémarre les
            # root hubs (attache/détache du filtre de classe) et laisse grandMA2
            # onPC pousser le firmware. Si usb_loop continue à énumérer / revendiquer
            # / poller la wing pendant ce temps, il entre en concurrence : wing
            # « muette », et surtout le remontage des root hubs pour DÉTACHER
            # USBPcap échoue (hub occupé) → USBPcap.sys reste dans la pile de la
            # wing, wing morte jusqu'au reboot (constaté en réel).
            # Les phases 5-7 de l'assistant (fermer MA2, rebrancher, attendre la
            # connexion) NE posent PAS ce drapeau — elles ont au contraire besoin
            # que usb_loop tourne pour que Wing Bridge reprenne la wing.
            try:
                import wing_firmware_capture as _fwc
                _capture_exclu = bool(_fwc.CAPTURE_STATE.get("usb_exclusif"))
            except Exception:
                _capture_exclu = False
            if _capture_exclu:
                if etat.E.DEV[0] is not None:
                    _release_device()
                time.sleep(1.0)
                continue

            dev = etat.E.DEV[0]
            if dev is None:
                # Auto-reconnexion : si l'utilisateur veut la wing active et qu'elle
                # a disparu, on retente en douceur (toutes les AUTO["interval"] s,
                # silencieusement). full_init échoue vite si la wing est absente ;
                # dès qu'elle réapparaît, l'essai réussit et le bridge reprend.
                # Verrou « attend un rebranchement » : après un échec d'init, un
                # nouvel essai est IMPOSSIBLE à réussir tant que la wing n'a pas
                # été remise sous tension (cf. _echec_init). On ne le lève que
                # lorsqu'elle a réellement disparu du bus — preuve du débranchement.
                absente = wing_init.wing_absente()

                if etat.E.AUTO["attend_rebranchement"]:
                    # Auto-démarrage TARDIF : après un échec firmware, la wing peut finir son
                    # boot seule et repasser applicative SANS quitter le bus (délai mesuré ~7 s à
                    # > 25 s, banc `essai_autoboot.py`). On surveille donc aussi la VITESSE :
                    # présente et applicative → verrou levé, reprise sans renvoi de firmware (CAS 1).
                    # Lecture seule : énumération + `dev.speed`, aucune poignée.
                    if not absente and \
                            wing_init.etat_wing(wing_init._trouver()) == "operationnelle":
                        etat.E.AUTO["absente_depuis"] = 0.0
                        etat.E.AUTO["attend_rebranchement"] = False
                        etat.E.AUTO["echecs"] = 0
                        etat.E.AUTO["interval"] = 2.0
                        etat.E.AUTO["last_try"] = 0.0
                        wing_etat_materiel.effacer_etat_materiel()
                        core.log("journal.wing.autodemarrage_tardif")
                        time.sleep(0.2)
                        continue
                    # ⚠️ Il faut une absence DURABLE, pas un clignement : une wing coincée en
                    # bootloader décroche seule du bus ~10 s pendant ses reboots. Lever le verrou
                    # là-dessus renvoyait le firmware et l'entretenait dans son blocage. Une vraie
                    # coupure humaine dure bien plus de 5 s (ABSENCE_REELLE_S).
                    if not absente:
                        etat.E.AUTO["absente_depuis"] = 0.0
                    elif etat.E.AUTO["absente_depuis"] == 0.0:
                        etat.E.AUTO["absente_depuis"] = time.time()
                    elif time.time() - etat.E.AUTO["absente_depuis"] >= core.ABSENCE_REELLE_S:
                        etat.E.AUTO["absente_depuis"] = 0.0
                        etat.E.AUTO["attend_rebranchement"] = False
                        etat.E.AUTO["echecs"] = 0
                        etat.E.AUTO["interval"] = 2.0
                        etat.E.AUTO["last_try"] = 0.0
                        # 🔑 Absence DURABLE = preuve de coupure. On oublie le
                        # dernier envoi de firmware : la wing qu'on retrouvera aura
                        # droit à son unique essai (anti-martèlement).
                        wing_etat_materiel.effacer_etat_materiel()
                        # ⚠️ Formulation neutre À DESSEIN. Ce message se déclenche
                        # dès que la wing quitte le bus — ce qui arrive aussi
                        # SANS débranchement (re-énumération pendant un
                        # redémarrage). Il annonçait « Wing débranchée » alors que
                        # personne n'avait touché au câble.
                        core.log("journal.wing.liberee_bus")
                    time.sleep(0.5)
                    continue

                # Rien à tenter tant que la wing n'est pas sur le bus. Sans ce
                # garde-fou, on appelait full_init toutes les 2 s pour s'entendre
                # répondre « wing non trouvée » — du bruit pur dans le journal.
                if absente:
                    etat.E.AUTO["essais_presence"] = 0     # nouvelle présence à venir
                    # 🔑 Le blocage persistant se lève AUSSI ici : après un redémarrage de l'app,
                    # `attend_rebranchement` est faux, et une wing débranchée entre-temps n'aurait
                    # jamais levé le blocage. Un verrou qui ne se lève pas est pire que le bug.
                    if etat.E.AUTO["absente_depuis"] == 0.0:
                        etat.E.AUTO["absente_depuis"] = time.time()
                    elif time.time() - etat.E.AUTO["absente_depuis"] >= core.ABSENCE_REELLE_S:
                        etat.E.AUTO["absente_depuis"] = 0.0
                        if wing_etat_materiel.blocage_connu():
                            core.log("journal.wing.debranchee_blocage")
                        wing_etat_materiel.effacer_etat_materiel()
                    time.sleep(0.5)
                    continue
                etat.E.AUTO["absente_depuis"] = 0.0

                if etat.E.STATE["want_connected"] and not etat.E.STATE["connecting"]:
                    now = time.time()
                    # Demande HUMAINE de reconnexion forcée en attente : on la
                    # sert DÈS QUE POSSIBLE (on court-circuite l'espacement progressif)
                    # et c'est CETTE boucle — seule propriétaire du device — qui exécute
                    # le renvoi firmware, jamais le thread HTTP. Consommée une fois.
                    force_op = wing_init.RECO_MUETTE.get("force_demande", False)
                    if force_op or now - etat.E.AUTO["last_try"] >= etat.E.AUTO["interval"]:
                        etat.E.AUTO["last_try"] = now
                        # ⚠️ UNE LIGNE À L'APPARITION, et une seule. Sans elle, un
                        # branchement qui échoue ne laissait AUCUNE trace : ni « je
                        # l'ai vue », ni « j'ai essayé », ni « ça a raté ». On ne
                        # pouvait donc pas distinguer « l'app ne l'a pas vue » de
                        # « l'init a échoué » — les deux donnaient un journal vide.
                        # Constaté sur un branchement raté.
                        etat.E.AUTO["essais_presence"] += 1
                        if etat.E.AUTO["essais_presence"] == 1 and not force_op:
                            core.log("journal.wing.detectee")
                        # La reprise du bridge est faite par `connect_wing` : le SEUL endroit où une
                        # connexion réussit, donc le seul qui la voie à coup sûr (démarrage et bouton
                        # compris).
                        #
                        # 🔬 `force=True` ici. `force=False` a été essayé (4 essais réels,
                        # comportement identique) : hypothèse réfutée — la vraie variable était le
                        # câble USB. Ne pas retenter sans nouvelle preuve.
                        if force_op:
                            wing_init.RECO_MUETTE["force_demande"] = False
                            core.log("journal.wing.reco_forcee")
                            core.connect_wing(force=True, quiet=False,
                                              force_operateur=True)
                        else:
                            core.connect_wing(force=True, quiet=True)
                time.sleep(0.3)
                continue

            # ⚠️ TOUTE LIAISON NEUVE REPART D'UNE LIGNE DE BASE. Sans ça, le
            #    premier paquet du retour est comparé à l'état d'AVANT la coupure
            #    et MA3 reçoit des ordres que personne n'a donnés (relevé : 9 avant
            #    le correctif). Se raccrocher à la POIGNÉE et non au mode : la
            #    boucle ne voit jamais le passage idle→bridge d'une reconnexion.
            #    → docs/HARDWARE.md#valeurs-fantomes-apres-une-reconnexion · contrôle test_reconnexion_sans_fantomes
            if dev is not dernier_dev:
                dernier_dev  = dev
                prev_faders  = None
                prev_encs    = None
                startup_skip = 3

            _t_cycle = time.perf_counter()
            try:
                data = core.cycle_dmx(dev)
            except WingUnplugged:
                # Une boucle PÉRIMÉE qui revient d'un tour long ne doit surtout
                # pas relâcher la poignée : ce serait celle de la boucle neuve.
                if _generation_perimee(gen):
                    return
                # Arrachage détecté. Pas besoin de recliquer : tant que l'utilisateur
                # veut la wing (want_connected), la boucle la reconnecte toute seule
                # dès le rebranchement. On mémorise le mode pour reprendre le bridge.
                with etat.E.LOCK:
                    if etat.E.STATE["mode"] == "bridge":
                        etat.E.STATE["resume_mode"] = "bridge"
                core.log("journal.wing.debranchee")
                _release_device()
                # Nouvel épisode de reconnexion : compteur d'escalade remis à
                # zéro (voir wing_init.RECO_MUETTE). Chaque arrachage distinct repart
                # de zéro ; le renvoi firmware d'escalade ne vaut que pour cet épisode.
                wing_init._reco_muette_reset(episode=True)
                etat.E.AUTO["last_try"] = time.time()   # petit délai avant le 1er essai
                continue

            # 🔢 2e point de contrôle, juste après la lecture : c'est LÀ qu'un
            # tour peut durer (lecture de 300 ms, écritures). Une boucle
            # remplacée pendant ce temps ne traite pas son paquet — sinon elle
            # enverrait à MA3 les mêmes gestes que la neuve.
            if _generation_perimee(gen):
                return

            core._boucle_tic((time.perf_counter() - _t_cycle) * 1000,
                             vide=(data is None or len(data) < 96))

            # Positions de fader retenues par la limitation de débit : on les
            # libère dès que leur créneau arrive, quoi qu'il se passe par ailleurs.
            core.faders_vider_attente()


            if data is None or len(data) < 96:
                if data is not None and not WING_FLUX["erreur"]:
                    WING_FLUX["erreur"] = f"paquet trop court ({len(data)} o, 96 attendus)"
                _flux_muet()
                time.sleep(0.016)
                continue
            _flux_ok()

            mode = etat.E.STATE["mode"]
            if mode != last_mode:
                # Changement de mode → re-baseline pour éviter les faux positifs
                prev_faders = None
                prev_encs   = None
                startup_skip = 3
                last_mode = mode

            state  = wb.parse_state(data)
            # Remet les faders dans l'ordre physique F1..F8 (l'ordre brut des octets
            # était décalé : 7 8 1 2 3 4 5 6). Si l'ordre reste faux, ajuste FADER_ORDER.
            _fv = state["faders"]
            state["faders"] = [_fv[k] for k in core.FADER_ORDER]
            events = wb.parse_events(data)

            # ── Feedback LED : la LED d'un bouton suit l'appui (tous modes) ──────
            if etat.E.LED["feedback"] and not etat.E.VEGAS["on"]:
                for btn_id, pressed in events:
                    # Au relâchement on ne retombe pas sur une veilleuse fixe mais
                    # sur l'état réel de MA3 : sinon la LED d'un executor qui tourne
                    # s'éteindrait dès qu'on lâche le bouton.
                    if pressed:
                        etat.E.BOUTONS_ENFONCES.add(btn_id)
                        core.set_btn_led(btn_id, core.LED_FULL)
                    else:
                        etat.E.BOUTONS_ENFONCES.discard(btn_id)
                        core.set_btn_led(btn_id, core.niveau_led_ma3(f"0x{btn_id:02x}"))

            # Rafraîchissement périodique des LED depuis MA3, à ~8 Hz. La sonde
            # n'écrit que toutes les 0,2 s : ce rythme n'apporte donc rien de plus
            # sur l'ÉTAT, mais il est imposé par le CLIGNOTEMENT d'un fader non
            # rattrapé, qui doit être net. Ne pas descendre plus bas sans raison :
            # chaque passage coûte du temps dans une boucle à ~30 Hz.
            if etat.E.LED["ma3"] and not etat.E.VEGAS["on"]:
                _maintenant = time.time()
                if _maintenant - etat.E.LED_RAFRAICHI["t"] >= 0.12:
                    etat.E.LED_RAFRAICHI["t"] = _maintenant
                    _t_led = time.perf_counter()
                    core.rafraichir_leds_ma3()
                    core.pickup_verifier_repos(state["faders"])
                    etat.E.BOUCLE["leds_ms"] = (time.perf_counter() - _t_led) * 1000

            if prev_faders is None:
                prev_faders = state["faders"][:]
                prev_encs   = list(state["encoders"])
                continue
            if startup_skip > 0:
                startup_skip -= 1
                prev_faders = state["faders"][:]
                prev_encs   = list(state["encoders"])
                continue

            # ── Mode LEARN : capture le premier événement ─────────────────────────
            if mode == "learn":
                if etat.E.STATE["last_event"] is None:
                    evenement = None
                    for btn_id, pressed in events:
                        if pressed:
                            evenement = {"kind": "button", "key": f"0x{btn_id:02x}"}
                            break
                    else:
                        for i, (pv, cv) in enumerate(zip(prev_faders, state["faders"])):
                            if abs(cv - pv) > 5:
                                evenement = {"kind": "fader", "index": i}
                                break
                        else:
                            for i, (pe, ce) in enumerate(zip(prev_encs, state["encoders"])):
                                if ce != pe:
                                    evenement = {"kind": "encoder", "index": i}
                                    break
                    if evenement is not None:
                        core.etat_poser(last_event=evenement)

            # ── Mode BRIDGE : comportement complet ────────────────────────────────
            elif mode == "bridge":
                # 🔒 Le verrou ne couvre que l'instantané : `enc_attr_selon_ma3()` peut lancer
                # un `pgrep` (jusqu'à 1 s) — sous LOCK, dans cette boucle à 30 Hz, il gelait
                # faders, boutons et /api/status.
                with etat.E.LOCK:
                    faders_map = [dict(x) for x in etat.E.PROFILE["faders"]]
                    enc_step   = etat.E.PROFILE["enc_step"]
                    enc_attr_configures = (etat.E.STATE["enc_attr"] or [None] * 4)[:]
                enc_attr = core.enc_attr_selon_ma3(enc_attr_configures)

                for i, (pv, cv) in enumerate(zip(prev_faders, state["faders"])):
                    if cv != pv:
                        core.send_fader(i, faders_map[i], cv)

                # Les roues PILOTENT ici, en OSC (`Attribute <nom> at ±<pas>`, attribut pris
                # dans le GROUPE actif du profil). Ce qui reste partiel, c'est le SUIVI de
                # l'Encoder Bar de MA3 : « le suivi n'est pas fini » ≠ « les roues ne font rien ».
                for i, (pe, ce, i32) in enumerate(zip(prev_encs, state["encoders"], ENC_IS32)):
                    if ce != pe:
                        delta = wb.enc_delta(ce, pe, i32)
                        attr  = enc_attr[i] if i < len(enc_attr) else None
                        if attr:
                            step = enc_step * delta
                            sign = "+" if step >= 0 else "-"
                            v    = abs(step)
                            vs   = str(int(v)) if v == int(v) else f"{v:.1f}"
                            etat.E.OSC.send_message("/cmd", f"Attribute {attr} at {sign} {vs}")
                            core.log(f"ENC{i+1} {attr} {sign}{vs}")

                for btn_id, pressed in events:
                    if pressed:
                        core.handle_button_bridge(btn_id)
                    else:
                        core.handle_button_release(btn_id)

            prev_faders = state["faders"][:]
            prev_encs   = list(state["encoders"])
            time.sleep(0.016)
        except Exception as e:
            _erreur_tour(e)
            # Ligne de base neuve : le tour interrompu a pu laisser prev_*
            # à moitié à jour — comparer contre lui enverrait des gestes que
            # personne n'a faits (même règle que les « valeurs fantômes »).
            prev_faders = None
            prev_encs   = None
            time.sleep(0.05)


# ── Filet par tour et superviseur de la boucle USB ───────────────────────────
#
# 🔴 FAILLE CRITIQUE (audit du 25/09/2026). `usb_loop` n'avait AUCUN filet hors
# `WingUnplugged`, et rien ne la relançait : `wing_diagnostic._hook_thread`
# ne faisait que SIGNALER sa mort (`THREAD_MORT`). Une exception dans un tour
# — mesuré avec un profil importé aux faders mal typés — gelait la wing en
# plein show jusqu'à un clic sur « Connecter ».
#
# Deux étages, parce qu'aucun ne suffit seul :
#   1. `_erreur_tour` : le tour fautif est abandonné, la boucle CONTINUE
#      (faders, boutons, LEDs, DMX restent servis) ;
#   2. `usb_loop` (superviseur) : si la boucle meurt quand même (erreur hors
#      du filet), on la RELANCE, avec un délai croissant. Au-delà de
#      USB_RELANCE_MAX morts en USB_RELANCE_FENETRE_S, on abandonne et on
#      laisse l'exception remonter : `threading.excepthook` pose alors
#      `THREAD_MORT`, et l'interface affiche honnêtement « boucle morte »
#      au lieu de relancer en boucle un défaut permanent.
#
# Contrôle test_profil_mal_type (smoke_securite.py).
USB_RELANCE_MAX = 5
USB_RELANCE_FENETRE_S = 60.0
USB_RELANCE_DELAI_S = 1.0        # délai avant relance, × nombre de morts récentes
ERREUR_TOUR_JOURNAL_S = 10.0     # même erreur : une ligne toutes les 10 s au plus
_DERNIERE_ERREUR = {"cle": None, "t": 0.0}


def _ou(e: BaseException) -> str:
    """« fichier:ligne » de l'endroit où l'exception est née — sans ça, une
    ligne de journal dit QUOI mais pas OÙ, et on ne sait pas quoi corriger."""
    import traceback
    tb = traceback.extract_tb(e.__traceback__)
    if not tb:
        return "?"
    f = tb[-1]
    return f"{os.path.basename(f.filename)}:{f.lineno}"


def _erreur_tour(e: Exception):
    """Un tour de boucle a levé : on compte, on journalise (sans noyer)."""
    import wing_ui as core
    etat.E.BOUCLE["erreurs_tour"] = etat.E.BOUCLE.get("erreurs_tour", 0) + 1
    cle = (type(e).__name__, str(e)[:120])
    maintenant = time.time()
    # À 30 Hz, une erreur qui se répète à chaque tour écrirait 30 lignes par
    # seconde : on ne parle qu'à la PREMIÈRE, puis au plus toutes les 10 s.
    if cle != _DERNIERE_ERREUR["cle"] or \
            maintenant - _DERNIERE_ERREUR["t"] >= ERREUR_TOUR_JOURNAL_S:
        _DERNIERE_ERREUR.update(cle=cle, t=maintenant)
        core.log("journal.wing.erreur_tour", type=cle[0], err=cle[1],
                 ou=_ou(e), n=etat.E.BOUCLE["erreurs_tour"])


def usb_loop(gen=None):
    """Point d'entrée du thread USB : fait tourner `_usb_boucle`, la relance
    si elle meurt. Une sortie VOLONTAIRE (USB_ARRET) ou une génération
    périmée (boucle remplacée) n'est jamais relancée."""
    import wing_ui as core
    # Lancée sans génération (démarrage de l'app, tests) : elle prend la
    # COURANTE. Sans ça, la boucle du démarrage (gen=None) n'aurait jamais été
    # retirée par la suivante — et le doublon réapparaissait à la 1re reprise.
    if gen is None:
        gen = etat.E.USB_GEN
    morts = []
    while True:
        if _generation_perimee(gen):
            return
        try:
            _usb_boucle(gen)
            return
        except Exception as e:
            maintenant = time.time()
            morts = [t for t in morts
                     if maintenant - t < USB_RELANCE_FENETRE_S] + [maintenant]
            etat.E.BOUCLE["relances"] = etat.E.BOUCLE.get("relances", 0) + 1
            if len(morts) > USB_RELANCE_MAX:
                core.log("journal.wing.boucle_abandon", type=type(e).__name__,
                         err=str(e)[:120], ou=_ou(e), n=len(morts),
                         s=f"{USB_RELANCE_FENETRE_S:.0f}")
                raise          # → threading.excepthook → THREAD_MORT, visible
            delai = min(USB_RELANCE_DELAI_S * len(morts), 10.0)
            core.log("journal.wing.boucle_relancee", type=type(e).__name__,
                     err=str(e)[:120], ou=_ou(e), s=f"{delai:.0f}")
            time.sleep(delai)
