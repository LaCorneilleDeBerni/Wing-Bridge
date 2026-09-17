"""Boutons de la wing : anti-rebond, appui/relâchement, mode console
(double appui, verbe + executor, cycles de mots-clés).

L'ÉTAT PARTAGÉ (profil, réglages, verrou, liaison USB…) se lit et s'écrit
via `etat.E.<champ>` (etat.py, audit du 25/09/2026, D1) — jamais via
`wing_ui` : ses anciens noms lèvent. `core.X` ne sert plus qu'aux FONCTIONS
et CONSTANTES que `wing_ui.py` réexporte.

⚠️ `import wing_ui as core` est PARESSEUX (dans chaque fonction, jamais en
tête de fichier : un import circulaire casse le bootstrap PyInstaller).

⚠️ `_maintenu_re()` dépend de `MA3_VERBES_MAINTENUS`, qui reste dans
wing_ui.py mais n'y est défini qu'après le bloc d'imports (ligne ~277) —
donc APRÈS que ce module soit importé. La regex est donc compilée au premier
appel, pas au chargement du module (même piège que `FADER_KEYWORD_BY_KIND`
dans wing_ma3.py).

`CIBLES_CONSOMMEES`, `MA3_CYCLES`, `CYCLE`, `VERBES_ANNULE`,
`VERBES_UNE_CIBLE`, `DERNIER_APPUI`, `DOUBLE_APPUI_S`, `VERBE_PEREMPTION_S`,
`BTN_DEBOUNCE_S`, `_btn_last_event` sont en revanche EXCLUSIFS à ce bloc :
ils déménagent ici en clair (référence nue). `CYCLE`/`DERNIER_APPUI`/
`_btn_last_event` restent ré-exportés par wing_ui.py parce que
`smoke_test.py` les mute directement (`.clear()`, assignation de clé) pour
neutraliser l'anti-rebond entre deux essais — la mutation porte sur le MÊME
objet quel que soit le module qui le nomme, donc la référence nue ici reste
sûre.
"""

import etat
import re
import threading
import time


# ── Anti-rebond bouton ─────────────────────────────────────────────────────
# Un seul appui physique ne doit déclencher qu'UNE commande (rebond mécanique,
# ou événement dupliqué sur plusieurs cycles de poll : quelques ms, bien sous
# un relâchement volontaire, ~100 ms au minimum). Appui et relâchement sont
# suivis SÉPARÉMENT (par (btn_id, type)) pour ne jamais avaler le relâchement
# légitime d'un clic bref à cause de son propre appui.
BTN_DEBOUNCE_S = 0.06
_btn_last_event = {}   # (btn_id, "press"|"release") → time.time() du dernier traité

_MAINTENU_RE_CACHE = {}


def _maintenu_re():
    """Regex "<Verbe> On (.+)" — compilée au premier appel, voir docstring
    de ce module."""
    import wing_ui as core
    rx = _MAINTENU_RE_CACHE.get("rx")
    if rx is None:
        rx = re.compile(
            r"^(" + "|".join(sorted(v.capitalize() for v in core.MA3_VERBES_MAINTENUS))
            + r") On (.+)$")
        _MAINTENU_RE_CACHE["rx"] = rx
    return rx


def _debounced(btn_id: int, kind: str) -> bool:
    """True si cet événement doit être IGNORÉ (trop rapproché du précédent
    du MÊME type sur ce bouton)."""
    now = time.time()
    k = (btn_id, kind)
    if now - _btn_last_event.get(k, 0.0) < BTN_DEBOUNCE_S:
        return True
    _btn_last_event[k] = now
    return False


def handle_button_release(btn_id: int):
    """Relâchement d'un bouton : complète les fonctions maintenues par leur
    contrepartie Off (executors, OSC direct) OU relâche la touche clavier
    maintenue pour un appui long (mode console) — indépendant l'un de l'autre."""
    import wing_ui as core
    if _debounced(btn_id, "release"):
        return

    # Cet appui a servi de CIBLE à un verbe : le bouton n'a pas agi comme un
    # executor, son relâchement n'a donc rien à déclencher. Sans ça, le suivi
    # de MA3 réévaluait la fonction propre du bouton et annonçait « Executor
    # 201 absent de la page courante », juste sous un « Move … At Executor
    # 201 » parfaitement valide (voir CIBLES_CONSOMMEES).
    if btn_id in CIBLES_CONSOMMEES:
        CIBLES_CONSOMMEES.discard(btn_id)
        return

    key = f"0x{btn_id:02x}"
    with etat.E.LOCK:
        token = etat.E.PROFILE["buttons"].get(key)
        keymap = dict(etat.E.PROFILE.get("console_keys", {}))
    if not token:
        return

    # Relâche la VRAIE touche enfoncée à l'appui. On lit MAINTIENS, pas le
    # profil : c'est le seul moyen de relâcher exactement ce qu'on a enfoncé,
    # même si le profil a changé entre-temps.
    #
    # ⚠️ Indépendant de WS["enabled"] au moment présent : si l'appui a démarré
    # un maintien, on DOIT le relâcher, mode console coupé ou non. Une touche
    # restée enfoncée dans MA3 est bien pire qu'une frappe manquée.
    spec_tenu = etat.E.MAINTIENS.pop(btn_id, None)
    if spec_tenu:
        core.enqueue_key_up(spec_tenu)
        core.log(f'CONSOLE : {token} → clavier "{spec_tenu}" (relâché)')
        return

    # Contrepartie « Off ». Deux chemins :
    #  • suivi actif  → MA3 dit si sa fonction est maintenue, donc s'il faut un
    #    Off — même quand le profil contient une commande momentanée. C'est ce
    #    qui permet à un bouton réglé « Go+ » d'agir en Flash si MA3 le dit.
    #  • sans suivi   → comportement historique, sur le seul texte du profil.
    if core.suivi_actif() and core._RE_EXEC_CMD.match(token.strip()):
        off_cmd = core.token_selon_ma3(token, "relachement")
        if off_cmd is None:
            return                 # fonction momentanée : rien au relâchement
        etat.E.OSC.send_message("/cmd", off_cmd)
        core.log(f'RELÂCHÉ : "{off_cmd}"')
        return

    m = _maintenu_re().match(token)
    if m:
        off_cmd = f"{m.group(1)} Off {m.group(2)}"
        etat.E.OSC.send_message("/cmd", off_cmd)
        core.log(f'RELÂCHÉ : "{off_cmd}"')


# ── Double appui et verbe en attente ─────────────────────────────────────────
#
# Deux comportements de vraie console qui manquaient.
#
# 1. DOUBLE APPUI sur une touche → commande dédiée. Sur une command wing, deux
#    appuis rapides sur Menu déclenchent une sauvegarde rapide.
# 2. VERBE + EXECUTOR. Sur une console, taper « Store » puis appuyer sur un
#    executor complète la commande. En mode console, l'appui sur un executor
#    partait en OSC direct : MA3 exécutait Go+ au lieu de recevoir la cible, et
#    le verbe restait en plan dans la ligne de commande.
#
# ⚠️ On ne LIT pas la ligne de commande de MA3 — on ne peut pas savoir ce que
# l'utilisateur y a tapé au clavier physique. On suit donc uniquement les
# verbes tapés DEPUIS LA WING, avec une péremption : au-delà, on revient au
# comportement normal plutôt que de deviner.
DOUBLE_APPUI_S = 0.45          # au-delà, ce sont deux appuis distincts
VERBE_PEREMPTION_S = 10.0      # un verbe oublié ne doit pas piéger la wing

# ── Appuis répétés sur la MÊME touche → mot-clé suivant ──────────────────────
#
# Comportement d'une vraie console :
# « pour avoir Label je clique deux fois sur Assign ; move devient exchange,
# delete devient remove puis release ».
#
# Vérifié et complété par balayage du manuel installé (gma3 2.4.2) : chaque
# page keyword_*.html indique « Press <Touche> <Touche> » quand le mot-clé
# s'obtient par répétition. 24 cycles y figurent ; ne sont repris ici que ceux
# dont la touche sert de VERBE À CIBLE sur la wing.
#
# ⚠️ On ne change PAS ce qui est tapé : le raccourci de la touche d'origine
# part autant de fois qu'il y a d'appuis, et MA3 fait le cycle lui-même. Ce
# qu'on suit ici, c'est le mot-clé RÉELLEMENT actif, pour que la commande
# envoyée en OSC corresponde à ce que la console affiche.
MA3_CYCLES = {
    "Assign": ["Assign", "Label"],
    "Move":   ["Move", "Exchange"],
    "Copy":   ["Copy", "Paste", "Insert"],
    "Goto":   ["Goto", "Load"],
    "Select": ["Select", "Collect"],
    "Edit":   ["Edit", "EditSetting"],
    # ⚠️ Remove et Release agissent sur les VALEURS DU PROGRAMMEUR, pas sur un
    # objet (vérifié dans le manuel). Ils sont donc listés — le cycle existe —
    # mais absents de VERBES_CIBLE : après un double appui sur Delete, aucun
    # verbe n'attend de cible, et l'executor retrouve son action directe.
    "Delete": ["Delete", "Remove", "Release"],
}

# Position dans le cycle de la dernière touche pressée.
CYCLE = {"btn": None, "n": 0, "t": 0.0}


def mot_cycle(btn_id: int, token: str, maintenant: float) -> str:
    """Mot-clé courant pour cette touche, selon le nombre d'appuis rapides.

    Hors cycle, ou après une pause, on repart du premier mot.
    """
    suite = MA3_CYCLES.get(token)
    if not suite:
        CYCLE["btn"] = None
        return token
    if CYCLE["btn"] == btn_id and maintenant - CYCLE["t"] <= DOUBLE_APPUI_S:
        CYCLE["n"] = (CYCLE["n"] + 1) % len(suite)
    else:
        CYCLE["n"] = 0
    CYCLE.update(btn=btn_id, t=maintenant)
    return suite[CYCLE["n"]]

# Ces touches referment la ligne de commande : le verbe n'attend plus rien.
VERBES_ANNULE = {"Please", "Clear", "Esc", "Oops"}

# Verbes qui se contentent d'UNE cible : l'appui sur l'executor termine la
# commande. Copy, Move et Assign en attendent DEUX (source puis destination),
# on continue donc d'accumuler jusqu'à Please — même logique qu'en OSC pur.
VERBES_UNE_CIBLE = {"Store", "Update", "Delete", "Label", "Goto", "Load",
                    "Select", "Edit", "Fix",
                    "Off", "On", "Kill", "Toggle",
                    "Collect", "EditSetting", "Insert",
                    # ⚠️ ASSIGN est à UNE cible (vérifié sur console réelle) : l'appui sur
                    # l'executor COMPLÈTE la commande, sans Please.
                    "Assign"}
# Restent à DEUX cibles : Copy, Move et Exchange (source puis destination).

# Boutons dont l'APPUI a servi de cible à un verbe : leur relâchement n'est
# PLUS traité comme celui d'un bouton d'executor. (Sous « Move Executor 101 At
# Executor 201 », le relâchement de 201 journalisait « Executor 201 absent » —
# exact, mais lu comme un refus de la commande qui attendait Please.)
CIBLES_CONSOMMEES = set()


def _console_executer(cmd: str, keymap: dict):
    """Exécute une commande complète depuis le mode console.

    ⚠️⚠️ POURQUOI ON NE TAPE PAS LA CIBLE AU CLAVIER — erreur d'une version
    antérieure, signalée « ça fait n'importe quoi ».

    La ligne de commande de MA3 N'EST PAS UN CHAMP DE TEXTE : chaque lettre y
    insère un MOT-CLÉ. On y tapait « Executor 105 » caractère par caractère,
    et MA3 lisait donc une suite de mots-clés — E → Edit, c → Channel,
    u → Update, t → Thru… — au lieu du texte voulu.

    ⚠️ Ce commentaire donnait « o → Set ». C'est FAUX, et ça a coûté : la même
    idée fausse était recopiée dans la table des raccourcis, où « Set » était
    réglé sur « o » — c'est-à-dire la touche de « Off ». Un bouton Set coupait
    donc l'executor (corrigé — voir RACCOURCIS_CORRIGES).
    Les deux sources installées le disent : la table de raccourcis de MA3
    (KeyCode OFF = « O », SET = « Q ») et le manuel (Oops = « O », Set n'a pas
    de raccourci). La correspondance exacte lettre → mot-clé dépend en outre
    de la table ShCuts active — ne PAS la reconstituer de mémoire, la lire.

    Et le mot « Executor » n'a AUCUN raccourci clavier dans MA3 : il est de
    toute façon impossible à taper. La seule voie correcte est l'OSC.

    ⚠️ ORDRE : le verbe a DÉJÀ été tapé dans la ligne de commande de MA3. On
    l'efface avant d'envoyer la commande entière, sinon MA3 garderait
    « Store » en suspens après l'exécution. Et la frappe passe par la file de
    l'assistant clavier (sondée toutes les 50 ms) alors que l'OSC part
    immédiatement — d'où le délai, sans lequel la commande arriverait AVANT
    l'effacement.
    """
    import wing_ui as core
    etat.E.CONSOLE_CIBLES["cmd"] = ""
    etat.E.VERBE["token"] = None
    spec = keymap.get("Clear")
    if spec:
        core.enqueue_key(spec)

    def _envoyer():
        etat.E.OSC.send_message("/cmd", cmd)
        core.log(f'CONSOLE : "{cmd}" (verbe + cible → OSC)')

    threading.Timer(0.25 if spec else 0.0, _envoyer).start()

DERNIER_APPUI = {}             # btn_id → horodatage du dernier appui


def verbe_en_attente():
    """Un verbe tapé depuis la wing attend-il encore sa cible ?

    Renvoie None si la fonction est décochée dans les réglages : tout le
    mécanisme « verbe + executor » repose sur cette réponse, il suffit donc
    de la couper ici pour que les executors retrouvent leur action directe.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("verbe_cible", True):
        return None
    if not etat.E.VERBE["token"]:
        return None
    if time.time() - etat.E.VERBE["t"] > VERBE_PEREMPTION_S:
        etat.E.VERBE["token"] = None
        return None
    return etat.E.VERBE["token"]


def handle_button_bridge(btn_id: int):
    """Logique bridge pour un appui bouton (répliquée de wing_bridge.main)."""
    import wing_ui as core
    if _debounced(btn_id, "press"):
        return
    key = f"0x{btn_id:02x}"

    # Double appui rapide → commande dédiée du profil, si elle existe — SAUF
    # sur une roue (__ENCn_PUSH__) : un double-clic y bascule sur le groupe
    # N+ENC_GROUPES_SIMPLE (5-8), en dur, sans passer
    # par la table `double_clic` (réservée aux AUTRES boutons). Il faut donc
    # connaître le token AVANT de décider quoi faire du double-clic — d'où
    # cette lecture, redondante avec celle un peu plus bas (mode console et
    # mode bridge la refont chacun la leur), mais nécessaire ici : au moment
    # où `double` se décide, rien d'autre n'a encore lu `buttons`.
    #
    # ⚠️ `double_clic` est indexé par TOKEN ("Menu"), pas par code bouton
    # brut : le code est propre à chaque wing (GUIDE_PROJET.md, « chaque
    # wing est différente ») — indexer par code ferait suivre le double-clic
    # à la POSITION physique du bouton au lieu du bouton lui-même dès qu'une
    # autre wing (ou un remappage) place un token différent à ce code.
    with etat.E.LOCK:
        token_precoce = etat.E.PROFILE["buttons"].get(key)

    maintenant = time.time()
    double = (maintenant - DERNIER_APPUI.get(btn_id, 0.0)) <= DOUBLE_APPUI_S
    DERNIER_APPUI[btn_id] = maintenant
    if double:
        if token_precoce and token_precoce.startswith("__ENC") \
                and token_precoce.endswith("_PUSH__"):
            DERNIER_APPUI[btn_id] = 0.0        # pas de triple déclenchement
            n = int(token_precoce[5]) - 1 + core.wb.ENC_GROUPES_SIMPLE
            gi = core.appliquer_groupe_enc(n)
            attrs = " | ".join(f"R{i+1}={a or '—'}"
                               for i, a in enumerate(etat.E.STATE["enc_attr"]))
            core.log("journal.bouton.groupe_enc_dbl", n=gi + 1, attrs=attrs)
            return
        with etat.E.LOCK:
            cmd2 = (etat.E.PROFILE.get("double_clic") or {}).get(token_precoce)
        if cmd2:
            DERNIER_APPUI[btn_id] = 0.0        # pas de triple déclenchement
            etat.E.VERBE["token"] = None
            etat.E.OSC.send_message("/cmd", cmd2)
            core.log(f'DOUBLE APPUI : "{cmd2}"')
            # ⚠️ Le PREMIER appui du double-clic vient de partir
            # comme une frappe normale (voir plus bas : la fonction ne sait
            # pas encore, à cet instant-là, qu'un second appui va suivre dans
            # la fenêtre de 0,45 s — attendre pour le savoir retarderait TOUT
            # appui simple). Si ce premier appui a ouvert un écran côté MA3
            # (cas de Menu), cet écran reste ouvert après la commande OSC :
            # elle sauvegarde mais ne referme rien. Un Escape ferme cet écran
            # sans effet de bord si rien n'était ouvert — vérifié en réel (le
            # menu restait affiché après le save).
            core.enqueue_key("Escape")
            return

    with etat.E.LOCK:
        buttons  = dict(etat.E.PROFILE["buttons"])
        exec_ref = dict(etat.E.PROFILE["executor_ref"])
        keymap   = dict(etat.E.PROFILE.get("console_keys", {}))
        # ⚠️ `cmd_buf`, lui, N'EST PAS snapshoté ici — voir plus bas, juste
        # avant son premier usage réel : le lire ici puis écrire dessus
        # bien plus loin, hors verrou, est exactement la course du bug #9
        # (une frappe en cours peut faire réapparaître une commande périmée
        # après une remise à zéro voulue par `_post_mode`).

    # ── Mode console : tout passe par le clavier (vraie ligne de commande MA3).
    # Le buffer interne de l'app N'EST PAS utilisé ici — on ne veut pas de
    # "ligne de commande" parallèle. Store + clic écran se fait dans MA3.
    if core.console_helper_alive():
        token = buttons.get(key)
        if token is None:
            core.log("journal.bouton.non_mappee", key=key)
            return
        # Clic encodeur : change le groupe d'attributs (local, pas de frappe)
        if token.startswith("__ENC") and token.endswith("_PUSH__"):
            gi = core.appliquer_groupe_enc(int(token[5]) - 1)
            core.log("journal.bouton.groupe_enc", n=gi + 1)
            return
        # Bouton executor (Go+/playback) : action OSC directe, vérifiée AVANT le
        # raccourci clavier — sinon un raccourci resté configuré sur une commande
        # d'executor TAPERAIT « Go+ » au lieu de l'exécuter.
        # Un verbe attend sa cible → on ASSEMBLE la commande et on l'envoie en OSC,
        # sans rien taper (voir _console_executer).
        if key in exec_ref and verbe_en_attente():
            ref   = exec_ref[key]
            verbe = verbe_en_attente()
            debut = etat.E.CONSOLE_CIBLES["cmd"] or verbe
            # Ce bouton a servi de CIBLE : son relâchement ne doit pas être
            # réinterprété comme celui d'un bouton d'executor.
            CIBLES_CONSOMMEES.add(btn_id)
            if verbe in VERBES_UNE_CIBLE:
                _console_executer(f"{debut} {ref}", keymap)
            else:
                # Copy / Move / Exchange attendent une SECONDE cible, avec « At » ENTRE LES
                # DEUX (syntaxe du manuel) :
                #     Copy [Object] [Source] At [Destination]
                #     Move [Object] [Object] At [Object]
                # Sans le At, MA3 refuse — en silence.
                if etat.E.CONSOLE_CIBLES["cmd"]:
                    # 🎯 DEUXIÈME cible = la destination : la commande est COMPLÈTE et part
                    # immédiatement, sans Please (réglage par défaut de la console, qui vaut pour
                    # TOUS les verbes à cible, pas seulement Assign).
                    _console_executer(
                        f'{etat.E.CONSOLE_CIBLES["cmd"]} At {ref}', keymap)
                else:
                    # PREMIÈRE cible = la source : on attend la destination.
                    etat.E.CONSOLE_CIBLES["cmd"] = f"{verbe} {ref}"
                    etat.E.VERBE["t"] = time.time()   # le verbe reste en attente
                    core.log("journal.bouton.choisir_destination",
                             cmd=etat.E.CONSOLE_CIBLES["cmd"])
            return

        # ⚠️ Même reconnaissance d'une commande d'executor que partout ailleurs
        # (`core._RE_EXEC_CMD`, `<Verbe> [On|Off] Executor <n>`) : une liste figée de
        # préfixes laissait « Flash Executor 105 » partir en OSC brut, sans le On/Off
        # qu'exige une fonction maintenue.
        if key in exec_ref or core._RE_EXEC_CMD.match(token.strip()):
            token = core.token_selon_ma3(token, "appui")
            if token is None:      # MA3 dit : rien à envoyer pour cet événement
                return
            etat.E.OSC.send_message("/cmd", token)
            core.log(f'CONSOLE : {token} (OSC direct)')
            return
        # Please termine une commande assemblée DEPUIS LA WING (Copy / Move /
        # Assign + cibles). Elle n'a jamais été écrite dans la ligne de
        # commande de MA3 — taper Entrée n'y ferait donc rien du tout.
        if token == "Please" and etat.E.CONSOLE_CIBLES["cmd"]:
            _console_executer(etat.E.CONSOLE_CIBLES["cmd"], keymap)
            return

        # Raccourci clavier connu → frappe vers MA3
        spec = keymap.get(token)
        if spec:
            # La touche reste enfoncée jusqu'au relâchement physique du bouton
            # wing (handle_button_release) : on relaie la VRAIE durée, MA3
            # décide seul (Clear maintenu = ClearAll…). Plus aucune case à
            # cocher — voir le commentaire de MAINTIENS.
            core.enqueue_key_down(spec)
            etat.E.MAINTIENS[btn_id] = spec
            core.log(f'CONSOLE : {token} → clavier "{spec}" (enfoncé)')
            # Appuis répétés → mot-clé suivant (Assign Assign = Label…).
            # Le raccourci vient d'être tapé autant de fois qu'il y a
            # d'appuis : MA3 a fait le cycle de son côté, on suit le sien.
            mot = mot_cycle(btn_id, token, maintenant)
            if mot != token:
                core.log(f"CONSOLE : {token} ×{CYCLE['n'] + 1} → {mot}")
            if mot in core.VERBES_CIBLE:
                etat.E.VERBE.update(token=mot, t=time.time())
                etat.E.CONSOLE_CIBLES["cmd"] = ""     # nouveau verbe = nouvelle commande
            elif token in VERBES_ANNULE:
                etat.E.VERBE["token"] = None
                etat.E.CONSOLE_CIBLES["cmd"] = ""     # Clear / Esc / Oops annulent tout
            else:
                # Mot-clé atteint par cycle mais qui ne vise pas d'objet
                # (Remove, Release, Paste) : on désarme, l'executor doit
                # retrouver son action directe.
                etat.E.VERBE["token"] = None
                etat.E.CONSOLE_CIBLES["cmd"] = ""
            return
        # Verbe SANS raccourci clavier (Label, Load…) : il s'arme quand même — la
        # commande finale part en OSC, le raccourci ne sert qu'à AFFICHER le verbe dans
        # la ligne de commande de MA3.
        mot = mot_cycle(btn_id, token, maintenant)
        if mot in core.VERBES_CIBLE:
            etat.E.VERBE.update(token=mot, t=time.time())
            etat.E.CONSOLE_CIBLES["cmd"] = ""
            core.log("journal.bouton.verbe_arme", mot=mot)
            return

        # Pas de raccourci clavier. On raisonne alors comme sur une VRAIE
        # console : un token d'UN SEUL MOT (Store, Clear, Fixture…) est une
        # TOUCHE de la ligne de commande — sans raccourci, on ne peut pas la
        # taper, on l'ignore. Une valeur de PLUSIEURS MOTS (« Next Page »,
        # « Go+ Exec 5 ») n'est pas une touche mais une COMMANDE complète :
        # elle part en OSC, exactement comme les executors ci-dessus.
        #
        # Sans cette distinction, toute commande assignée hors de la liste
        # figée de la carte Mode console devenait MUETTE dès le mode console
        # activé, sans autre trace qu'une ligne de journal.
        if " " in token.strip():
            etat.E.OSC.send_message("/cmd", token)
            core.log(f'CONSOLE : {token} (commande complète → OSC direct)')
            return
        core.log("journal.bouton.sans_raccourci", token=token)
        return

    # Double rôle executor : si le buffer commence par un verbe à cible unique
    # (Store, Update, Delete), l'appui sur l'executor TERMINE la commande —
    # exécution immédiate, pas de Please.
    #
    # ⚠️ Lecture, décision ET écriture de `cmd_buf` SOUS LE MÊME VERROU (`_post_mode`
    # le remet aussi à zéro) : sinon une commande périmée pouvait réapparaître
    # juste après une remise à zéro voulue. Journal et envoi OSC restent hors
    # verrou.
    with etat.E.LOCK:
        buf = etat.E.STATE["cmd_buf"]
        double_role = key in exec_ref and bool(buf.strip())
        if double_role:
            ref   = exec_ref[key]
            first = buf.strip().split()[0]
            if first in ("Store", "Update", "Delete"):
                a_envoyer = buf.strip() + " " + ref
                etat.E.STATE["cmd_buf"] = ""
            else:
                # Copy/Move/Assign… attendent plusieurs objets → on continue de bufferiser
                a_envoyer = None
                etat.E.STATE["cmd_buf"] = buf + " " + ref
            nouveau_buf = etat.E.STATE["cmd_buf"]
    if double_role:
        if a_envoyer:
            core.log(f'EXEC : "{a_envoyer}"  (verbe + clic executor)')
            etat.E.OSC.send_message("/cmd", a_envoyer)
        else:
            core.log(f'BUFFER : "{nouveau_buf}"')
        return

    token = buttons.get(key)
    if token is None:
        core.log("journal.bouton.non_mappee", key=key)
        return

    # ── Commande d'executor : MA3 fait autorité, comme en mode console ───────
    #
    # ⚠️ Appui et relâchement doivent TOUJOURS être décidés par la même fonction
    # (`token_selon_ma3`). Sinon — profil « Flash On Executor 105 », MA3 réglé sur
    # Go+ — l'appui envoie Flash On, le relâchement rien : EXECUTOR BLOQUÉ ALLUMÉ.
    if core.suivi_actif() and core._RE_EXEC_CMD.match(token.strip()):
        cible = core.token_selon_ma3(token, "appui")
        if cible is None:
            return                      # MA3 n'a rien à cet endroit
        etat.E.OSC.send_message("/cmd", cible)
        core.log(f'→ "{cible}"')
        return

    # ⚠️ Même règle que plus haut : `cmd_buf` relu ET écrit sous le MÊME
    # verrou, à chaque branche — jamais sur une valeur lue plus tôt dans la
    # fonction (voir le commentaire détaillé au premier bloc « double rôle
    # executor »).
    if token in core.CMD_BUF_TOKENS:
        with etat.E.LOCK:
            buf = etat.E.STATE["cmd_buf"]
            is_digit   = token in "0123456789."
            last_digit = buf and buf[-1] in "0123456789."
            if not buf:
                buf = token
            elif is_digit and last_digit:
                buf += token
            elif is_digit and buf.endswith(" "):
                buf += token
            else:
                buf += " " + token
            etat.E.STATE["cmd_buf"] = buf
        core.log(f'BUFFER : "{buf}"')

    elif token == "Please":
        with etat.E.LOCK:
            buf = etat.E.STATE["cmd_buf"]
            if buf.strip():
                etat.E.STATE["cmd_buf"] = ""
        if buf.strip():
            core.log(f'EXEC : "{buf.strip()}"')
            etat.E.OSC.send_message("/cmd", buf.strip())
        else:
            etat.E.OSC.send_message("/cmd", "Please")
            core.log("→ Please")

    elif token == "Clear":
        with etat.E.LOCK:
            buf = etat.E.STATE["cmd_buf"]
            if buf:
                etat.E.STATE["cmd_buf"] = ""
        if buf:
            core.log(f'Buffer effacé (était : "{buf}")')
        else:
            etat.E.OSC.send_message("/cmd", "Clear")
            core.log("→ Clear")

    elif token.startswith("__ENC") and token.endswith("_PUSH__"):
        gi = core.appliquer_groupe_enc(int(token[5]) - 1)
        attrs = " | ".join(f"R{i+1}={a or '—'}" for i, a in enumerate(etat.E.STATE["enc_attr"]))
        core.log("journal.bouton.groupe_enc_attrs", n=gi + 1, attrs=attrs)

    else:
        etat.E.OSC.send_message("/cmd", token)
        core.log(f'→ "{token}"')


# ── Affectation d'une touche à partir d'une requête de l'interface ───────────
#
# Sortie de `wing_handler._post_assign` (audit du 25/09/2026, point D3) : le
# Handler assemblait lui-même la commande MA3 (« Flash On Executor 105 »). Il
# ne fait plus que lire, appeler ceci, et ranger le résultat.
Affectation = __import__("collections").namedtuple(
    "Affectation", "action cle commande executor_ref journal params")

_RE_CODE_TOUCHE = re.compile(r"0x[0-9a-f]{2}")


def affectation(body) -> "Affectation":
    """Ce qu'une requête `/api/assign` demande de faire à une touche.

    `action` : "poser" (commande + executor_ref éventuel), "effacer", ou
    "rien" (valeur vide — l'interface l'envoie quand on vide un champ).
    Lève `wing_validation.EntreeInvalide` sur un paramètre invalide."""
    import wing_ui as core
    import wing_validation as v
    atype = v.choix(body, "type", ("cmd", "exec", "push", "clear"))
    cle = v.texte(body, "key", 8)
    if not _RE_CODE_TOUCHE.fullmatch(cle):
        import wing_i18n
        raise v.EntreeInvalide(wing_i18n.L("err.entree.touche", v=cle))
    if atype == "clear":
        return Affectation("effacer", cle, None, None,
                           "journal.assign.effacee", {"key": cle})
    brut = body.get("value")
    if brut is None or (isinstance(brut, str) and not brut.strip()):
        return Affectation("rien", cle, None, None, None, {})
    if atype == "cmd":
        valeur = v.texte(body, "value", 400)
        # ⚠️ Casse corrigée AVANT enregistrement : « off » au lieu de « Off »
        # échoue EN SILENCE sur la ligne de commande de MA3.
        commande, corrections = core.corriger_casse(valeur)
        return Affectation(
            "poser", cle, commande, None,
            "journal.assign.touche_casse" if corrections else "journal.assign.touche",
            {"key": cle, "cmd": commande, "casse": ", ".join(corrections)})
    if atype == "exec":
        exe = v.entier(body, "value", 1, 99999)
        # Fonction de déclenchement de l'executor (Go+, Flash, Toggle…). Les
        # fonctions MAINTENUES ont besoin de « On » à l'appui —
        # handle_button_release complète le « Off » au relâchement.
        func = v.choix(body, "func", core.EXEC_FUNCS, "Go+")
        commande = (f"{func} On Executor {exe}" if func in core.MAINTENUES_UI
                    else f"{func} Executor {exe}")
        return Affectation("poser", cle, commande, f"Executor {exe}",
                           "journal.assign.double_role",
                           {"key": cle, "cmd": commande})
    n = v.choix(body, "value", ("1", "2", "3", "4"))       # push (clic de roue)
    return Affectation("poser", cle, f"__ENC{n}_PUSH__", None,
                       "journal.assign.push_roue", {"key": cle, "n": n})


def renumeroter_rangee(refs: dict, btns: dict, rangee: int, base: int) -> int:
    """Renumérote une RANGÉE de boutons executor d'un coup (modifie `refs` et
    `btns` sur place ; l'appelant tient etat.E.LOCK). Rend le nombre de touches.

    Concernées : celles dont l'executor actuel tombe dans la centaine visée
    (100 → 100-199). On garde leur ORDRE PHYSIQUE (tri par code de bouton) et
    on réaffecte base, base+1, … Sur MA3 toutes les pages ont la même
    disposition et un numéro d'executor est relatif à la page courante : une
    seule passe suffit. Sorti de wing_handler (audit du 25/09/2026, D3)."""
    concernes = []
    for cle, ref in refs.items():
        m = re.search(r"(\d+)", str(ref))
        if m and rangee <= int(m.group(1)) < rangee + 100:
            concernes.append(cle)
    concernes.sort(key=lambda c: int(c, 16))
    for n, cle in enumerate(concernes):
        neuf = base + n
        refs[cle] = f"Executor {neuf}"
        tok = btns.get(cle)
        if tok:
            # On ne touche QU'AU numéro : le verbe et le suffixe On/Off
            # appartiennent au réglage de l'utilisateur.
            btns[cle] = re.sub(r"(Executor\s+)\d+", rf"\g<1>{neuf}", tok)
    return len(concernes)
