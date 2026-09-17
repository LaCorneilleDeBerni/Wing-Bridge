"""OSC entrant (observation), cible OSC/réglages machine, journal serveur.

⚠️ Même motif que les modules déjà extraits : `import wing_ui as core` DANS
chaque fonction, et toute donnée qui reste dans `wing_ui.py` s'y accède par
`core.X`, jamais en référence nue.

⚠️⚠️ CE MODULE CONTIENT `log()` ET `_log_to_file()` — les deux fonctions les
plus largement monkeypatchées de tout le projet. `smoke_test.py` fait
`ui.log = lambda ...` (souvent une lambda qui CAPTURE les messages dans une
liste pour les inspecter après coup, pas seulement un no-op) et
`ui._log_to_file = lambda m: None`, une bonne vingtaine de fois à elles deux,
TOUJOURS par réassignation complète (jamais une mutation). Toute fonction de
CE fichier qui appelle `log(...)` ou `_log_to_file(...)` — y compris
`log_init()`, qui vit dans ce même fichier — DOIT donc écrire
`core.log(...)`/`core._log_to_file(...)`, jamais l'appel nu : un appel nu se
résoudrait dans l'espace de noms de CE module, où le monkeypatch posé sur
`wing_ui` n'a aucun effet. Validé concrètement par le contrôle 39 (« Un
branchement raté laisse une trace ») : il repose sur `wing_init.JOURNAL =
ui.log_init` (le VRAI `log_init`, pas un mock) pour vérifier que le message
capturé par `ui.log` remonte bien jusqu'au journal — si `log_init` appelait
`log()` en nu, le message ne serait JAMAIS capturé, silencieusement.

L'ÉTAT PARTAGÉ se lit et s'écrit via `etat.E.<champ>` (etat.py, audit du
25/09/2026, D1) — jamais via `wing_ui`, dont les anciens noms lèvent.
`etat.E.OSC` est RECRÉÉ par `apply_osc_target()` (réassignation, jamais
`global OSC`) ; `etat.E.MA3_CHECK` y est invalidé.

`OSC_IN`/`OSC_IN_MAX_ADDR`/`OSC_IN_HIST`/`LOG` déménagent mais restent
RÉ-EXPORTÉS : lus (parfois mutés — `.clear()`, écriture de clé) par des
routes HTTP pas encore découpées. Aucun n'est jamais RÉASSIGNÉ en bloc par
ce code externe, donc la référence nue là-bas reste sûre après ré-export.
"""

import etat
import atexit
import json
import os
import queue
import re
import shutil
import socket
import threading
import time
from collections import deque

import wing_bridge as wb
import wing_mapper as wm
from pythonosc import udp_client


# ── OSC entrant (observation) ────────────────────────────────────────────────
# Port 0 = écoute désactivée (défaut). Ne PAS mettre 8000 par défaut : sur la
# même machine, c'est le port sur lequel MA3 écoute déjà.
OSC_IN = {
    "port":    0,          # port réellement lié (0 = pas d'écoute)
    "sock":    None,
    "error":   "",
    "count":   0,          # total de messages reçus depuis le démarrage
    "seen":    {},         # adresse → {"n", "last", "types", "t"}
    "lock":    threading.Lock(),
}
OSC_IN_MAX_ADDR = 200      # garde-fou mémoire si MA3 émet des adresses variées
# Historique CHRONOLOGIQUE des derniers messages. Le résumé par adresse dit
# QUELLES fonctions transitent ; il ne dit pas dans quel ORDRE. Or c'est
# l'ordre qui donne le sens des valeurs (ex. « Go+ » puis « Off, 1 » : que
# vaut le 1 ?). Borné, donc sans risque pour la mémoire.
OSC_IN_HIST = deque(maxlen=400)


def osc_in_bind(port: int):
    """(Re)lie le socket d'écoute. port=0 → arrête l'écoute."""
    import wing_ui as core
    old = OSC_IN["sock"]
    if old:
        try:
            old.close()
        except Exception:
            pass
    OSC_IN["sock"], OSC_IN["port"], OSC_IN["error"] = None, 0, ""
    if not port:
        return True
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("", port))
        s.settimeout(0.5)
        OSC_IN["sock"], OSC_IN["port"] = s, port
        core.log("journal.osc.ecoute", port=port)
        return True
    except Exception as e:
        OSC_IN["error"] = str(e)
        core.log("journal.osc.ecoute_ko", port=port, err=e)
        return False


def osc_in_loop():
    """Reçoit et RÉSUME ce que MA3 envoie. Un résumé par adresse (compteur +
    dernière valeur) plutôt qu'un flot brut : MA3 peut émettre en continu, et
    ce qu'on cherche à savoir c'est QUELLES adresses existent et à quoi elles
    ressemblent, pas les relire une par une."""
    from pythonosc.osc_packet import OscPacket
    while True:
        s = OSC_IN["sock"]
        if s is None:
            time.sleep(0.5)
            continue
        try:
            data, src = s.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            time.sleep(0.3)
            continue
        try:
            msgs = [tm.message for tm in OscPacket(data).messages]
        except Exception:
            # Paquet non-OSC (ou dialecte inattendu) : on le signale une fois
            # sous une pseudo-adresse plutôt que de le jeter en silence.
            msgs = []
            with OSC_IN["lock"]:
                e = OSC_IN["seen"].setdefault("<non-OSC>", {"n": 0, "last": "",
                                                            "types": "", "t": 0})
                e["n"] += 1
                e["last"] = repr(data[:40])
                e["t"] = time.time()
                OSC_IN["count"] += 1
            continue
        for m in msgs:
            with OSC_IN["lock"]:
                OSC_IN["count"] += 1
                if m.address not in OSC_IN["seen"] and \
                        len(OSC_IN["seen"]) >= OSC_IN_MAX_ADDR:
                    continue
                e = OSC_IN["seen"].setdefault(m.address, {"n": 0, "last": "",
                                                          "types": "", "t": 0})
                e["n"] += 1
                e["last"] = ", ".join(str(p) for p in m.params)[:120]
                e["types"] = ", ".join(type(p).__name__ for p in m.params)
                e["t"] = time.time()
                e["from"] = src[0]
                # Phase d'observation : la dernière valeur seule ne dit rien
                # d'utile (on la lit toujours au repos). Ce qu'on cherche à
                # savoir c'est QUELLES fonctions transitent sur une adresse et
                # SUR QUELLE ÉCHELLE varient les valeurs (0-1 ? 0-100 ?) —
                # indispensable pour interpréter les faders plus tard.
                fonctions = e.setdefault("fn", [])
                for p in m.params:
                    if isinstance(p, str) and p not in fonctions and len(fonctions) < 12:
                        fonctions.append(p)
                nums = [p for p in m.params if isinstance(p, (int, float))
                        and not isinstance(p, bool)]
                if nums:
                    v = float(nums[-1])
                    e["min"] = v if "min" not in e else min(e["min"], v)
                    e["max"] = v if "max" not in e else max(e["max"], v)
                OSC_IN_HIST.append({
                    "t": time.strftime("%H:%M:%S"),
                    "addr": m.address,
                    "params": ", ".join(str(p) for p in m.params)[:100],
                })


def valid_osc_target(ip: str, port: int):
    """Renvoie (ip, port) nettoyés, ou lève ValueError avec un message clair.
    On accepte une IPv4 ou un nom d'hôte : MA3 peut tourner sur une machine
    désignée par son nom sur le réseau du théâtre."""
    import wing_i18n
    ip = (ip or "").strip()
    if not ip:
        raise ValueError(wing_i18n.L("err.reglages.adresse_vide"))
    if len(ip) > 255 or any(c.isspace() for c in ip):
        raise ValueError(wing_i18n.L("err.reglages.adresse_invalide"))
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", ip):
        raise ValueError(wing_i18n.L("err.reglages.adresse_caracteres"))
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise ValueError(wing_i18n.L("err.port_invalide"))
    if not (1 <= port <= 65535):
        raise ValueError(wing_i18n.L("err.reglages.port_hors_plage"))
    return ip, port


def apply_osc_target(ip: str, port: int):
    """Recrée le client OSC à chaud. `wb.MA3_IP` est mis à jour aussi car
    ma3_reachable() s'en sert pour décider si la cible est locale.

    ⚠️ `etat.E.OSC = …`, PAS `global OSC` : ce module n'est pas `wing_ui`, un
    `global` ici ne réassignerait que sa propre variable de module, invisible
    du reste du projet qui lit `etat.E.OSC`. Même piège que `PROFILE`."""
    import wing_ui as core
    wb.MA3_IP, wb.MA3_PORT = ip, port
    core.reglage_poser(ma3_ip=ip, ma3_port=port)
    etat.E.OSC = udp_client.SimpleUDPClient(ip, port)
    etat.E.MA3_CHECK["t"] = 0.0        # invalide le cache de détection de MA3


def load_settings():
    """Charge les réglages machine au démarrage. Un fichier illisible ne doit
    JAMAIS empêcher l'app de démarrer : on repart des défauts en le signalant."""
    import wing_ui as core
    try:
        if SETTINGS_FILE.exists():
            d = json.load(open(SETTINGS_FILE, encoding="utf-8"))
            ip, port = valid_osc_target(d.get("ma3_ip", wb.MA3_IP),
                                        d.get("ma3_port", wb.MA3_PORT))
            apply_osc_target(ip, port)
            try:
                pin = int(d.get("osc_in_port", 0))
                core.reglage_poser(osc_in_port=pin if 0 <= pin <= 65535 else 0)
            except (TypeError, ValueError):
                core.reglage_poser(osc_in_port=0)
            # Ces cases sont RELUES au démarrage : un réglage qu'on écrit sans le relire
            # n'est pas un réglage, c'est un bouton sans fil.
            for cle in ("suivre_ma3", "fader_pickup", "verbe_cible",
                        "encodeurs_ma3", "dmx_local"):
                if cle in d:
                    core.reglage_poser(**{cle: bool(d[cle])})
            # `plugin_slot` : entier, pas un booléen — bornes 1..9999 (borne
            # PRATIQUE, pas documentée par le manuel MA3 comme un plafond du
            # pool Plugins : rien trouvé dans keyword_plugin.html/plugins.html
            # à ce sujet, donc pas de chiffre MA3 présenté comme un fait). Une
            # valeur hors bornes ou illisible retombe sur le défaut (3) plutôt
            # que de faire échouer tout le chargement des réglages.
            if "plugin_slot" in d:
                try:
                    slot = int(d["plugin_slot"])
                    core.reglage_poser(plugin_slot=slot if 1 <= slot <= 9999 else 3)
                except (TypeError, ValueError):
                    core.reglage_poser(plugin_slot=3)
            # ⭐ Profil favori — réglage MACHINE et non de profil : il DÉSIGNE
            # un profil, il ne peut donc pas vivre dedans (un profil qui se
            # déclare favori se propagerait à chaque copie).
            fav = d.get("profil_favori")
            core.reglage_poser(profil_favori=str(fav) if fav else "")
            # Horodate du dernier envoi réussi des raccourcis — None si jamais
            # envoyés ou valeur illisible, jamais une exception qui ferait
            # échouer tout le chargement des réglages.
            h = d.get("shcuts_horodate")
            try:
                core.reglage_poser(shcuts_horodate=float(h) if h else None)
            except (TypeError, ValueError):
                core.reglage_poser(shcuts_horodate=None)
            return
    except Exception as e:
        core.log("journal.settings.illisible", err=e)
    apply_osc_target(wb.MA3_IP, wb.MA3_PORT)


_SAVE_SETTINGS_LOCK = threading.Lock()


def save_settings():
    import wing_ui as core
    try:
        SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Écriture ATOMIQUE (temp-file + os.replace) — même motif que le
        # reste du projet : une coupure en plein milieu de l'écriture DIRECTE
        # laissait un `settings.json` tronqué, illisible au prochain
        # démarrage (repli silencieux sur les défauts, réglages perdus).
        #
        # 🔒 Sérialisé SOUS verrou (audit du 25/09/2026, I8) : `json.dumps`
        # parcourt SETTINGS, et un autre fil qui y ajoutait une clé au même
        # moment faisait lever « dictionary changed size during iteration »
        # — rattrapé plus bas, sauvegarde perdue sans bruit. La sérialisation
        # d'une dizaine de clés est instantanée ; l'écriture disque reste
        # HORS verrou (règle test_lock_sans_appel_lent).
        # Fichier temporaire PROPRE à l'appel (pid + fil) : deux sauvegardes
        # simultanées ne se marchent plus dessus.
        with etat.E.LOCK:
            texte = json.dumps(etat.E.SETTINGS, indent=2)
        tmp = SETTINGS_FILE.with_name(
            f"{SETTINGS_FILE.name}.{os.getpid()}.{threading.get_ident()}.part")
        tmp.write_text(texte, encoding="utf-8")
        # 🪟 Test réel Windows du 26/09/2026 (même constat que wing_mapper.
        # save_profile) : `os.replace()` peut lever un accès refusé
        # intermittent (WinError 5) quand deux fils remplacent la MÊME
        # destination en même temps — `rename(2)` POSIX ne connaît pas ce cas.
        with _SAVE_SETTINGS_LOCK:
            os.replace(tmp, SETTINGS_FILE)
        wm.own_like_parent(SETTINGS_FILE)
        return True
    except Exception as e:
        core.log("journal.settings.save_ko", err=e)
        return False


SETTINGS_FILE = wm.PROFILE_DIR.parent / "settings.json"


# ── Journal serveur (mémoire + disque) ───────────────────────────────────────
# Sur disque aussi : un redémarrage (os.execv) efface la mémoire, et quelqu'un
# qui dit « ça marche pas » doit avoir une trace à envoyer.
LOG = deque(maxlen=300)          # mémoire — c'est ce qu'affiche l'interface
LOG_FILE       = wm.PROFILE_DIR.parent / "wing_server.log"
LOG_MAX_BYTES  = 1_000_000       # ~1 Mo, puis rotation
LOG_ARCHIVE_MAX = 12             # nombre de sauvegardes de session conservées
_log_file_lock = threading.Lock()

# 🔑 Désinstallation : pendant le ménage final (`wing_desinstall.executer`), on
# EFFACE le dossier de données. Ce drapeau coupe l'écriture disque du journal —
# sinon une ligne tardive recrée le dossier (coquille vide constatée sous
# Windows).
_arret_en_cours = False


def _rotate_log_if_needed():
    """Une seule archive conservée (.1) : on veut un historique utile, pas
    remplir le disque de quelqu'un pendant une tournée."""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > LOG_MAX_BYTES:
            vieux = LOG_FILE.parent / (LOG_FILE.name + ".1")
            os.replace(LOG_FILE, vieux)
            wm.own_like_parent(vieux)
    except Exception:
        pass


def archiver_session_precedente():
    """Sauvegarde HORODATÉE de wing_server.log, prise à chaque démarrage
    AVANT que la nouvelle session n'y écrive quoi que ce soit (appelée depuis
    `wing_ui.main()`, juste avant le séparateur « DÉMARRAGE »).

    Différent de `_rotate_log_if_needed()` : celle-ci déclenche sur un SEUIL
    DE TAILLE (1 Mo) et n'en garde qu'UNE (`.1`, écrasée à chaque nouvelle
    rotation) — une session courte peut donc disparaître si la session
    suivante génère beaucoup de volume avant d'avoir été consultée (constaté :
    le fichier n'avait pourtant pas tourné, mais la confusion montrait qu'une
    seule sauvegarde ne suffit pas à couvrir « avant que
    j'aie eu le temps de regarder »). Ici, chaque DÉMARRAGE fige un
    instantané séparé, sans dépendre de la taille ; les `LOG_ARCHIVE_MAX`
    plus récents sont gardés, le fichier courant n'est ni renommé ni tronqué.
    """
    try:
        if not LOG_FILE.exists() or LOG_FILE.stat().st_size == 0:
            return
        horodatage = time.strftime("%Y%m%d-%H%M%S")
        archive = LOG_FILE.parent / f"{LOG_FILE.stem}-{horodatage}{LOG_FILE.suffix}"
        shutil.copy2(LOG_FILE, archive)
        wm.own_like_parent(archive)
        archives = sorted(LOG_FILE.parent.glob(f"{LOG_FILE.stem}-*{LOG_FILE.suffix}"))
        for vieille in archives[:-LOG_ARCHIVE_MAX]:
            vieille.unlink(missing_ok=True)
    except Exception:
        pass          # une sauvegarde ratée ne doit JAMAIS faire tomber l'app


# ── Journal en CLÉS (i18n serveur) ───────────────────────────────────────────
#
# Depuis la Phase 2 i18n, `LOG` (le deque en mémoire) ne stocke plus des
# chaînes déjà formées mais des entrées STRUCTURÉES :
#
#   {"hc": "HH:MM:SS", "hl": "YYYY-MM-DD HH:MM:SS",
#    "cle": "journal.xxx" | None, "params": {...}, "n": int | None,
#    "brut": "texte déjà formé" | None}
#
# Deux familles :
#   • `cle` renseignée  → ligne TRADUISIBLE. Résolue à l'affichage :
#       - `/api/status` la rend dans `wing_i18n.LANGUE` (langue de l'app) —
#         un POST /api/lang re-traduit donc TOUT l'historique en mémoire au
#         prochain poll ;
#       - le disque (`_log_to_file`) la rend en `L_en` — le fichier
#         `wing_server.log` est TOUJOURS anglais, quelle que soit la langue.
#   • `brut` renseignée → passe-plat : texte qui n'a pas à être traduit
#     (dumps de debug, traces hex, lignes « ENC1 Pan +12 »…). Écrit tel quel
#     des deux côtés.
#
# `log(cle_ou_texte, **params)` choisit : un argument qui commence par un
# namespace connu (`journal.` `err.` `firmware.` `diag.`) → entrée à clé ;
# sinon → entrée brute. `log_plural(cle, n, **params)` pour les lignes dont
# la forme dépend d'un compte.
_NS_TRAD = ("journal.", "err.", "firmware.", "diag.")


def _horodates():
    t = time.localtime()
    return (time.strftime("%H:%M:%S", t), time.strftime("%Y-%m-%d %H:%M:%S", t))


def _rendre_entree(entree, langue: str) -> str:
    """Une entrée structurée → sa ligne de texte dans `langue`.
    Tolère une chaîne nue (entrées d'avant la Phase 2, ou appel direct)."""
    if not isinstance(entree, dict):
        return str(entree)
    if entree.get("brut") is not None:
        return entree["brut"]
    try:
        import wing_i18n
        return wing_i18n.rendre(entree.get("cle"), entree.get("params"),
                                entree.get("n"), langue)
    except Exception:
        return entree.get("cle") or ""


def journal_affiche(n: int = 60):
    """Les `n` dernières lignes du journal, rendues dans la langue COURANTE
    de l'app — c'est ce que renvoie `/api/status` (champ `log`)."""
    import wing_i18n
    lignes = []
    for e in list(LOG)[-n:]:
        if isinstance(e, dict):
            lignes.append(f"[{e.get('hc', '')}] "
                          + _rendre_entree(e, wing_i18n.LANGUE))
        else:
            lignes.append(str(e))          # ceinture : entrée d'un ancien format
    return lignes


# ── Écriture DIFFÉRÉE du journal (audit du 25/09/2026) ────────────────────
#
# 🟠 `_log_to_file` ouvrait, écrivait et refermait le fichier (rotation
# comprise, sous verrou) À CHAQUE LIGNE — y compris depuis `usb_loop`, la
# boucle la plus chaude du projet, qui journalise un cran de roue sur deux. Un
# disque qui traîne (Spotlight, Time Machine, dossier réseau, antivirus)
# ralentissait donc la wing elle-même. C'est la règle « jamais d'appel lent
# sous etat.E.LOCK », violée par une autre voie.
#
# Désormais l'appelant DÉPOSE l'entrée dans une file et repart : un seul fil
# (`_ecrivain_journal`) touche au disque, par lots. La mise en forme (rendu
# anglais) part avec lui, hors de la boucle.
#
# ⚠️ Le prix : une ligne peut rester en file quand le process meurt. Trois
# filets : `atexit`, et `vider_journal()` appelé explicitement avant chaque
# `os._exit` / `os.execv` (qui sautent atexit) ; une file PLEINE (disque
# bloqué) ne bloque jamais l'appelant — la ligne est comptée perdue, et le
# compte est écrit dès que le disque revient.
# Contrôle test_journal_hors_boucle (smoke_securite.py).
JOURNAL_FILE_MAX = 10_000
_FILE_DISQUE = queue.Queue(maxsize=JOURNAL_FILE_MAX)
_ECRIVAIN = {"fil": None, "perdues": 0}
_ecrivain_lock = threading.Lock()


def _ligne_disque(entree) -> str:
    """Une entrée structurée est rendue en ANGLAIS (`L_en`) et préfixée de sa
    date complète ; une chaîne nue est écrite telle quelle (bannière
    « DÉMARRAGE », traces de crash…)."""
    if isinstance(entree, dict):
        return f"{entree.get('hl', '')}  {_rendre_entree(entree, 'en')}"
    return str(entree)


def _ecrire_lot(lot):
    """Écrit un lot [(entrée, fichier)] — SEUL endroit qui touche au disque."""
    par_fichier = {}
    for entree, fichier in lot:
        par_fichier.setdefault(fichier, []).append(_ligne_disque(entree))
    with _log_file_lock:
        if _arret_en_cours:
            return                # ménage de désinstallation : plus de disque
        for fichier, lignes in par_fichier.items():
            try:
                if fichier == LOG_FILE:
                    _rotate_log_if_needed()
                nouveau = not fichier.exists()
                fichier.parent.mkdir(parents=True, exist_ok=True)
                with open(fichier, "a", encoding="utf-8") as f:
                    f.write("".join(l + "\n" for l in lignes))
                    f.flush()
                if nouveau:
                    wm.own_like_parent(fichier)
            except Exception:
                pass      # journaliser ne doit JAMAIS faire tomber l'app


def _ecrivain_journal():
    while True:
        lot = [_FILE_DISQUE.get()]
        try:
            while len(lot) < 500:
                lot.append(_FILE_DISQUE.get_nowait())
        except queue.Empty:
            pass
        try:
            perdues, _ECRIVAIN["perdues"] = _ECRIVAIN["perdues"], 0
            if perdues:
                lot.insert(0, (f"[journal] {perdues} line(s) dropped: the "
                               "disk did not keep up", lot[0][1]))
            _ecrire_lot(lot)
        finally:
            for _ in range(len(lot) - (1 if perdues else 0)):
                _FILE_DISQUE.task_done()


def _demarrer_ecrivain():
    if _ECRIVAIN["fil"] is not None and _ECRIVAIN["fil"].is_alive():
        return
    with _ecrivain_lock:
        if _ECRIVAIN["fil"] is None or not _ECRIVAIN["fil"].is_alive():
            _ECRIVAIN["fil"] = threading.Thread(
                target=_ecrivain_journal, daemon=True, name="journal_disque")
            _ECRIVAIN["fil"].start()


def _log_to_file(entree):
    """Dépose l'entrée pour écriture différée — ne touche JAMAIS au disque.

    Le fichier cible est figé AU DÉPÔT : une ligne ne change pas de fichier
    si LOG_FILE est redirigé entre-temps (tests, désinstallation)."""
    if _arret_en_cours:
        return                # ménage de désinstallation en cours : pas de disque
    _demarrer_ecrivain()
    try:
        _FILE_DISQUE.put_nowait((entree, LOG_FILE))
    except queue.Full:
        _ECRIVAIN["perdues"] += 1


def vider_journal(delai: float = 1.0) -> bool:
    """Attend (au plus `delai` s) que tout ce qui est en file soit écrit.
    À appeler avant `os._exit` / `os.execv`, qui ne laissent pas finir le fil
    d'écriture. Rend True si la file est vide."""
    fin = time.monotonic() + delai
    while _FILE_DISQUE.unfinished_tasks and time.monotonic() < fin:
        time.sleep(0.005)
    return not _FILE_DISQUE.unfinished_tasks


atexit.register(vider_journal)


def _journaliser(cle, params, n, brut):
    import wing_ui as core
    hc, hl = _horodates()
    entree = {"hc": hc, "hl": hl, "cle": cle, "params": params,
              "n": n, "brut": brut}
    LOG.append(entree)
    core._log_to_file(entree)


def log(cle_ou_texte, **params):
    """Journalise une ligne. Si `cle_ou_texte` commence par un namespace i18n
    connu → entrée traduisible `{cle, params}` ; sinon → passe-plat brut."""
    if isinstance(cle_ou_texte, str) and cle_ou_texte.startswith(_NS_TRAD):
        _journaliser(cle_ou_texte, params, None, None)
    else:
        _journaliser(None, {}, None, str(cle_ou_texte))


def log_plural(cle, n, **params):
    """Journalise une ligne dont la FORME dépend de `n` (pluriel).
    `cle` est un préfixe : le catalogue porte `cle.one` / `cle.other`."""
    _journaliser(cle, params, n, None)


def _rendre_appel(cle_ou_texte="", n=None, **params):
    """Aide aux tests : rend EN FRANÇAIS ce qu'un `log(...)` / `log_plural(...)`
    afficherait, sans toucher au deque ni au disque. Les monkeypatches
    `smoke_*.py` qui CAPTURENT le journal passent par ici, pour continuer à
    voir une phrase (et pas une clé brute) après la conversion en clés."""
    import wing_i18n
    if isinstance(cle_ou_texte, str) and cle_ou_texte.startswith(_NS_TRAD):
        return wing_i18n.rendre(cle_ou_texte, params, n, "fr")
    return str(cle_ou_texte)


# Les messages d'initialisation de la wing passent par le journal de l'app, pas
# par stdout : lancée depuis le Finder, l'app n'a pas de console où les lire, et
# ce sont justement ceux qui expliquent une wing qui ne répond pas.
#
# ⚠️ Avec anti-répétition : l'auto-reconnexion peut échouer en boucle pendant
# des minutes. Sans ça, le journal se remplit de 60 lignes identiques et noie
# tout le reste — constaté, le journal ne montrait plus que ça.
_INIT_MSG = {"dernier": (), "n": 0}


def log_init(msg, **params):
    """⚠️ Appelé en retour par `wing_init.py` via `wing_init.JOURNAL` — y
    compris pendant `smoke_test.py`, qui réassigne `ui.log` (parfois pour en
    CAPTURER le contenu) sans toucher à `log_init` lui-même. Chaque appel à
    `log(...)` ici doit donc être `core.log(...)` : un appel nu se
    résoudrait dans ce module, jamais dans le `wing_ui` patché.

    `msg` est une clé `journal.*` (+ `params`) depuis la Phase 2 i18n, ou un
    texte nu (passe-plat). L'anti-répétition dédoublonne sur (clé, params)."""
    import wing_ui as core
    signature = (msg, tuple(sorted(params.items(), key=lambda kv: kv[0])))
    if signature == _INIT_MSG["dernier"]:
        _INIT_MSG["n"] += 1
        if _INIT_MSG["n"] in (5, 20, 100):      # jalons, pas chaque fois
            core.log_plural("journal.init.repete", _INIT_MSG["n"])
        return
    if _INIT_MSG["n"]:
        core.log_plural("journal.init.repete_total", _INIT_MSG["n"])
    _INIT_MSG.update(dernier=signature, n=0)
    core.log(msg, **params)
