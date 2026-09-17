"""L'état MUTABLE partagé du moteur — un objet, sans logique.

POURQUOI (audit du 25/09/2026, point D1). Tout cet état vivait en variables
de module de `wing_ui.py`, lu et écrit par ~165 `import wing_ui as core`
paresseux. `docs/ARCHITECTURE.md` le disait en toutes lettres : l'emplacement
de certains états était décidé par l'endroit où le test de fumée les
remplaçait (« monkeypatch »). Conséquences : dépendances cycliques cachées,
`core.PROFILE = p` à un endroit contre `PROFILE.clear()` ailleurs, et des
tests qui devaient sauver puis restaurer des dizaines de noms à la main.

Désormais :
  • tout l'état mutable est un attribut de `Etat` — ce module ne contient AUCUNE
    logique, seulement des valeurs initiales ;
  • le code y accède par `etat.E.<champ>` — `E` est l'instance COURANTE, lue à
    chaque accès (jamais `from etat import E`, qui figerait l'instance) ;
  • un test INJECTE un état neuf et isolé : `with etat.injecter() as e:` —
    tout le moteur voit `e` jusqu'à la sortie du bloc, puis l'état d'origine,
    intact. Plus de liste de noms à sauver et restaurer.

Ce qui N'EST PAS ici : les CONSTANTES (types de fader, niveaux de LED,
chemins par défaut) restent dans leur module ; l'état propre à un module et
lu par lui seul (`wing_reglages.OSC_IN`, `wing_connexion.WING_FLUX`,
`wing_init.DERNIER_ECHEC`…) reste chez son propriétaire.

⚠️ `LOCK` n'est PAS réentrant — voir `wing_ui.etat_poser`.
Contrôle test_etat_injecte (smoke_securite.py).
"""

import contextlib
import threading
import time
from collections import deque

import wing_bridge as wb
import wing_mapper as wm


class Etat:
    """Tout l'état mutable partagé. Aucune méthode : des champs."""

    def __init__(self):
        from pythonosc import udp_client

        # ── Verrou de l'état partagé (STATE / SETTINGS / PROFILE) ──
        self.LOCK = threading.Lock()

        self.STATE = {
            "mode": "idle",          # idle | learn | bridge
            "wing": False,           # wing connectée ?
            "connecting": False,
            "last_event": None,      # {"kind": "button"|"fader"|"encoder", ...}
            "cmd_buf": "",
            "enc_attr": None,        # attributs courants des 4 roues (mode bridge)
            # QUEL groupe de roues est actif (pas seulement ses valeurs) : sans
            # ça, enregistrer renvoyait les roues sur le groupe par défaut.
            "enc_group": 0,
            "dirty": False,          # modifs non enregistrées dans le profil actif ?
            "want_connected": False, # l'utilisateur VEUT-il la wing active ?
            "resume_mode": None,     # mode à restaurer après une reconnexion
        }
        self.PROFILE = wm.new_profile_from_defaults()

        # Réglages MACHINE (≠ profil) — voir wing_ui, « Réglages MACHINE ».
        self.SETTINGS = {
            "ma3_ip": wb.MA3_IP, "ma3_port": wb.MA3_PORT, "osc_in_port": 0,
            "profil_favori": "",     # nom de fichier, "" = aucun
            "suivre_ma3": True,      # suivre la config réelle de MA3 (sonde Lua)
            "fader_pickup": True,    # rattrapage de fader (sonde Lua)
            "verbe_cible": True,     # verbe + executor (Store puis executor)
            # Défaut FALSE : pilotage de l'Encoder Bar jamais éprouvé sur console.
            "encodeurs_ma3": False,
            # DMX réseau « local uniquement » : défaut FALSE (norme du métier).
            "dmx_local": False,
            "plugin_slot": 3,        # slot du pool Plugins pour l'amorce
            "shcuts_horodate": None, # dernier envoi réussi des raccourcis (epoch)
        }
        self.OSC = udp_client.SimpleUDPClient(wb.MA3_IP, wb.MA3_PORT)

        # ── Liaison USB ──
        self.DEV = [None]            # device USB
        # Génération de la boucle USB (voir wing_connexion._generation_perimee).
        self.USB_GEN = 0
        self.AUTO = {
            "last_try": 0.0, "interval": 2.0, "echecs": 0,
            "attend_rebranchement": False,
            "essais_presence": 0,    # essais depuis l'apparition sur le bus
            "absente_depuis": 0.0,   # depuis quand la wing est absente (0 = là)
        }
        self.BOUCLE = {
            "t_sec": 0.0, "n": 0, "hz": 0.0,      # cadence mesurée
            "cycle_ms": 0.0, "cycle_max": 0.0,    # aller-retour USB
            "leds_ms": 0.0, "vides": 0,
            "t_write": 0.0, "t_read": 0.0, "t_ecr": 0.0, "n_pkt": 0,
            "signale": False, "lent_n": 0,
            "t_tour": 0.0,           # battement de cœur (distingue morte / débranchée)
            "erreurs_tour": 0, "relances": 0,     # filet de la boucle
            "ecritures_ko": 0, "ecriture_err": "",  # écritures DMX/LED refusées
        }
        self.ENVOI = {"dmx": 0.0}
        self.THREAD_MORT = {}        # {nom_thread: "TypeErreur: message"}

        # ── DMX (XLR de la wing) ──
        self.DMX = {
            "enabled": False,
            "uni": [1, 2],           # univers écoutés : [XLR A, XLR B]
            "buf": [bytearray(512), bytearray(512)],
            "source": None,          # "sACN" | "Art-Net"
            "pps": 0, "_count": 0, "_t": time.time(),
            "t_tour": 0.0,           # battement de cœur de dmx_listener
            "refuses": 0,            # paquets écartés (« local uniquement »)
        }

        # ── LEDs ──
        self.LED = {
            "buf": bytearray(wb.LED_BASE),
            "feedback": True,        # LED d'un bouton allumée pendant l'appui
            "ma3": True,             # niveau de repos = état réel de MA3
        }
        self.LED_RAFRAICHI = {"t": 0.0}
        self.VEGAS = {"on": False}

        # ── Faders ──
        self.FADER_LAST = {}         # dernière valeur envoyée, par fader
        self.FADER_T = {}            # dernier envoi, par fader
        self.FADER_ATTENTE = {}      # (val, cmd) en attente, par fader
        self.PICKUP = {}             # i → {"pris", "signe", "bouge", "envoye"}
        self.SUIVI_VU = {}           # anti-répétition des constats de suivi MA3

        # ── Touches, mode console ──
        self.MAINTIENS = {}          # btn_id → spec clavier réellement enfoncé
        self.BOUTONS_ENFONCES = set()
        self.VERBE = {"token": None, "t": 0.0}
        self.CONSOLE_CIBLES = {"cmd": ""}
        self.WS = {
            "queue": deque(),        # frappes en attente
            "lock": threading.Lock(),
            "helper_seen": 0.0,      # dernier poll de l'assistant
            "helper_trusted": False, # Accessibilité accordée à l'assistant ?
            "helper_build": 0,
            "pending_action": None,  # action à transmettre (open_settings)
        }

        # ── MA3, interface, profils ──
        self.MA3_CHECK = {"t": 0.0, "alive": False, "listening": False}
        self.UI_VIE = {"dernier_ping": 0.0, "arret_t": 0.0}
        self.RECOVERY = {"available": None}


E = Etat()


@contextlib.contextmanager
def injecter(e: Etat = None):
    """Installe `e` (ou un état neuf) comme état COURANT le temps du bloc.

    Pour les tests : tout le moteur lit `etat.E` à chaque accès, il voit donc
    l'état injecté ; à la sortie, l'état d'origine revient intact. ⚠️ Arrêter
    tout fil lancé dans le bloc avant d'en sortir : il basculerait sinon sur
    l'état d'origine."""
    global E
    ancien = E
    E = e if e is not None else Etat()
    try:
        yield E
    finally:
        E = ancien
