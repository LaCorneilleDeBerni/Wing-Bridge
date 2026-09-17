"""État MATÉRIEL persistant de la wing : l'anti-martèlement du renvoi de
firmware et le blocage connu, qui doivent SURVIVRE à un redémarrage du moteur.

Sorti de `wing_init.py` (audit du 25/09/2026, point D3) : un petit fichier
horodaté et ses règles de lecture n'ont rien à faire dans le module qui
dialogue avec la wing. `wing_init.full_init` consulte ceci avant d'envoyer
le firmware ; `wing_connexion` l'efface quand la wing quitte le bus ;
`wing_firmware_capture` y range son propre drapeau.

⚠️ Aucun import de `wing_init` au niveau du module (ce serait circulaire :
`wing_init` importe celui-ci) — les rares appels vers lui sont paresseux.
"""

import os
import time
from pathlib import Path


def _wi():
    """`wing_init`, importé paresseusement (import circulaire sinon). Lu À
    CHAQUE APPEL : un test qui remplace `wing_init._trouver` est respecté."""
    import wing_init
    return wing_init


# ── Anti-martèlement QUI SURVIT À UN REDÉMARRAGE DU MOTEUR ────────────────────
#
# 🔴 RÈGLE (établie au banc `essai_wing_propre.py`) : une wing coincée en
# bootloader ne l'est PAS par défaut matériel. C'est le
# RENVOI RÉPÉTÉ de firmware qui la ré-enfonce : chaque envoi sur un bootloader
# le fait re-rebooter.
#
# ⚠️ SA SECONDE MOITIÉ EST RÉFUTÉE. « Un envoi UNIQUE après une
# vraie coupure marche à tous les coups » : le banc `essai_sortie.py` a relevé
# **0 réussite sur 9**, chaque envoi suivant une coupure vérifiée (disparition
# PUIS réapparition). La coupure est peut-être NÉCESSAIRE, elle n'est pas
# SUFFISANTE. Ne pas se rassurer avec cette phrase en lisant un échec.
#
# La PREMIÈRE moitié tient et justifie l'anti-martèlement ci-dessous : ne pas
# renvoyer sur un bootloader qui vient de refuser reste la bonne conduite.
#
# Le verrou en mémoire (DERNIER_ECHEC + attend_rebranchement côté wing_ui) évite
# le martèlement DANS un process. Mais le bouton « Réinitialiser » — pressé
# après chaque build — lance un process NEUF qui repart de zéro et renvoie le
# firmware. D'où « ça recommence à chaque build ».
#
# Le remède : n'envoyer le firmware QU'UNE FOIS par présence sur le bus, et
# faire SURVIVRE cette mémoire à un redémarrage, via un petit fichier horodaté.
# Un process neuf qui voit « firmware envoyé il y a < FW_REHAMMER_S et wing
# toujours en bootloader » ne renvoie RIEN — comme le fait le script manuel.
#
# ⚠️ Le fichier est effacé dès que la wing quitte le bus (preuve de coupure) ou
# qu'un init réussit : une wing fraîchement rebranchée a droit à son unique
# essai. wing_ui injecte le chemin ; sans lui (scripts standalone), no-op.
ETAT_FICHIER = None            # Path, injecté par wing_ui
FW_REHAMMER_S = 30.0           # en deçà, un renvoi de firmware = martèlement


def _ecrire_etat_fichier(d: dict):
    """Écriture ATOMIQUE de `ETAT_FICHIER` (temp-file + os.replace) — même
    motif que le reste du projet (sauvegarde auto, raccourcis XML, cache
    firmware). Partagée avec `wing_firmware_capture.py` (même fichier, même
    règle) : ce fichier porte l'anti-martèlement du renvoi de firmware — une
    coupure en plein milieu de l'écriture DIRECTE pouvait laisser un JSON
    tronqué, illisible au prochain process, qui perdait alors SILENCIEUSEMENT
    l'état de blocage (`bloque`) ou l'horodatage (`fw_envoye_t`) protégeant
    contre un renvoi de firmware trop rapproché."""
    import json
    if ETAT_FICHIER is None:
        return
    tmp = ETAT_FICHIER.with_suffix(".part")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, ETAT_FICHIER)


def _marquer_firmware_envoye():
    """Horodate l'envoi du firmware, pour l'anti-martèlement inter-process."""
    if ETAT_FICHIER is None:
        return
    try:
        _ecrire_etat_fichier({"fw_envoye_t": time.time()})
    except Exception:
        pass


def _marquer_blocage():
    """Retient qu'un envoi de firmware a ÉCHOUÉ à démarrer sur ce bootloader.

    🔑 CE QUI MANQUAIT POUR ÊTRE FIABLE.

    L'anti-martèlement était un MINUTEUR de 30 s. Il protégeait bien contre des
    essais rapprochés dans une même session, mais pas du tout contre le cas
    réel : l'app quittée puis relancée plus tard, sur une wing toujours coincée.
    Relevé : échec à 10:30:58, app relancée à 10:45:16, soit 14 minutes plus
    tard : la fenêtre était expirée, l'app a retenté, regaspillé l'unique
    tentative, et redemandé un débranchement.

    Un blocage n'est pas une question de DÉLAI : tant que la wing n'a pas perdu
    son alimentation, réessayer ne peut pas aboutir — quel que soit le temps
    écoulé. On persiste donc un ÉTAT, effacé seulement par la preuve d'une
    coupure (la wing quitte le bus) ou par un init réussi.
    """
    if ETAT_FICHIER is None:
        return
    try:
        import json
        d = {}
        if ETAT_FICHIER.exists():
            try:
                d = json.loads(ETAT_FICHIER.read_text(encoding="utf-8"))
            except Exception:
                d = {}
        d["bloque"] = True
        d["bloque_t"] = time.time()
        # 🔑 On retient QUI était bloqué. Un rebranchement ré-énumère la wing,
        # qui reçoit alors (presque toujours) une nouvelle adresse USB. C'est
        # notre seul indice qu'une coupure a eu lieu PENDANT QUE L'APP ÉTAIT
        # ARRÊTÉE — cas où l'on ne peut rien observer.
        #
        # ⚠️ HEURISTIQUE, pas une preuve : une adresse peut être réattribuée.
        # C'est pourquoi elle n'est jamais le seul recours — un clic délibéré
        # sur « Connecter la wing » passe outre le blocage (voir full_init).
        # Gardé pour le DIAGNOSTIC seulement — surtout pas comme preuve d'un
        # rebranchement : voir la note dans blocage_connu().
        d["bus"], d["adresse"] = _adresse_courante()
        _ecrire_etat_fichier(d)
    except Exception:
        pass


def _adresse_courante():
    """(bus, adresse) de la wing sur le bus, ou (None, None) si absente."""
    d = _wi()._trouver()
    if d is None:
        return (None, None)
    return (getattr(d, "bus", None), getattr(d, "address", None))


def blocage_connu() -> bool:
    """Ce bootloader a-t-il DÉJÀ refusé de démarrer, coupure non faite depuis ?

    ⚠️ RÉPOND FAUX dès qu'un doute existe. Un blocage qui ne se lève jamais
    serait BIEN PIRE que le bug qu'il corrige : l'app refuserait d'initialiser
    une wing parfaitement saine, sans aucun recours. Quatre choses le lèvent :
      1. la wing quitte durablement le bus (boucle d'auto-reconnexion) ;
      2. un init réussi (`effacer_etat_materiel`) ;
      3. l'adresse USB a changé → la wing a été ré-énumérée, donc rebranchée ;
      4. un clic délibéré sur « Connecter la wing » (`force=True`).
    """
    if ETAT_FICHIER is None:
        return False
    try:
        import json
        d = json.loads(ETAT_FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not d.get("bloque"):
        return False
    # ❌ HEURISTIQUE RÉFUTÉE — ne pas la réintroduire : « adresse USB différente →
    # rebranchement ». La wing RE-ÉNUMÈRE à chaque envoi de firmware (elle
    # reboote) : son adresse change à chaque essai, et le blocage se levait tout
    # seul. L'adresse ne distingue PAS un rebranchement humain d'un reboot.
    #
    # Ce qui lève le blocage : une absence DURABLE du bus (≥ ABSENCE_REELLE_S), un
    # init réussi, ou un clic délibéré sur « Connecter la wing » (force=True).
    if _wi()._trouver() is None:
        return False                      # wing absente : rien à bloquer
    return True


def _firmware_envoye_recemment() -> bool:
    """Un firmware a-t-il été envoyé il y a moins de FW_REHAMMER_S ?"""
    if ETAT_FICHIER is None:
        return False
    try:
        import json
        d = json.loads(ETAT_FICHIER.read_text(encoding="utf-8"))
        return (time.time() - float(d.get("fw_envoye_t", 0))) < FW_REHAMMER_S
    except Exception:
        return False


def effacer_etat_materiel():
    """Oublie le dernier envoi : wing coupée du bus, ou init réussi."""
    if ETAT_FICHIER is None:
        return
    try:
        ETAT_FICHIER.unlink(missing_ok=True)
    except Exception:
        pass


# En deçà, un `bloque` est trop RÉCENT pour être périmé : c'est le cas d'un
# redémarrage rapide (🔄 Réinitialiser juste après un envoi) — le martèlement
# doit y rester interdit. Choisi bien au-dessus de FW_REHAMMER_S (30 s) pour ne
# JAMAIS recouvrir la fenêtre anti-renvoi-rapide.
BLOCAGE_PEREMPTION_DEMARRAGE_S = 120.0


def reconcilier_blocage_au_demarrage() -> bool:
    """AU DÉMARRAGE UNIQUEMENT : lève un `bloque` PÉRIMÉ. Renvoie True si effacé.

    🐛 `bloque` (cf. `blocage_connu`) n'est normalement effacé qu'en
    OBSERVANT la wing quitter durablement le bus — ce que seule une app EN MARCHE
    fait (`usb_loop`, `effacer_etat_materiel`). Si l'app était FERMÉE pendant un
    débranchement/rebranchement PHYSIQUE, ce marqueur périmé survit et refuse, au
    démarrage suivant, une wing pourtant repartie de zéro — sans recours visible.

    On ne peut pas PROUVER après coup qu'une coupure a eu lieu pendant l'arrêt.
    Mais si le dernier envoi de firmware (`fw_envoye_t`) est ANCIEN — bien au-delà
    du cooldown anti-martèlement —, la situation a eu tout le temps de changer :
    on rend à la wing son UNIQUE essai plutôt que de la refuser indéfiniment.

    ⚠️ Ne touche RIEN si le blocage est RÉCENT (< BLOCAGE_PEREMPTION_DEMARRAGE_S) :
    c'est exactement le redémarrage rapide (🔄 Réinitialiser peu après un envoi),
    où le martèlement reste interdit — le cooldown `fw_envoye_t` garde tout son
    rôle. Et ceci ne s'exécute qu'UNE FOIS, au démarrage : le comportement d'une
    app EN MARCHE (usb_loop, blocage_connu) est INCHANGÉ.

    ⚠️ COMPROMIS ASSUMÉ : dans le cas « app relancée longtemps après SANS coupure,
    wing encore coincée », on lèvera le blocage et l'app
    fera UN essai de trop (un reboot de wing), puis se re-bloquera et demandera un
    débranchement. Ce n'est PAS le martèlement d'antan (boucle 2 s) : un seul
    essai au démarrage, puis `attend_rebranchement` re-suspend la boucle. Le coût
    (un reboot) est préférable à refuser pour toujours une wing saine rebranchée.
    """
    if ETAT_FICHIER is None:
        return False
    try:
        import json
        d = json.loads(ETAT_FICHIER.read_text(encoding="utf-8"))
    except Exception:
        return False
    if not d.get("bloque"):
        return False
    # `fw_envoye_t` = repère du cooldown (le même que _firmware_envoye_recemment) ;
    # repli sur `bloque_t` si absent. Un repère à 0 (absent) → réputé très ancien.
    repere = d.get("fw_envoye_t") or d.get("bloque_t") or 0.0
    if time.time() - float(repere) >= BLOCAGE_PEREMPTION_DEMARRAGE_S:
        effacer_etat_materiel()
        return True
    return False
