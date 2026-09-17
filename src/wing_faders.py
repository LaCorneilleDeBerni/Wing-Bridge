#!/usr/bin/env python3
"""
wing_faders.py — envoi des faders, suivi de MA3, rattrapage (« pickup »)
==============================================================================
Extrait de `wing_ui.py`. L'ÉTAT PARTAGÉ (profil, réglages, verrou, liaison USB…) se lit et s'écrit
via `etat.E.<champ>` (etat.py, audit du 25/09/2026, D1) — jamais via
`wing_ui` : ses anciens noms lèvent. `core.X` ne sert plus qu'aux FONCTIONS
et CONSTANTES que `wing_ui.py` réexporte.
Constantes lues via `core.X` : `FADER_INTERVALLE`, `MASTERS_SELECTION`,
`SPEED_UNITS`, `MA3_VERBES_MAINTENUS`, `_RE_EXEC_CMD`, `FADER_ORDER`,
`FADER_KEYWORDS`.

⚠️ `import wing_ui as core` est PARESSEUX — DANS chaque fonction qui s'en
sert, jamais en tête de fichier : le cycle d'import est sûr sous CPython nu,
mais PAS sous le bootloader figé de PyInstaller. Et parce que `wing_ui.py` est
le POINT D'ENTRÉE du programme, il s'auto-enregistre dans
`sys.modules["wing_ui"]` en tête de fichier, AVANT d'importer ce module.

`_mapped_speed_value` : voir `docs/FADERS_ENCODERS.md` — valeur ABSOLUE avec
mot-clé d'unité (le manuel MA3 tranche), min/max = choix de l'utilisateur.
"""

import etat
import re
import time


# Grammaire des commandes d'executor du profil : `<Verbe> [On|Off] Executor <n>`
# — la regex est `core._RE_EXEC_CMD` (wing_ui.py), partagée avec wing_boutons.py.


def _suivi_dit(cle, cle_i18n, **params):
    """`cle` : identifiant d'anti-répétition (par executor/fader). `cle_i18n`
    (+ params) : la ligne à journaliser. On ne rejoue pas si la MÊME ligne
    (clé + params) a déjà été dite pour cette `cle`."""
    import wing_ui as core
    signature = (cle_i18n, tuple(sorted(params.items())))
    if etat.E.SUIVI_VU.get(cle) == signature:
        return
    etat.E.SUIVI_VU[cle] = signature
    core.log(cle_i18n, **params)


def suivi_actif() -> bool:
    """Le suivi de MA3 est-il réellement en vigueur ?

    Il faut DEUX conditions : la case cochée, ET une sonde qui répond. Le
    plugin est une étape d'installation requise ; s'il manque, le repli sans
    sonde existe pour NE PAS PLANTER — pas pour offrir une expérience
    équivalente. Sans sonde, l'app pilote MA3 à l'aveugle (pas de retour LED,
    pas de rattrapage des faders) : elle marche, en dégradé.
    """
    import wing_ui as core
    return bool(etat.E.SETTINGS.get("suivre_ma3", True)) and core.ma3_etat().get("actif")


# ── Faders → types de master MA3 ──────────────────────────────────────────────
# Chaque fader physique a un "kind" — reflète très exactement la liste
# "Select Function" que MA3 propose pour la propriété Fader d'un executor
# (Menu Executor → Fader → Select Function).
#
# Observé sur un vrai showfile : fader "Master" et "" (vide), touches "Go+",
# "Flash", "SelectFixtures". Le reste vient de la liste officielle des fonctions
# (cf. docs/FADERS_ENCODERS.md, « Même traitement pour les faders »).
MA3_FADER_KINDS = {          # ex.fader → "kind" interne
    "master": "executor",
    "x": "crossfade", "crossfade": "crossfade",
    "xa": "crossfadeA", "crossfadea": "crossfadeA",
    "xb": "crossfadeB", "crossfadeb": "crossfadeB",
    "temp": "temp",
    "rate": "rate",
    "time": "time",
    "speed": "faderspeed",
}

# ex.key → verbe de commande. Identité pour l'essentiel, mais on n'accepte QUE
# ce que Wing Bridge sait réellement envoyer : une fonction comme
# "SelectFixtures" n'est pas un verbe de playback et doit retomber sur le
# réglage de l'utilisateur plutôt que de produire une commande inventée.
# Liste relevée dans MA3 lui-même (Assign Executor → Select Function,
# captures), puis CHAQUE nom vérifié comme mot-clé de commande
# réel dans le manuel installé (présence de shared/language/HTML/keyword_*.html).
#
# ⚠️ Volontairement ABSENTS, faute de certitude sur leur syntaxe appliquée à un
# executor : Time, LogIn, Rate1, <<<, >>>. Un nom absent de cette table laisse
# le réglage de l'utilisateur intact et se signale — jamais de commande
# inventée. Les ajouter demandera une vérification, pas une intuition.
MA3_KEY_VERBES = {v.lower(): v for v in (
    "Go+", "Go-", "Pause", "Toggle", "Top", "Off", "On", "Flash", "Temp",
    "Swap", "Black", "Learn", "LearnSpeed", "Load", "Goto", "Kill", "Select",
    "SelectFixtures", "Speed1", "DoubleSpeed", "HalfSpeed", "FastSync",
    "ReSync", "Call", "At")}


def kind_selon_ma3(exe, kind_configure):
    """Type de fader à envoyer. `None` = ne rien envoyer du tout.

    🎯 Règle : quand le suivi est actif, **MA3 fait autorité, y compris quand
    il ne dit rien**. Un executor sans
    fonction de fader, ou absent de la page, ne doit RIEN recevoir — comme sur
    une vraie wing, où bouger un fader en face d'un emplacement vide ne fait
    rien. Le réglage de l'app n'est plus un repli dans ce cas.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("suivre_ma3", True) or not exe:
        return kind_configure
    if not core.ma3_etat().get("actif"):
        return kind_configure                    # pas de sonde : comme avant
    e = core.ma3_executor(exe)
    if not e:
        _suivi_dit(f"f{exe}", "journal.fader.exec_hors_page", exe=exe)
        return None
    brut = str(e.get("fonction") or "").strip()
    if not brut or brut.lower() == "empty":
        _suivi_dit(f"f{exe}", "journal.fader.exec_sans_fonction", exe=exe)
        return None
    vrai = MA3_FADER_KINDS.get(brut.lower())
    if vrai is None:
        _suivi_dit(f"f{exe}", "journal.fader.fonction_non_geree", exe=exe, brut=brut)
        return None
    if vrai != kind_configure:
        _suivi_dit(f"f{exe}", "journal.fader.suit_ma3", exe=exe, brut=brut)
    return vrai


def token_selon_ma3(token: str, evenement: str = "appui"):
    """Commande d'executor ajustée à la fonction réelle de la touche MA3.

    Renvoie la commande à envoyer, ou `None` s'il ne faut RIEN envoyer.

    🐛 Corrige une règle antérieure. Quand MA3 était réglé sur une
    fonction MAINTENUE (Flash) et le bouton de l'app sur une fonction
    momentanée (Go+), on n'envoyait rien du tout, par peur d'un « On » sans
    « Off ». Résultat : le bouton ne faisait STRICTEMENT rien, ce qui est pire
    que le problème évité.

    La vraie réponse est d'envoyer la paire nous-mêmes : `Flash On` à l'appui,
    `Flash Off` au relâchement. Le suffixe écrit dans le profil devient sans
    objet dès lors que MA3 fait autorité — c'est MA3 qui dit si la fonction est
    maintenue, donc c'est lui qui décide s'il faut un On/Off.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("suivre_ma3", True):
        return token
    m = core._RE_EXEC_CMD.match(token.strip())
    if not m:
        return token                              # pas une commande d'executor
    verbe, suffixe, exe = m.group(1), (m.group(2) or ""), int(m.group(3))
    if not core.ma3_etat().get("actif"):
        return token                              # pas de sonde : comme avant

    # 🎯 Suivi actif : MA3 fait autorité, y compris quand il ne dit rien.
    # Un executor vide ou absent de la page ne doit RIEN recevoir — sur une
    # vraie wing, appuyer en face d'un emplacement vide ne fait rien.
    e = core.ma3_executor(exe)
    if not e:
        _suivi_dit(f"t{exe}", "journal.fader.exec_hors_page", exe=exe)
        return None
    brut = str(e.get("touche") or "").strip()
    if not brut:
        _suivi_dit(f"t{exe}", "journal.fader.touche_sans_fonction", exe=exe)
        return None
    if brut.lower() == "empty":
        # L'executor n'a AUCUNE fonction sur sa touche : appuyer ne doit rien
        # déclencher, exactement comme sur une vraie console.
        _suivi_dit(f"t{exe}", "journal.fader.touche_vide", exe=exe)
        return None
    vrai = MA3_KEY_VERBES.get(brut.lower())
    if vrai is None:
        _suivi_dit(f"t{exe}", "journal.fader.touche_non_geree", exe=exe, brut=brut)
        return None
    # ⚠️ On/Off ne vaut QUE pour les fonctions maintenues : « Go+ On Executor 5 »
    # n'est pas une commande MA3 valide (syntaxes relevées dans le manuel).
    # C'est donc MA3 — qui sait si sa fonction est maintenue — qui décide de la
    # forme, pas le suffixe écrit dans le profil.
    maintenu_ma3 = vrai.lower() in core.MA3_VERBES_MAINTENUS

    if maintenu_ma3:
        cible = (f"{vrai} On Executor {exe}" if evenement == "appui"
                 else f"{vrai} Off Executor {exe}")
    else:
        # Fonction momentanée : elle n'agit qu'à l'appui, jamais au relâchement.
        if evenement != "appui":
            return None
        cible = f"{vrai} Executor {exe}"

    if vrai.lower() != verbe.lower():
        _suivi_dit(f"t{exe}", "journal.fader.touche_suit_ma3", exe=exe,
                   vrai=vrai, verbe=verbe)
    return cible


# ── Rattrapage de fader (« pickup ») ─────────────────────────────────────────
# Principe et règles : en-tête « Rattrapage de fader » de wing_ui.py. La valeur
# de MA3 vient de la sonde Lua — jamais devinée.
PICKUP_TOLERANCE = 2.0       # % — en deçà, on considère le fader rejoint
PICKUP_REPOS_S   = 1.5       # s sans mouvement avant de re-vérifier l'accord


def _valeur_ma3_du_fader(cfg: dict):
    """Valeur MA3 courante (0..100) d'un fader, quel que soit son type.

    Jusqu'ici seul `executor` avait un canal de lecture (la
    sonde ne lisait QUE des objets Executor). La sonde lit maintenant aussi
    `MasterPool()` (voir plugin_ma3/wingbridge.lua) — `gm`/`speed`/`selected`
    ont donc chacun une source, par le MÊME mécanisme (`GetFader()` sur un
    handle), jamais une logique parallèle. `None` si la sonde ne dit rien
    (fader désactivé côté MA3, sonde absente…) — jamais fabriqué.
    """
    import wing_ui as core
    kind = cfg.get("kind", "executor")
    if kind == "gm":
        return core.ma3_master("grand", 1)          # Master 2.1, un seul
    if kind == "speed":
        return core.ma3_master("speed", cfg.get("num", 1))
    if kind == "selected":
        return core.ma3_master("selected", cfg.get("num", 2))
    exe = cfg.get("exec")
    if not exe:
        return None
    e = core.ma3_executor(exe)
    return e.get("fader") if e else None


def pickup_autorise(i: int, cfg: dict, pct: float) -> bool:
    """Ce fader a-t-il le droit d'envoyer sa valeur ?

    Renvoie True si le rattrapage est désactivé, si MA3 ne dit rien de ce
    fader, ou si le fader a rejoint la valeur MA3. Ne bloque JAMAIS en
    l'absence d'information : sans la sonde, comportement d'avant.

    `cfg` : l'entrée `PROFILE["faders"][i]` (kind, exec, num…) — pas
    seulement un numéro d'executor, depuis que `gm`/`speed`/`selected` sont
    couverts aussi.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("fader_pickup", True):
        return True
    v = _valeur_ma3_du_fader(cfg)
    if v is None:
        return True                      # rien à rattraper, on laisse passer
    ma3v = float(v)
    now = time.time()
    st = etat.E.PICKUP.setdefault(i, {"pris": False, "signe": 0, "bouge": 0.0,
                                    "envoye": None})
    ecart = pct - ma3v
    st["bouge"] = now

    if st["pris"]:
        return True

    # Rejoint : à portée, ou l'écart a changé de signe (on a traversé).
    signe = 1 if ecart > 0 else (-1 if ecart < 0 else 0)
    if abs(ecart) <= PICKUP_TOLERANCE or (st["signe"] and signe
                                          and signe != st["signe"]):
        st["pris"] = True
        st["signe"] = 0
        core.log("journal.fader.rattrape", n=i + 1, pct=f"{pct:.0f}")
        return True

    st["signe"] = signe
    # ⚠️ Message SANS la position courante : elle change à chaque pas, et
    # l'anti-répétition (qui compare le texte) le laissait donc passer à chaque
    # fois — un flot de lignes pendant tout le mouvement.
    _suivi_dit(f"p{i}", "journal.fader.attente_rattrapage", n=i + 1,
               pct=f"{ma3v:.0f}")
    return False


PICKUP_PAGE = {"no": None}


def pickup_page_changee():
    """Un changement de page relâche TOUS les faders, immédiatement.

    🐛 Corrigé. Le relâchement ne se faisait qu'après 1,5 s
    d'immobilité : en changeant de page puis en attrapant le fader aussitôt,
    on gardait la main et MA3 sautait à la position physique. Le symptôme
    paraissait directionnel (« ça marche en descendant, pas en montant »)
    alors que c'était une question de TIMING — la logique de rattrapage,
    testée en isolation, est symétrique.

    Le changement de page est un événement franc : on n'a aucune raison
    d'attendre pour en tenir compte.
    """
    import wing_ui as core
    page = (core.ma3_etat().get("page") or {}).get("no")
    if page is None or page == PICKUP_PAGE["no"]:
        return False
    ancienne, PICKUP_PAGE["no"] = PICKUP_PAGE["no"], page
    if ancienne is None:
        return False                      # premier relevé : rien à relâcher
    repris = 0
    for i, st in etat.E.PICKUP.items():
        if st["pris"]:
            st["pris"] = False
            st["signe"] = 0
            etat.E.SUIVI_VU.pop(f"p{i}", None)
            repris += 1
    if repris:
        core.log_plural("journal.fader.page_rattrape", repris,
                        ancienne=ancienne, page=page)
    return True


def pickup_verifier_repos(faders_phys=None):
    """Réaccorde un fader au repos avec MA3, dans les deux sens.

    Appelé par la boucle USB. C'est ce qui rend le changement de page correct :
    la page change, MA3 affiche autre chose, le fader n'a pas bougé — il doit
    donc redemander un rattrapage au lieu de sauter au prochain contact.

    ⚠️ Couvre maintenant tous les types de fader (`_valeur_ma3_du_fader`),
    plus seulement `executor`. Un `gm`/`speed`/`selected` déjà « pris » perd
    donc la main lui aussi si MA3 change sous ses pieds — à tout moment, pas
    seulement au changement de page (`pickup_page_changee` ci-dessus reste un
    déclencheur immédiat en plus, pas le seul).

    🆕 AUTO-RATTRAPAGE AU REPOS (sens inverse). `faders_phys` = les
    positions physiques RÉELLES (0-1023, fournies par la boucle USB). Un fader
    NON « pris » dont la position physique COÏNCIDE déjà avec la valeur MA3 de
    la page courante n'a aucune raison de clignoter : on le rattrape sans exiger
    de mouvement. Sans ça, l'aller-retour de page (1 → 2 → 1) laissait les
    boutons clignoter au RETOUR alors que rien n'avait bougé : `pickup_page_changee`
    ré-arme TOUT le monde à chaque changement, et le rattrapage par mouvement ne
    se déclenche qu'au mouvement. On lit la position physique RÉELLE, pas la
    dernière valeur envoyée (`st["envoye"]`), qui peut être périmée sur un fader
    armé qu'on a bougé sans le rattraper. `faders_phys=None` → ancien
    comportement (aucun auto-rattrapage), pour ne pas surprendre un appelant tiers.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("fader_pickup", True):
        return
    if pickup_page_changee():
        return                            # déjà tout relâché
    now = time.time()
    faders = faders_instantane()             # jamais LOCK dans la boucle USB
    for i, st in etat.E.PICKUP.items():
        if not st["pris"] or now - st["bouge"] < PICKUP_REPOS_S:
            continue
        if i >= len(faders):
            continue
        v = _valeur_ma3_du_fader(faders[i])
        if v is None or st["envoye"] is None:
            continue
        if abs(float(v) - float(st["envoye"])) > PICKUP_TOLERANCE * 2:
            st["pris"] = False
            st["signe"] = 0
            etat.E.SUIVI_VU.pop(f"p{i}", None)
            core.log("journal.fader.ma3_bouge", n=i + 1, pct=f"{float(v):.0f}")

    # Sens inverse : le fader est déjà en place, on lève le clignotement.
    if faders_phys is None:
        return
    for i, st in etat.E.PICKUP.items():
        if st["pris"] or now - st["bouge"] < PICKUP_REPOS_S:
            continue                      # déjà pris, ou en cours de mouvement
        if i >= len(faders) or i >= len(faders_phys):
            continue
        v = _valeur_ma3_du_fader(faders[i])
        if v is None:
            continue
        pct = int(round(faders_phys[i] / 1023.0 * 100))
        if abs(pct - float(v)) <= PICKUP_TOLERANCE:
            st["pris"]   = True
            st["signe"]  = 0
            st["envoye"] = pct            # référence pour un futur ré-armement
            etat.E.SUIVI_VU.pop(f"p{i}", None)
            core.log("journal.fader.deja_place", n=i + 1, pct=pct)


def _mapped_speed_value(cfg: dict, cv: int):
    """Position du fader (0-1023) → valeur ABSOLUE dans l'unité choisie
    (BPM/Hz/Seconds), mappée linéairement entre `cfg["min"]` et `cfg["max"]`.

    📖 VÉRIFIÉ dans le manuel MA3 2.4.2 installé (source qui
    fait autorité pour ce projet, cf. GUIDE_PROJET.md) : `keyword_faderspeed.html`,
    `keyword_bpm.html`, `keyword_hz.html`, `keyword_seconds.html`.
    `At <UNITÉ> <valeur>` (mot-clé d'unité EXPLICITE) est documenté comme une
    valeur ABSOLUE dans les exemples officiels eux-mêmes : « FaderSpeed
    Sequence 2 At BPM 6 » (6 BPM), « Master 3.1 At BPM 75 » (75 BPM),
    « Master 3.1 At Hz 3 », « Master 3.1 At Seconds 6 ». C'est DIFFÉRENT du
    mot-clé général `At <nombre>` SANS unité (`keyword_at.html` : « FaderMaster
    Sequence 1 At 30 » → 30 %), qui lui est un pourcentage — deux commandes
    distinctes malgré la ressemblance. Un doute passé (retour de forum : « At
    95 » visant 95 BPM donnait ~240 BPM) venait très probablement de la forme
    SANS mot-clé d'unité, pas de la forme `At BPM 95` utilisée ici.

    `cfg["min"]`/`cfg["max"]` ne miment PAS un réglage lu dans MA3 — la sonde
    Lua (`plugin_ma3/wingbridge.lua`) n'expose aucune plage de vitesse
    (vérifié : elle ne lit que `GetFader()`, 0-100 %, et `ex.fader`, le nom de
    la fonction). `masters_speed.html` confirme d'ailleurs que la plage d'un
    Speed Master est fixe côté MA3 (0-225 BPM), pas configurable par master —
    rien à interroger de toute façon. `min`/`max` sont donc uniquement le
    choix de l'UTILISATEUR : quelle plage absolue la course de CE fader
    physique doit couvrir.

    ✅ Confirmé en usage réel : un Speed Master piloté depuis l'app contre un
    Speed Master posé dans MA3 — le chase suit correctement. Point clos.
    """
    lo = float(cfg.get("min", 0))
    hi = float(cfg.get("max", 225))     # plage native du Speed Master MA3 (0-225 BPM)
    val = lo + (cv / 1023.0) * (hi - lo)
    return int(val) if val == int(val) else round(val, 1)


def send_fader(i: int, cfg: dict, cv: int):
    """Construit et envoie la commande MA3 adaptée au type de ce fader."""
    import wing_ui as core
    kind = cfg.get("kind", "executor")
    # `gm`/`speed`/`selected` ne pilotent AUCUN executor : `kind_selon_ma3`
    # (adaptation de la FONCTION assignée par MA3 à un executor) n'a pas de
    # sens pour eux — GrandMaster EST GrandMaster, MA3 ne lui « assigne » rien
    # d'autre. Seul le RATTRAPAGE
    # (pickup_autorise, plus bas) les couvre désormais, pas le suivi de type.
    if kind not in ("gm", "speed", "selected") and cfg.get("suivre", True):
        kind = kind_selon_ma3(cfg.get("exec"), kind)
        if kind is None:
            return                       # MA3 n'a rien à cet endroit

    if kind == "gm":
        pct = int(round(cv / 1023.0 * 100))
        if not pickup_autorise(i, cfg, pct):
            return
        st = etat.E.PICKUP.get(i)
        if st is not None:
            st["envoye"] = pct
        _send_throttled(i, pct, f"Master 2.1 At {pct}")
    elif kind == "faderspeed":
        exe  = cfg.get("exec", 101)
        unit = core.SPEED_UNITS.get(cfg.get("unit", "bpm"), "BPM")
        val  = _mapped_speed_value(cfg, cv)
        _send_throttled(i, val, f"FaderSpeed Executor {exe} At {unit} {val}")
    elif kind == "selected":
        num = int(cfg.get("num", 2))          # 2 = XFade, le cas courant
        pct = int(round(cv / 1023.0 * 100))
        if not pickup_autorise(i, cfg, pct):
            return
        st = etat.E.PICKUP.get(i)
        if st is not None:
            st["envoye"] = pct
        _send_throttled(i, pct, f"Master 1.{num} At {pct}")
    elif kind == "speed":
        num  = cfg.get("num", 1)
        unit = core.SPEED_UNITS.get(cfg.get("unit", "bpm"), "BPM")
        val  = _mapped_speed_value(cfg, cv)
        # ⚠️ Rattrapage comparé en % BRUT (0-100, échelle GetFader) — PAS dans
        # l'unité affichée (BPM/Hz/s) : `ma3_master` rend le même % brut que
        # pour un executor, cohérent avec `pickup_autorise` partout ailleurs.
        pct = int(round(cv / 1023.0 * 100))
        if not pickup_autorise(i, cfg, pct):
            return
        st = etat.E.PICKUP.get(i)
        if st is not None:
            st["envoye"] = pct
        _send_throttled(i, val, f"Master 3.{num} At {unit} {val}")
    else:
        # Tous les types en pourcentage. Un `kind` inconnu retombe sur
        # FaderMaster, comportement historique.
        exe = cfg.get("exec", 101)
        pct = int(round(cv / 1023.0 * 100))
        mot = core.FADER_KEYWORDS.get(kind, "FaderMaster")   # inconnu → historique
        if not pickup_autorise(i, cfg, pct):
            return
        st = etat.E.PICKUP.get(i)
        if st is not None:
            st["envoye"] = pct
        _send_throttled(i, pct, f"{mot} Executor {exe} At {pct}")


def _envoyer_fader(i: int, val, cmd: str, now: float):
    import wing_ui as core
    etat.E.FADER_LAST[i] = val
    etat.E.FADER_T[i] = now
    etat.E.FADER_ATTENTE.pop(i, None)
    etat.E.OSC.send_message("/cmd", cmd)
    core.log(f"FADER F{i+1} → {cmd}")


def _send_throttled(i: int, val, cmd: str):
    """Envoi limité en débit, sans jamais perdre la position finale."""
    import wing_ui as core
    if etat.E.FADER_LAST.get(i) == val:
        etat.E.FADER_ATTENTE.pop(i, None)
        return
    now = time.time()
    if now - etat.E.FADER_T.get(i, 0.0) < core.FADER_INTERVALLE:
        # Trop tôt : on retient la DERNIÈRE valeur vue. Elle partira au
        # prochain créneau — c'est ce qui garantit que le fader finit toujours
        # exactement là où il est, même si on lâche entre deux créneaux.
        etat.E.FADER_ATTENTE[i] = (val, cmd)
        return
    _envoyer_fader(i, val, cmd, now)


def faders_vider_attente():
    """Envoie les positions retenues dont le créneau est arrivé.

    Appelée à chaque tour de boucle : c'est elle qui garantit qu'aucune
    position finale n'est perdue quand on relâche un fader entre deux créneaux.
    """
    import wing_ui as core
    if not etat.E.FADER_ATTENTE:
        return
    now = time.time()
    for i, (val, cmd) in list(etat.E.FADER_ATTENTE.items()):
        if now - etat.E.FADER_T.get(i, 0.0) >= core.FADER_INTERVALLE:
            _envoyer_fader(i, val, cmd, now)


_FADERS_INSTANTANE = {"t": 0.0, "liste": []}


def faders_instantane():
    """Copie des faders du profil, rafraîchie au plus 2 fois par seconde.

    🐛 LEÇON COÛTEUSE. Les fonctions LED prenaient `LOCK` à chaque
    appel : 12 boutons × 8 rafraîchissements = ~96 prises de verrou par seconde,
    depuis la boucle USB (~30 Hz), en concurrence avec /api/status. L'app est
    devenue inutilisable — frappes en retard, LED décalées.

    ⚠️ RÈGLE : ne JAMAIS prendre `LOCK` dans la boucle USB ni dans une fonction
    qu'elle appelle à chaque tour. Passer par un instantané mis en cache.
    """
    import wing_ui as core
    now = time.time()
    if now - _FADERS_INSTANTANE["t"] >= 0.5:
        _FADERS_INSTANTANE["t"] = now
        with etat.E.LOCK:
            _FADERS_INSTANTANE["liste"] = [dict(x) for x in
                                           etat.E.PROFILE.get("faders", [])]
    return _FADERS_INSTANTANE["liste"]


def executors_en_attente() -> set:
    """Executors dont le fader n'a pas encore été rattrapé.

    Calculé UNE FOIS par rafraîchissement, pas une fois par bouton.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("fader_pickup", True):
        return set()
    attente = set()
    for i, f in enumerate(faders_instantane()):
        exe = f.get("exec")
        st = etat.E.PICKUP.get(i)
        if exe and st is not None and not st["pris"]:
            attente.add(exe)
    return attente


# ── Roues encodeuses : suivre l'Encoder Bar de MA3 ─────────────────────────
#
# Même moule que `kind_selon_ma3`/`token_selon_ma3` : MA3 fait autorité quand le
# suivi est actif, y compris quand il ne dit rien (sélection vide → rien, comme
# une roue tournée en face de rien sur une vraie console).
#
# 🔑🔑 NE JAMAIS lire `c["nom"]` pour piloter : vérifié en direct sur un vrai
# projecteur (« Spot 1 », 32 canaux), `nom` (h.name) vaut le nom du FIXTURE
# pour tous les canaux. `subattribut` (h.SUBATTRIBUTE) donne les vrais
# mots-clés (`Focus1`, `Shutter1` — pas les libellés « Focus », « Shutter »).
def enc_attr_selon_ma3(configures: list) -> list:
    """4 attributs à envoyer aux roues. `configures` = le groupe statique du
    profil, retourné tel quel si le suivi est inactif ou la sonde muette.

    Sélection MA3 vide ou sans canal remonté → `[None]*4` : rien n'est
    envoyé, jamais une valeur inventée ou périmée du groupe configuré.
    """
    import wing_ui as core
    if not etat.E.SETTINGS.get("encodeurs_ma3", False):
        return configures
    if not core.ma3_etat().get("actif"):
        return configures                         # pas de sonde : comme avant
    enc = core.ma3_encodeurs()
    if not enc.get("selection"):
        _suivi_dit("enc", "journal.roue.rien_selectionne")
        return [None, None, None, None]
    attrs = [c.get("subattribut") for c in (enc.get("canaux") or [])
             if isinstance(c, dict) and c.get("subattribut")]
    if not attrs:
        _suivi_dit("enc", "journal.roue.sans_attribut")
        return [None, None, None, None]
    return (attrs + [None, None, None, None])[:4]


# ── Configuration d'un fader à partir d'une requête de l'interface ───────────
#
# Sortie de `wing_handler._post_fader` (audit du 25/09/2026, point D3) : le
# Handler construisait lui-même la configuration ET le libellé de la commande
# MA3, avec des `int(body.get(...))` sans borne. Il ne fait plus que lire la
# requête, appeler ceci, et ranger le résultat.
# Les types de fader viennent de `wm.KINDS_FADER` — la même liste que la
# validation des profils chargés (`wm.valider_types`) : un fader créé par
# l'interface a donc toujours une forme qu'un rechargement acceptera.
def config_fader(body) -> tuple:
    """(configuration, libellé MA3 pour le journal, suivre) d'un fader.
    Lève `wing_validation.EntreeInvalide` sur un paramètre invalide."""
    import wing_ui as core
    import wing_mapper as wm
    import wing_validation as v
    kind = v.choix(body, "kind", sorted(wm.KINDS_FADER), "executor")
    suivre = v.booleen(body, "suivre", True)
    if kind == "gm":
        return {"kind": "gm"}, "GrandMaster", True
    if kind == "selected":
        num = v.entier(body, "num", 1, 99, 2)
        return ({"kind": "selected", "num": num},
                f"Master 1.{num} ({core.MASTERS_SELECTION.get(num, '?')})", True)
    if kind in ("speed", "faderspeed"):
        unit = v.choix(body, "unit", sorted(core.SPEED_UNITS), "bpm")
        # 0-225 : plage native d'un Speed Master MA3 (BPM).
        lo = v.reel(body, "min", -1e6, 1e6, 0.0)
        hi = v.reel(body, "max", -1e6, 1e6, 225.0)
        plage = f"{core.SPEED_UNITS[unit]} {lo}-{hi}"
        if kind == "speed":
            num = v.entier(body, "num", 1, 99, 1)
            return ({"kind": "speed", "num": num, "unit": unit,
                     "min": lo, "max": hi},
                    f"Speed Master {num} ({plage})", True)
        exe = v.entier(body, "exec", 1, 99999, 101)
        # `suivre` stocké comme pour les autres faders d'executor : l'interface
        # affiche la case pour ce type, elle doit donc avoir un effet.
        return ({"kind": "faderspeed", "exec": exe, "unit": unit,
                 "min": lo, "max": hi, "suivre": suivre},
                f"FaderSpeed Executor {exe} ({plage})", suivre)
    # Types en pourcentage (executor, crossfade…) : `suivre` = ce fader
    # obéit-il à MA3 ? Réglage PAR fader — la sérigraphie d'une wing ne
    # correspond pas forcément à la configuration du show.
    exe = v.entier(body, "exec", 1, 99999, 101)
    return ({"kind": kind, "exec": exe, "suivre": suivre},
            f"{core.FADER_KEYWORDS[kind]} Executor {exe}", suivre)
