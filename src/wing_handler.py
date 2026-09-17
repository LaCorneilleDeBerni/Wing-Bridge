"""Le serveur HTTP : toutes les routes /api/... et la page d'accueil.

⚠️ Appelle presque tout le reste. L'ÉTAT PARTAGÉ se lit et s'écrit via
`etat.E.<champ>` (etat.py, audit du 25/09/2026, D1) — jamais via `wing_ui`,
dont les anciens noms lèvent. Les FONCTIONS réexportées par `wing_ui.py`
(`log`, `connect_wing`, `ma3_*`, `shcuts_*`…) et les constantes/chemins
(`FADER_KEYWORDS`, `REFERENCE_FILE`, `UI_PORT`…) s'appellent via `core.X`,
importé paresseusement dans chaque méthode.

⚠️ `etat.E.PROFILE = p` explicitement dans `_post_profile_load`,
`_post_profile_recover`, `_post_profile_new`, `_post_reference_restore` :
un `global PROFILE` ne réassignerait que l'espace de noms de CE module.

`HTML`/`_lire_js`/`JS_FICHIERS`/`JS_DIR`/`_JS_CACHE` (page d'accueil et
fichiers `ui/*.js`) restent dans `wing_ui.py` — accédés en
`core.HTML`/`core._lire_js(...)` depuis `_get_page`/`_get_js`.

`wb` (wing_bridge), `wm` (wing_mapper), `wing_init`, `wing_detect` sont des
singletons importés directement ici, comme partout ailleurs dans le
projet : un monkeypatch posé dessus par `smoke_test.py` (ex.
`ui.wing_init.wing_absente = …`) mute l'objet module lui-même, visible de
partout qui l'importe — pas besoin de `core.wb`/`core.wm`.
"""

import etat
import hmac
import json
import re
import subprocess
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler
from pathlib import Path

import wing_bridge as wb
import wing_desinstall
import wing_dialogues
import wing_firmware
import wing_statut
import wing_detect
import wing_boutons
import wing_faders
import wing_init
import wing_profils
import wing_jeton
import wing_ma3
import wing_mapper as wm
import wing_validation as wv




def _L(cle, **params):
    """Résout une clé i18n dans la LANGUE courante de l'app — pour les
    `raison`/`message` des réponses JSON QUI SONT AFFICHÉS dans l'interface.
    Le journal disque et le diagnostic restent anglais (voir wing_i18n)."""
    import wing_i18n
    return wing_i18n.L(cle, **params)


class Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):   # silence les logs HTTP
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        # Même raison que pour la page : /api/profile et /api/status changent à
        # chaque instant. Une réponse mise en cache ferait afficher un état mort.
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # 🛟 Corps de requête validé, erreurs rendues en JSON : corps invalide → 400,
    # exception dans une route → 500, les deux journalisées — jamais une connexion
    # coupée sans réponse (l'interface ne voyait qu'une « erreur réseau »), ni
    # `rfile.read(-1)` sur une longueur négative (fil de requête bloqué).
    # Contrôle test_handler_robuste.
    CORPS_MAX = 5_000_000          # un profil pèse quelques dizaines de ko

    class RequeteInvalide(Exception):
        """Corps de requête inexploitable → réponse 400."""

    def _read_body(self):
        brut = self.headers.get("Content-Length", 0)
        try:
            length = int(brut or 0)
        except (TypeError, ValueError):
            raise Handler.RequeteInvalide(_L("err.http.longueur_illisible",
                                             v=repr(brut)[:40]))
        if length < 0 or length > self.CORPS_MAX:
            raise Handler.RequeteInvalide(_L("err.http.longueur_bornes", n=length))
        if not length:
            return {}
        try:
            corps = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeDecodeError) as e:
            raise Handler.RequeteInvalide(_L("err.http.json_invalide", e=e))
        if not isinstance(corps, dict):
            raise Handler.RequeteInvalide(
                _L("err.http.pas_un_objet", t=type(corps).__name__))
        return corps

    def send_response(self, code, message=None):
        # Mémorise qu'une réponse est PARTIE : si une route lève après avoir
        # commencé à répondre, en renvoyer une seconde corromprait le flux.
        self._repondu = True
        super().send_response(code, message)

    def _executer(self, route, *args):
        """Exécute une route ; toute exception devient un 500 JSON journalisé."""
        import wing_ui as core
        self._repondu = False
        try:
            route(*args)
        except wv.EntreeInvalide as e:
            # Paramètre refusé par wing_validation : c'est la REQUÊTE qui est
            # fausse, pas le moteur → 400 avec la raison, pas un 500.
            # JOURNALISÉ : l'interface ignore souvent la réponse d'un réglage ;
            # sans cette ligne, un champ refusé paraîtrait enregistré.
            core.log("journal.http.entree_refusee",
                     chemin=self.path.split("?", 1)[0], detail=str(e)[:200])
            if not getattr(self, "_repondu", False):
                self._json({"error": _L("err.http.requete_invalide"),
                            "detail": str(e)}, 400)
        except (BrokenPipeError, ConnectionResetError):
            pass                    # le client est parti : rien à lui dire
        except Exception as e:
            import traceback
            tb = traceback.extract_tb(e.__traceback__)
            ou = f"{Path(tb[-1].filename).name}:{tb[-1].lineno}" if tb else "?"
            core.log("journal.http.erreur_route", methode=self.command,
                     chemin=self.path.split("?", 1)[0], type=type(e).__name__,
                     err=str(e)[:200], ou=ou)
            if not getattr(self, "_repondu", False):
                try:
                    self._json({"error": _L("err.http.erreur_interne"),
                                "detail": f"{type(e).__name__}: {e}"[:300]}, 500)
                except Exception:
                    pass

    # ── Garde-fou : d'où vient cette requête ? ───────────────────────────────
    #
    # 🔒 Le serveur n'écoute que sur 127.0.0.1, ce qui empêche
    # d'être joint depuis le réseau — mais PAS depuis le navigateur de la
    # machine. Une page web quelconque, ouverte pendant que l'app tourne, peut
    # poster sur http://127.0.0.1:8765/api/… : le navigateur bloque la LECTURE
    # de la réponse (CORS), pas l'ENVOI de la requête. `/api/hard_reset`,
    # `/api/quit` ou `/api/profile/delete` partiraient donc quand même.
    #
    # Deux vérifications, toutes deux nécessaires :
    #   • `Origin` : présent sur toute requête inter-sites → on refuse s'il
    #     n'est pas le nôtre. Absent = appel local hors navigateur (l'assistant
    #     clavier en urllib), qu'on laisse passer.
    #   • `Host` : couvre le « DNS rebinding », où un nom appartenant à
    #     l'attaquant est résolu vers 127.0.0.1. L'Origin serait alors
    #     cohérent, mais le Host trahit le détour.
    #
    # ⚠️ Ces deux en-têtes ne couvrent PAS un programme local hors navigateur
    # (il n'envoie pas d'Origin) : c'est le rôle du jeton d'API, vérifié juste
    # en dessous (`_jeton_valide`). Toujours aucun mot de passe : le jeton
    # voyage dans la page, l'app reste utilisable en tapant l'adresse dans le
    # navigateur, en régie, sans rien avoir à retenir.
    def _origine_sure(self) -> bool:
        import wing_ui as core
        attendus = {f"127.0.0.1:{core.UI_PORT}", f"localhost:{core.UI_PORT}"}
        hote = (self.headers.get("Host") or "").strip().lower()
        if hote and hote not in attendus:
            return False
        origine = (self.headers.get("Origin") or "").strip().lower()
        if origine:
            return origine.split("//", 1)[-1] in attendus
        return True

    # ── Garde-fou n°2 : le jeton d'API ───────────────────────────────────────
    #
    # 🔒 Audit du 25/09/2026. `_origine_sure` laisse passer toute requête SANS
    # en-tête Origin — c'est-à-dire tout programme local hors navigateur,
    # depuis n'importe quel compte de la machine. Tout POST et
    # `GET /api/keystrokes` exigent donc en plus le jeton de ce lancement
    # (en-tête X-Wing-Jeton, ou `?jeton=` pour sendBeacon qui ne sait pas
    # poser d'en-tête). `_origine_sure` reste en place : défense en profondeur.
    # ⚠️ Limite assumée : la page servie contient le jeton — voir wing_jeton.py.
    def _jeton_valide(self) -> bool:
        import wing_ui as core
        fourni = (self.headers.get(wing_jeton.EN_TETE) or "").strip()
        if not fourni:
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            fourni = (q.get(wing_jeton.PARAM) or [""])[0]
        # compare_digest : temps constant, pas d'indice octet par octet.
        return bool(fourni) and hmac.compare_digest(
            fourni.encode("utf-8", "replace"), core.API_JETON.encode())

    # Un ancien assistant clavier (sans jeton) sonde toutes les secondes : sans
    # limite, le journal recevrait une ligne par seconde. Une par route / 30 s.
    _JETON_REFUS_VU = {}

    def _refuser_jeton(self):
        import wing_ui as core
        chemin = urllib.parse.urlparse(self.path).path
        maintenant = time.monotonic()
        if maintenant - Handler._JETON_REFUS_VU.get(chemin, -1e9) >= 30.0:
            Handler._JETON_REFUS_VU[chemin] = maintenant
            core.log("journal.http.jeton_refuse", methode=self.command,
                     chemin=chemin)
        self._json({"error": "jeton invalide"}, 403)

    def _refuser_origine(self):
        # Journalisé : si ça se déclenche un jour, on veut savoir d'où.
        import wing_ui as core
        core.log("journal.http.origine_refusee", methode=self.command,
                 chemin=self.path, origin=self.headers.get('Origin', '—'),
                 host=self.headers.get('Host', '—'))
        self._json({"error": "origine non autorisée"}, 403)

    # ══ TABLES DE ROUTAGE ═══════════════════════════════════════════════════
    #
    # ⚠️ Parcourues dans l'ordre, premier match gagnant. Une chaîne = égalité
    # stricte (chemin sans la chaîne de requête), une lambda = test libre
    # (préfixes : /ui/…, /api/keystrokes, la page d'accueil). Le corps de chaque
    # route est une méthode `_get_…` / `_post_…` plus bas, dans le même ordre.

    def _router(self, table):
        """Méthode qui traite ce chemin, ou None. Premier match gagnant.

        Comparé SANS la chaîne de requête : `?jeton=…` (sendBeacon) ne doit
        pas empêcher `/api/fermeture-onglet` de trouver sa route. Les routes
        qui lisent leurs paramètres (`/api/keystrokes`) relisent `self.path`."""
        chemin = self.path.split("?", 1)[0]
        for cible, nom in table:
            if cible(chemin) if callable(cible) else chemin == cible:
                return getattr(self, nom)
        return None

    # ── GET ──────────────────────────────────────────────
    ROUTES_GET = [
        (lambda p: p == "/" or p.startswith("/index"), "_get_page"),
        (lambda p: p.startswith("/ui/") and p.endswith(".js"), "_get_js"),
        (lambda p: p.startswith("/locales/") and p.endswith(".json"), "_get_locale"),
        ("/api/status", "_get_status"),
        ("/api/instance", "_get_instance"),
        ("/api/profile", "_get_profile"),
        ("/api/attributes", "_get_attributes"),
        ("/api/fader/functions", "_get_fader_functions"),
        ("/api/assistant", "_get_assistant"),
        ("/api/shcuts", "_get_shcuts"),
        ("/api/keywords", "_get_keywords"),
        ("/api/osc/in", "_get_osc_in"),
        ("/api/usb/scan", "_get_usb_scan"),
        (lambda p: p.startswith("/api/keystrokes"), "_get_keystrokes"),
        ("/api/dmx", "_get_dmx"),
        ("/api/profiles", "_get_profiles"),
    ]

    # ── POST ─────────────────────────────────────────────
    ROUTES_POST = [
        ("/api/lang", "_post_lang"),
        ("/api/mode", "_post_mode"),
        ("/api/learn/clear", "_post_learn_clear"),
        ("/api/assign", "_post_assign"),
        ("/api/fader", "_post_fader"),
        ("/api/encoders", "_post_encoders"),
        ("/api/profile/save", "_post_profile_save"),
        ("/api/profile/load", "_post_profile_load"),
        ("/api/profile/parcourir", "_post_profile_parcourir"),
        ("/api/profile/import", "_post_profile_import"),
        ("/api/profile/favori", "_post_profile_favori"),
        ("/api/profile/delete", "_post_profile_delete"),
        ("/api/profile/reveal", "_post_profile_reveal"),
        ("/api/profile/recover", "_post_profile_recover"),
        ("/api/profile/discard_recovery", "_post_profile_discard_recovery"),
        ("/api/profile/new", "_post_profile_new"),
        ("/api/reference/restore", "_post_reference_restore"),
        ("/api/reference/set", "_post_reference_set"),
        ("/api/led", "_post_led"),
        ("/api/led/vegas", "_post_led_vegas"),
        ("/api/console/key", "_post_console_key"),
        ("/api/console/reset", "_post_console_reset"),
        ("/api/double_clic", "_post_double_clic"),
        ("/api/fader/nom", "_post_fader_nom"),
        ("/api/fader/rangee", "_post_fader_rangee"),
        ("/api/bouton/rangee", "_post_bouton_rangee"),
        ("/api/fader_pickup", "_post_fader_pickup"),
        ("/api/shcuts/envoyer", "_post_shcuts_envoyer"),
        ("/api/verbe_cible", "_post_verbe_cible"),
        ("/api/suivre_ma3", "_post_suivre_ma3"),
        ("/api/encodeurs_ma3", "_post_encodeurs_ma3"),
        ("/api/plugin_slot", "_post_plugin_slot"),
        ("/api/osc/target", "_post_osc_target"),
        ("/api/diagnostic", "_post_diagnostic"),
        ("/api/osc/listen", "_post_osc_listen"),
        ("/api/osc/listen/clear", "_post_osc_listen_clear"),
        ("/api/console/open_settings", "_post_console_open_settings"),
        ("/api/console/action_done", "_post_console_action_done"),
        ("/api/console/test", "_post_console_test"),
        ("/api/dmx/config", "_post_dmx_config"),
        ("/api/usb/probe", "_post_usb_probe"),
        (lambda p: p in ("/api/wing/connect", "/api/wing/reconnect"), "_post_wing_connect"),
        ("/api/firmware/import_capture", "_post_firmware_import_capture"),
        ("/api/firmware/import_bin", "_post_firmware_import_bin"),
        ("/api/firmware/export", "_post_firmware_export"),
        ("/api/firmware/capture", "_post_firmware_capture"),
        ("/api/firmware/capture/cancel", "_post_firmware_capture_cancel"),
        ("/api/firmware/remove_capture_component", "_post_firmware_remove_capture_component"),
        ("/api/plugin/install", "_post_plugin_install"),
        ("/api/plugin/relaunch", "_post_plugin_relaunch"),
        ("/api/fermeture-onglet", "_post_fermeture_onglet"),
        ("/api/quit", "_post_quit"),
        ("/api/hard_reset", "_post_hard_reset"),
        ("/api/uninstall", "_post_uninstall"),
        # 🔒 AUCUNE route de débogage ici. `/api/_debug_boom_usb_loop` (qui
        # tuait volontairement usb_loop) a été livrée en v1.0.0 alors que son
        # commentaire exigeait de la retirer : n'importe quel processus local
        # pouvait geler la wing d'un `curl`. Retirée le 25/09/2026 ; le
        # contrôle test_pas_de_route_debug (smoke_securite.py) refuse son retour.
        # Le filet que cette route servait à éprouver est désormais testé
        # SANS matériel par test_profil_mal_type.
    ]

    def do_GET(self):
        if not self._origine_sure():
            return self._refuser_origine()
        # La file de frappes est la seule lecture qui AGIT (elle se vide, et
        # l'assistant qui la lit tape dans MA3) : elle exige le jeton.
        if self.path.split("?", 1)[0] == "/api/keystrokes" \
                and not self._jeton_valide():
            return self._refuser_jeton()
        route = self._router(self.ROUTES_GET)
        if route is None:
            return self._json({"error": "not found"}, 404)
        self._executer(route)

    def _get_page(self):
        import wing_ui as core
        # 🔒 Le jeton d'API voyage DANS la page : ui/core.js le lit dans cette
        # balise et le joint à chaque requête (voir wing_jeton.py, limite
        # comprise). `token_urlsafe` : ni guillemet ni chevron, rien à échapper.
        body = core.HTML.replace(
            "<head>", '<head>\n<meta name="wing-jeton" content="'
            + core.API_JETON + '">', 1).encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        # 🔑 AUCUNE mise en cache de l'interface : l'app est reconstruite souvent, et
        # un navigateur qui garde la page montre une version ancienne à qui croit
        # regarder la nouvelle (« l'interface ne montre pas ce que le serveur a »).
        # La page fait ~125 ko en local : l'économie serait nulle.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_js(self):
        # ⚠️ MÊME règle que la page (`no-store`) : un JS mis en cache donnerait une page
        # fraîche avec le comportement d'hier, sans que rien ne le signale.
        import wing_ui as core
        nom = self.path[len("/ui/"):-len(".js")]
        contenu = core._lire_js(nom)
        if contenu is None:
            # Nom hors liste blanche : on ne cherche même pas le fichier.
            self._json({"error": "not found"}, 404)
            return
        body = contenu.encode()
        self.send_response(200)
        self.send_header("Content-Type",
                         "application/javascript; charset=utf-8")
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_locale(self):
        # Catalogue de traduction (i18n). MÊME RÈGLE DE CACHE QUE LA PAGE ET LE
        # JS : `no-store`. Un catalogue mis en cache après un build survivrait à
        # ses propres corrections — l'interface montrerait d'anciennes chaînes.
        import wing_ui as core
        nom = self.path[len("/locales/"):-len(".json")]
        contenu = core._lire_locale(nom)
        if contenu is None:
            # Langue hors liste blanche : on ne cherche même pas le fichier.
            self._json({"error": "not found"}, 404)
            return
        body = contenu.encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _get_instance(self):
        # Sonde du « suis-je déjà lancé ? » d'un 2ᵉ process (wing_ui._instance_
        # deja_active). NE MODIFIE RIEN — surtout pas le battement de cœur : un
        # process qui démarre ne doit pas se faire passer pour un onglet ouvert.
        import wing_ui as core
        self._json({"vivant": True,
                    "ui_active": core._ui_active(),
                    "build": core.BUILD})

    def _post_fermeture_onglet(self, body):
        # `navigator.sendBeacon` depuis `pagehide` (ui/init.js) : l'onglet se
        # ferme. On ARME un arrêt différé — `vie_loop` l'exécutera dans
        # FERMETURE_GRACE_S, SAUF si un ping d'onglet revient d'ici là (= c'était
        # un rechargement F5). Un simple arrêt du poll (veille, réseau coupé) ne
        # passe PAS par ici : la veille ne doit pas tuer l'app.
        import wing_ui as core
        etat.E.UI_VIE["arret_t"] = time.monotonic()
        core.log("journal.vie.fermeture_armee", s=f"{core.FERMETURE_GRACE_S:.0f}")
        self._json({"ok": True})

    def _get_status(self):
        import wing_ui as core
        # 💓 Battement de cœur de l'onglet : ui/init.js appelle /api/status toutes
        # les 400 ms, et RIEN d'autre ne l'appelle (l'assistant clavier ne sonde
        # que /api/keystrokes). C'est donc ici, et seulement ici, qu'on sait
        # qu'un vrai onglet est ouvert — voir wing_ui.UI_VIE / _ui_active.
        etat.E.UI_VIE["dernier_ping"] = time.monotonic()
        self._json(wing_statut.statut())

    def _get_profile(self):
        import wing_ui as core
        # 🔒 LE VERROU NE PROTÈGE QUE LA COPIE — même règle que `_get_status`.
        # `self._json()` écrit sur le SOCKET HTTP (`self.wfile.write`) : un
        # client lent (ou une coupure réseau) pouvait retarder cette écriture
        # pendant que `etat.E.LOCK` restait tenu, bloquant `usb_loop` (30 Hz)
        # pour rien. On copie PROFILE sous verrou, on sérialise/écrit hors
        # verrou. Copie PROFONDE : PROFILE contient des dicts imbriqués
        # (buttons, faders…) qu'une autre requête peut muter pendant la
        # sérialisation JSON hors verrou.
        with etat.E.LOCK:
            profil = json.loads(json.dumps(etat.E.PROFILE))
        self._json(profil)

    def _get_attributes(self):
        # Hors LOCK : lecture d'un fichier, sans rapport avec l'état du
        # moteur (et le résultat est mis en cache après la 1re lecture).
        import wing_ui as core
        self._json(core.ma3_attributes())

    def _get_fader_functions(self):
        import wing_ui as core
        self._json(core.ma3_fader_functions())

    def _get_assistant(self):
        import wing_ui as core
        self._json(core.assistant_liste())

    def _get_shcuts(self):
        import wing_ui as core
        self._json(core.shcuts_etat())

    def _get_keywords(self):
        import wing_ui as core
        d = core.ma3_motscles()
        self._json({"source": d["source"], "chemin": d["chemin"],
                    "mots": d["mots"], "total": len(d["mots"])})

    def _get_osc_in(self):
        import wing_ui as core
        with core.OSC_IN["lock"]:
            lignes = [{"addr": a, "n": e["n"], "last": e["last"],
                       "types": e["types"], "from": e.get("from", ""),
                       "fn": ", ".join(e.get("fn", [])),
                       "min": e.get("min"), "max": e.get("max"),
                       "age": round(time.time() - e["t"], 1)}
                      for a, e in core.OSC_IN["seen"].items()]
            total, port, err = core.OSC_IN["count"], core.OSC_IN["port"], core.OSC_IN["error"]
        lignes.sort(key=lambda x: -x["n"])
        self._json({"port": port, "error": err, "count": total,
                    "addresses": lignes[:120],
                    "history": list(core.OSC_IN_HIST)[-120:],
                    "truncated": len(lignes) > 120})

    def _get_usb_scan(self):
        self._json(wing_detect.scan())

    def _get_keystrokes(self):
        # Poll de l'assistant clavier (GET) : marque sa présence + son état
        # d'autorisation (?trusted=1/0), renvoie la file et une action éventuelle.
        import wing_ui as core
        etat.E.WS["helper_seen"] = time.time()
        q = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(q)
        etat.E.WS["helper_trusted"] = params.get("trusted", ["0"])[0] == "1"
        try:
            etat.E.WS["helper_build"] = int(params.get("build", ["0"])[0])
        except ValueError:
            etat.E.WS["helper_build"] = 0
        action = etat.E.WS["pending_action"]
        self._json({
            "keys":   core.drain_keys(),
            "action": action,
            # L'assistant reste actif en permanence : le mode console
            # n'est plus une option, c'est le comportement.
            "console": True,
        })

    def _get_dmx(self):
        import wing_ui as core
        # Les 512 valeurs de CHAQUE univers (XLR A et XLR B) — la grille
        # complète « Voir les 512 canaux » les affiche telles quelles. Le
        # compte de canaux non nuls résume l'activité en une ligne, sans
        # forcer l'ouverture de la grille.
        buf_a = list(etat.E.DMX["buf"][0])
        buf_b = list(etat.E.DMX["buf"][1])
        self._json({
            "enabled":   etat.E.DMX["enabled"],
            "universe":  etat.E.DMX["uni"][0],
            "universe2": etat.E.DMX["uni"][1],
            "source":    etat.E.DMX["source"],
            "pps":       etat.E.DMX["pps"],
            "channels":  buf_a,
            "channels2": buf_b,
            "actifs":    sum(1 for v in buf_a if v),
            "actifs2":   sum(1 for v in buf_b if v),
            "local":     bool(etat.E.SETTINGS.get("dmx_local", False)),
            "refuses":   etat.E.DMX.get("refuses", 0),
        })

    def _get_profiles(self):
        import wing_ui as core
        out = []
        for p in wm.list_profiles():
            if p.name in (core.REFERENCE_FILE.name, core.AUTOSAVE_FILE.name):
                continue     # fichiers système : jamais listés ni écrasés
            try:
                name = json.load(open(p, encoding="utf-8")).get("name", p.stem)
            except Exception:
                name = p.stem
            out.append({"file": p.name, "name": name,
                        "favori": p.name == etat.E.SETTINGS.get("profil_favori"),
                        # 🛟 Le profil de secours livré ne se supprime pas :
                        #    c'est le point de retour quand tout est cassé.
                        "protege": core._profil_de_secours(p.name)})
        self._json(out)

    def do_POST(self):
        if not self._origine_sure():
            return self._refuser_origine()
        if not self._jeton_valide():
            return self._refuser_jeton()
        try:
            body = self._read_body()
        except Handler.RequeteInvalide as e:
            return self._json({"error": _L("err.http.requete_invalide"),
                               "detail": str(e)}, 400)
        route = self._router(self.ROUTES_POST)
        if route is None:
            return self._json({"error": "not found"}, 404)
        self._executer(route, body)

    def _post_lang(self, body):
        # Langue de l'app (i18n serveur). Le client l'appelle depuis
        # appliquerLangue() (ui/i18n.js) en plus de sa traduction du DOM :
        # les surfaces « langue courante » côté serveur — journal affiché,
        # `raison` des erreurs, étapes de l'assistant firmware — suivent.
        # Le fichier wing_server.log et le diagnostic restent anglais.
        import wing_i18n
        lang = wv.texte(body, "lang", 16, "").lower()
        if not wing_i18n.poser_langue(lang):     # liste blanche dans wing_i18n
            self._json({"ok": False, "raison": f"langue inconnue : {lang}"})
            return
        self._json({"ok": True, "lang": lang})

    def _post_mode(self, body):
        import wing_ui as core
        mode = body.get("mode", "idle")
        if mode not in ("idle", "learn", "bridge"):
            self._json({"ok": False, "raison": f"mode inconnu : {mode}"})
            return

        # Démarrer sans wing : on ne REFUSE pas (armer le bridge avant de brancher est
        # légitime), mais on ne prétend pas non plus que c'est démarré — l'intention
        # est mémorisée dans `resume_mode` (le même mécanisme que la reprise après un
        # arrachage), et on le DIT.
        #
        # 🔒 Décision ET écriture de STATE dans UN SEUL bloc `with etat.E.LOCK:` : deux
        # blocs séparés laissaient `STATE["wing"]` changer entre le test et l'écriture.
        # Journal et relance de l'assistant restent hors verrou.
        with etat.E.LOCK:
            refuse = mode in ("bridge", "learn") and not etat.E.STATE["wing"]
            if refuse:
                etat.E.STATE["mode"] = "idle"
                etat.E.STATE["resume_mode"] = mode if mode == "bridge" else None
            else:
                etat.E.STATE["mode"] = mode
                etat.E.STATE["last_event"] = None
                if mode == "bridge":
                    etat.E.STATE["cmd_buf"] = ""
                elif mode == "idle":
                    etat.E.STATE["resume_mode"] = None   # arrêt volontaire : on désarme
        if refuse:
            core.log("journal.mode.pas_demarre_bridge" if mode == "bridge"
                     else "journal.mode.pas_demarre_learn")
            self._json({"ok": False, "raison": _L("err.wing_non_connectee"),
                        "arme": mode == "bridge"})
            return

        if mode == "bridge":
            # 🔑 Démarrer le bridge démarre TOUT : un assistant clavier mort entre-temps
            # (crash, autorisation révoquée, quitté) est relancé ici plutôt que d'attendre
            # que l'utilisateur s'en aperçoive.
            if not core.console_helper_alive():
                core.log("journal.mode.kbd_relancement")
                core.restart_keyboard_helper()
            core.log("journal.mode.bridge_demarre")
        elif mode == "learn":
            core.log("journal.mode.apprentissage")
        else:
            core.log("journal.mode.arrete")
        self._json({"ok": True})

    def _post_learn_clear(self, body):
        import wing_ui as core
        core.etat_poser(last_event=None)
        self._json({"ok": True})

    def _post_assign(self, body):
        # Lire, valider, déléguer : la commande MA3 est construite par
        # wing_boutons.affectation (voir son en-tête).
        import wing_ui as core
        a = wing_boutons.affectation(body)
        with etat.E.LOCK:
            if a.action == "poser":
                etat.E.PROFILE["buttons"][a.cle] = a.commande
                if a.executor_ref:
                    etat.E.PROFILE["executor_ref"][a.cle] = a.executor_ref
                else:
                    etat.E.PROFILE["executor_ref"].pop(a.cle, None)
            elif a.action == "effacer":
                etat.E.PROFILE["buttons"].pop(a.cle, None)
                etat.E.PROFILE["executor_ref"].pop(a.cle, None)
        if a.journal:
            core.log(a.journal, **a.params)
        core.etat_poser(last_event=None, dirty=True)
        self._json({"ok": True})

    def _post_fader(self, body):
        # Lire, valider, déléguer : la configuration et son libellé MA3 sont
        # construits par wing_faders.config_fader (voir son en-tête).
        import wing_ui as core
        i = wv.entier(body, "index", 0, len(wb.FADER_EXEC) - 1)
        cfg, libelle, suivre = wing_faders.config_fader(body)
        with etat.E.LOCK:
            etat.E.PROFILE["faders"][i] = cfg
        core.log("journal.fader.assigne" if suivre else "journal.fader.assigne_force",
                 n=i + 1, cmd=libelle)
        core.mark_dirty()
        self._json({"ok": True})

    def _post_encoders(self, body):
        import wing_ui as core
        # ⚠️ Casse corrigée AVANT enregistrement — même piège que les
        # commandes (`_post_assign`) : un nom d'attribut mal capitalisé
        # ("dimmer" au lieu de "Dimmer") échoue en SILENCE sur la ligne de
        # commande de MA3 (`Attribute dimmer at + 1`), la roue paraît
        # simplement morte. Répertoire DISJOINT de `corriger_casse()` — voir
        # `corriger_casse_attribut()`. Calculé HORS verrou (même règle que
        # partout : la correction peut lire un fichier MA3 la 1re fois).
        groups = wv.groupes_encodeurs(body, "groups")
        if groups is not None:
            groups = [[(core.corriger_casse_attribut(a) if a else None) for a in g]
                      for g in groups]
        with etat.E.LOCK:
            nb_groupes = len(groups if groups is not None
                             else etat.E.PROFILE["enc_groups"])
        defaut = wv.entier(body, "default", 0, nb_groupes - 1, None)
        # Pas des roues : même borne que la validation des profils (C2), sinon
        # l'interface pourrait poser ce qu'un rechargement refuserait.
        pas = wv.reel(body, "step", 1e-6, wm.ENC_STEP_MAX, None)
        with etat.E.LOCK:
            if groups is not None:
                etat.E.PROFILE["enc_groups"] = groups
            if defaut is not None:
                etat.E.PROFILE["enc_default_group"] = defaut
            if pas is not None:
                etat.E.PROFILE["enc_step"] = pas
        # ⚠️ RÉ-APPLIQUER LE GROUPE COURANT, pas celui par défaut. Sinon
        #    enregistrer une modification fait SAUTER les roues sur un autre
        #    groupe, et le réglage qu'on vient d'écrire paraît ignoré.
        #    → docs/FADERS_ENCODERS.md#editer-un-groupe-doit-s-appliquer-tout-de-suite
        gi = core.appliquer_groupe_enc(etat.E.STATE.get("enc_group", 0))
        core.log("journal.enc.maj", n=gi + 1,
                 attrs=" | ".join(f"R{i+1}={a or '—'}"
                                  for i, a in enumerate(etat.E.STATE["enc_attr"])))
        core.mark_dirty()
        self._json({"ok": True})

    def _post_profile_save(self, body):
        # Sans 'name' → sauvegarde sur le profil ACTIF (bouton en-tête)
        import wing_ui as core
        name = wv.texte(body, "name", 80, "")
        # 🔒 LE VERROU NE PROTÈGE QUE L'INSTANTANÉ — `wm.save_profile()` écrit
        # sur DISQUE (jamais gratuit : peut tomber sur un disque lent, un
        # dossier réseau, une clé USB) et n'a rien à faire sous le MÊME verrou
        # qu'`usb_loop` à 30 Hz. On pose le nom et on COPIE PROFONDE le profil
        # sous verrou, on sauvegarde hors verrou sur cette copie figée.
        with etat.E.LOCK:
            if name:
                etat.E.PROFILE["name"] = name
            profil = json.loads(json.dumps(etat.E.PROFILE))
            etat.E.STATE["dirty"] = False
        path = wm.save_profile(profil)
        core.log("journal.profil.enregistre", nom=profil["name"])
        self._json({"ok": True, "file": path.name})

    def _post_profile_load(self, body):
        import wing_ui as core
        fname = body.get("file", "")
        # 🔒 Confinement au dossier des profils (audit du 25/09/2026), comme
        # `_post_profile_delete` l'avait déjà : `PROFILE_DIR / "/chemin/absolu"`
        # vaut le chemin absolu, et `../..` remontait n'importe où — n'importe
        # quel JSON du disque se chargeait comme profil. Contrôle
        # test_profil_load_confine.
        path = wing_profils.chemin_profil(fname)
        if path is None:
            self._json({"error": _L("err.chemin_invalide")}, 400)
            return
        if path.exists():
            p = wm.load_profile(path)
            with etat.E.LOCK:
                etat.E.PROFILE = p
                etat.E.STATE["dirty"] = False
            core.reset_enc_attr()
            core.log("journal.profil.charge", nom=p["name"])
            self._json({"ok": True})
        else:
            self._json({"error": "introuvable"}, 404)

    def _post_profile_parcourir(self, body):
        # Sélecteur de fichier NATIF, ouvert DANS le dossier des profils (caché dans le
        # Finder) : un `<input type="file">` ne peut pas choisir son dossier de départ.
        # L'utilisateur reste libre de naviguer ailleurs (AirDrop, clé USB…).
        import wing_ui as core
        dossier = str(wm.PROFILE_DIR)
        # ⚠️ PAS DE FILTRE de type : macOS attend des UTI, et un filtre sur l'extension
        # GRISAIT tous les fichiers. Le contenu est validé ensuite par
        # `importer_profil`. Sélecteur commun macOS/Windows : wing_dialogues.
        chemin = wing_dialogues.choisir_fichier(
            "Choisir un profil Wing Bridge (.json)", dossier=dossier)
        if chemin is None:
            self._json({"ok": False, "raison": _L("err.selecteur_indisponible")})
            return
        if not chemin:
            # Annulation : ce n'est PAS une erreur, on ne crie pas.
            self._json({"ok": False, "annule": True})
            return
        try:
            contenu = json.load(open(chemin, encoding="utf-8"))
        except Exception as e:
            self._json({"ok": False,
                        "raison": f"fichier illisible comme JSON : {e}"})
            return
        self._json(core.importer_profil(Path(chemin).name, contenu))

    def _post_profile_import(self, body):
        # {"nom": "...", "contenu": {...}} — import par le navigateur
        # (glisser un fichier). Le sélecteur natif passe par
        # /api/profile/parcourir ; les deux finissent dans importer_profil().
        import wing_ui as core
        self._json(core.importer_profil(str(body.get("nom", "") or ""),
                                   body.get("contenu")))

    def _post_profile_favori(self, body):
        # {"file": "mini-wing.json"} — "" ou absent retire le favori.
        #
        # ⭐ Le favori est un réglage MACHINE : il DÉSIGNE un profil, il ne
        # peut donc pas vivre dans le profil lui-même (sinon chaque copie
        # se déclarerait favorite à son tour).
        import wing_ui as core
        f = wv.texte(body, "file", 200, "")
        if f and f in (core.REFERENCE_FILE.name, core.AUTOSAVE_FILE.name):
            self._json({"ok": False, "raison": _L("err.fichier_systeme")})
            return
        if f and not (wm.PROFILE_DIR / f).exists():
            self._json({"ok": False, "raison": _L("err.profil_introuvable")})
            return
        core.reglage_poser(profil_favori=f)
        core.save_settings()
        core.log("journal.profil.favori_pose" if f
                 else "journal.profil.favori_retire", nom=f)
        self._json({"ok": True, "favori": f})

    def _post_profile_delete(self, body):
        import wing_ui as core
        fname = body.get("file", "")
        path = (wm.PROFILE_DIR / fname).resolve()
        # Garde-fous : jamais la config sûre, jamais hors du dossier profils
        # (fname vient de notre propre UI, mais on vérifie quand même).
        # ⚠️ SEED_PROFILE compris : l'interface ne montre pas de 🗑 pour lui,
        #    mais une interface ne protège RIEN — la garde est ici.
        if fname in (core.REFERENCE_FILE.name, core.AUTOSAVE_FILE.name) \
                or core._profil_de_secours(fname):
            self._json({"error": _L("err.profil_protege")}, 403)
        elif wm.PROFILE_DIR.resolve() not in path.parents:
            self._json({"error": _L("err.chemin_invalide")}, 400)
        elif not path.exists():
            self._json({"error": _L("err.introuvable")}, 404)
        else:
            name = fname
            try:
                name = json.load(open(path, encoding="utf-8")).get("name", fname)
            except Exception:
                pass
            path.unlink()
            core.log("journal.profil.supprime", nom=name)
            self._json({"ok": True})

    def _post_profile_reveal(self, body):
        # Ouvre le dossier des profils dans le Finder — pour les
        # échanger facilement (AirDrop, clé USB, autre Mac…) sans avoir
        # à naviguer dans ~/Library (caché par défaut dans le Finder).
        import wing_ui as core
        try:
            wm.PROFILE_DIR.mkdir(exist_ok=True)
            if getattr(sys, "frozen", False):
                user = core.open_in_user_session(wm.PROFILE_DIR)
                core.log("journal.profil.dossier_ouvert_user", user=user)
            else:
                subprocess.run(["open", str(wm.PROFILE_DIR)])
                core.log("journal.profil.dossier_ouvert")
            self._json({"ok": True, "path": str(wm.PROFILE_DIR)})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _post_profile_recover(self, body):
        # Reprend les modifications retrouvées après une sortie non propre.
        # Elles arrivent en état « modifié » : à l'utilisateur de décider
        # ensuite s'il les enregistre dans un profil nommé.
        # (etat.E.PROFILE : reste dans wing_ui.py, réassigné ici comme ailleurs.)
        import wing_ui as core
        try:
            d = json.load(open(core.AUTOSAVE_FILE, encoding="utf-8"))
            p = wm.migrate_profile(d["profile"])
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 400)
            return
        with etat.E.LOCK:
            etat.E.PROFILE = p
            etat.E.STATE["dirty"] = True
        core.reset_enc_attr()
        etat.E.RECOVERY["available"] = None
        core.log("journal.profil.recuperees", nom=p.get('name', '?'))
        self._json({"ok": True})

    def _post_profile_discard_recovery(self, body):
        import wing_ui as core
        core.AUTOSAVE_FILE.unlink(missing_ok=True)
        etat.E.RECOVERY["available"] = None
        core.log("journal.profil.recuperation_ignoree")
        self._json({"ok": True})

    def _post_profile_new(self, body):
        import wing_ui as core
        with etat.E.LOCK:
            etat.E.PROFILE = wm.new_profile_from_defaults()
            etat.E.PROFILE["name"] = "Profil d'origine"
            etat.E.STATE["dirty"] = False
        core.reset_enc_attr()
        core.log("journal.profil.origine_charge")
        self._json({"ok": True})

    def _post_reference_restore(self, body):
        # Filet de sécurité : recharge la config sûre en profil actif
        import wing_ui as core
        core.ensure_reference()
        try:
            p = wm.load_profile(core.REFERENCE_FILE)
        except Exception as e:
            self._json({"error": _L("err.config_sure_illisible", err=e)}, 500); return
        p.pop("locked", None)
        p.pop("saved_at", None)
        with etat.E.LOCK:
            etat.E.PROFILE = p
            etat.E.STATE["dirty"] = False
        core.reset_enc_attr()
        core.log("journal.profil.config_sure_restauree")
        self._json({"ok": True})

    def _post_reference_set(self, body):
        # Fige la config ACTUELLE comme nouveau connu-qui-marche
        import wing_ui as core
        # 🔒 LE VERROU NE PROTÈGE QUE LA COPIE — `save_reference()` écrit sur
        # DISQUE (`REFERENCE_FILE`), ça n'a rien à faire sous le MÊME verrou
        # qu'`usb_loop` à 30 Hz (même règle que `_post_profile_save`).
        with etat.E.LOCK:
            profil = json.loads(json.dumps(etat.E.PROFILE))
        core.save_reference(profil)
        info = core.reference_info()
        core.log("journal.profil.config_sure_maj", quand=info["when"])
        self._json({"ok": True, "when": info["when"]})

    def _post_led(self, body):
        # {"offset": N, "value": V} | {"btn": "0x78", "value": V}
        # {"solo": N, "value": V}   → tout éteint sauf le slot N
        # {"restore": true}         → retour à l'éclairage de repos
        #
        # ⏹ `{"all": V}` (tous les slots à V) RETIRÉ : seul chemin qui allumait
        #    les 119 LED à fond d'un coup, et la wing a décroché du bus 3 fois
        #    pendant son essai. NE PAS remettre sans une bonne raison ET une
        #    limitation de débit.
        import wing_ui as core
        value = wv.entier(body, "value", 0, 2047, 2040)
        if wv.booleen(body, "restore", False):
            etat.E.LED["buf"][:] = core.LED_BASE
        elif "solo" in body:
            etat.E.LED["buf"][:] = bytes(260)
            core.set_led_offset(wv.entier(body, "solo", 0, 258), value)
        elif "btn" in body:
            core.set_btn_led(wv.hexa(body, "btn", 0, 255), value)
        elif "offset" in body:
            core.set_led_offset(wv.entier(body, "offset", 0, 258), value)
        if "feedback" in body:
            etat.E.LED["feedback"] = wv.booleen(body, "feedback")
        if "ma3" in body:
            etat.E.LED["ma3"] = wv.booleen(body, "ma3")
            if not etat.E.LED["ma3"]:
                for k in list(etat.E.PROFILE.get("executor_ref", {})):
                    try: core.set_btn_led(int(k, 16), core.LED_GLOW)
                    except Exception: pass
            core.log("journal.led.ma3_suivi" if etat.E.LED["ma3"]
                     else "journal.led.ma3_ignore")
        self._json({"ok": True})

    def _post_led_vegas(self, body):
        import wing_ui as core
        etat.E.VEGAS["on"] = wv.booleen(body, "on", False)
        if not etat.E.VEGAS["on"]:
            etat.E.LED["buf"][:] = core.LED_BASE
        core.log("journal.led.chenillard_on" if etat.E.VEGAS['on']
                 else "journal.led.chenillard_off")
        self._json({"ok": True})

            # ⏹ Retirés, ne pas réintroduire : `/api/console` (le mode
            #    console n'est plus une option, démarrer le bridge démarre tout) et
            #    `/api/led/map` (la carte des LEDs est mesurée, plus configurée).
    def _post_console_key(self, body):
        # {"token": "Store", "key": "s"}  — édite la table du profil
        import wing_ui as core
        token = body.get("token", "")
        cle = body.get("key", "")
        # 🔒 Liste blanche (audit du 25/09/2026) : cette frappe finira dans le
        # XML de MA3 et dans une commande OSC — voir wm.raccourci_valide.
        if not isinstance(token, str) or not wm.raccourci_valide(cle):
            core.log("journal.console.raccourci_refuse", token=str(token)[:40],
                     key=str(cle)[:40])
            self._json({"ok": False, "raison": _L("err.raccourci_invalide")})
            return
        cle = cle.strip()
        with etat.E.LOCK:
            etat.E.PROFILE.setdefault("console_keys", {})
            if token:
                etat.E.PROFILE["console_keys"][token] = cle
        core.log("journal.console.raccourci", token=token, key=cle)
        core.mark_dirty()
        self._json({"ok": True})

            # ⏹ `/api/console/hold` retiré : l'appui long est relayé
            #    pour TOUTES les touches, MA3 décide seul. Plus rien à cocher.
    def _post_console_reset(self, body):
        # Réinitialise la table console aux raccourcis MA3 par défaut
        import wing_ui as core
        with etat.E.LOCK:
            etat.E.PROFILE["console_keys"] = dict(wm.CONSOLE_KEY_DEFAULTS)
        core.log("journal.console.reset")
        core.mark_dirty()
        self._json({"ok": True})

    def _post_double_clic(self, body):
        # {"token": "Menu", "commande": "SaveShow"} — édite la table du profil.
        # Indexé par TOKEN, pas par code bouton : voir
        # wing_mapper.py::new_profile_from_defaults. Une commande vide
        # désactive le double-appui pour ce token (même motif que
        # console_keys : chaîne vide = falsy, `handle_button_bridge` ne
        # déclenche rien).
        import wing_ui as core
        token = wv.texte(body, "token", 40, "")
        commande = wv.texte(body, "commande", 400, "")
        # ⚠️ Casse corrigée AVANT enregistrement — même règle que
        # `_post_assign` : un mot-clé MA3 mal capitalisé (« saveshow » au lieu
        # de « SaveShow ») échoue en SILENCE sur la ligne de commande de MA3,
        # sans rien remonter en OSC. La commande de double-appui part
        # justement en OSC direct (jamais par une frappe relayée) : elle est
        # exactement aussi exposée à ce piège qu'une assignation normale.
        corrections = []
        if commande:
            commande, corrections = core.corriger_casse(commande)
        with etat.E.LOCK:
            etat.E.PROFILE.setdefault("double_clic", {})
            if token:
                etat.E.PROFILE["double_clic"][token] = commande
        core.log("journal.console.double_appui_casse" if corrections
                 else "journal.console.double_appui", token=token, cmd=commande,
                 casse=', '.join(corrections))
        core.mark_dirty()
        self._json({"ok": True})

    def _post_fader_nom(self, body):
        # Étiquette libre d'un fader physique (sérigraphie de la wing).
        # ⚠️ Index BORNÉ aux faders de la wing : avant l'audit du 25/09/2026,
        # un index de 10 000 ajoutait 10 000 étiquettes vides au profil, et un
        # index négatif renommait un fader compté depuis la fin.
        import wing_ui as core
        i = wv.entier(body, "index", 0, len(wb.FADER_EXEC) - 1, 0)
        nom = wv.texte(body, "nom", 200, "")[:16]
        with etat.E.LOCK:
            noms = etat.E.PROFILE.setdefault("fader_noms", [])
            while len(noms) <= i:
                noms.append("")
            noms[i] = nom
            etat.E.STATE["dirty"] = True
        self._json({"ok": True})

    def _post_fader_rangee(self, body):
        # Remplit une suite de faders avec une rangée d'executors.
        # Sur MA3 toutes les pages ont la même disposition (101-110,
        # 201-210…), et un numéro d'executor est relatif à la page
        # courante : renseigner la rangée suffit, le suivi de page est
        # automatique.
        import wing_ui as core
        depuis = wv.entier(body, "depuis", 1, len(wb.FADER_EXEC), 1)   # n° de fader
        base   = wv.entier(body, "base", 1, 99999, 201)                # 1er executor
        with etat.E.LOCK:
            faders = etat.E.PROFILE.setdefault("faders", [])
            n = 0
            for i in range(depuis - 1, len(faders)):
                faders[i] = {"kind": "executor", "exec": base + n}
                n += 1
            etat.E.STATE["dirty"] = True
        core.log("journal.rangee.faders", depuis=depuis, base=base, n=n)
        self._json({"ok": True, "n": n})

    def _post_bouton_rangee(self, body):
        # Renumérote une RANGÉE de boutons executor — la règle est dans
        # wing_boutons.renumeroter_rangee.
        import wing_ui as core
        rangee = wv.entier(body, "rangee", 0, 99900, 100)
        base   = wv.entier(body, "base", 1, 99999, 101)
        with etat.E.LOCK:
            n = wing_boutons.renumeroter_rangee(
                etat.E.PROFILE.setdefault("executor_ref", {}),
                etat.E.PROFILE.setdefault("buttons", {}), rangee, base)
            etat.E.STATE["dirty"] = True
        core.log("journal.rangee.boutons", rangee=rangee, n=n, base=base)
        self._json({"ok": True, "n": n})

    def _post_fader_pickup(self, body):
        import wing_ui as core
        core.reglage_poser(fader_pickup=wv.booleen(body, "actif", True))
        core.save_settings()
        etat.E.PICKUP.clear()
        core.log("journal.reglage.pickup_on" if etat.E.SETTINGS["fader_pickup"]
                 else "journal.reglage.pickup_off")
        self._json({"ok": True, "actif": etat.E.SETTINGS["fader_pickup"]})

    def _post_shcuts_envoyer(self, body):
        import wing_ui as core
        self._json(core.shcuts_envoyer(force=wv.booleen(body, "force", False)))

    def _post_plugin_install(self, body):
        # Installe la sonde Lua dans grandMA3 : copie des 4 fichiers de prod +
        # séquence d'import OSC + vérif que la sonde répond. Toute la logique
        # (et tous les chemins d'échec actionnables) sont dans wing_ma3 —
        # ~3,5 s bloquantes, acceptable pour un bouton délibéré.
        self._json(wing_ma3.installer_plugin())

    def _post_plugin_relaunch(self, body):
        # Sonde déjà installée (fichiers sur le disque) mais arrêtée : un simple
        # « Plugin 3 » en OSC suffit à la relancer — pas de re-copie, pas de
        # ré-import, pas de SaveShow. ~2 s bloquantes.
        self._json(wing_ma3.relancer_plugin())

    # ⏹ `/api/encodeurs_ma3` retiré — voir le commentaire de `SETTINGS`
    #    (wing_reglages.py).

    def _post_plugin_slot(self, body):
        """Emplacement (slot) du pool Plugins de MA3 pour l'install automatique.

        Hors bornes (1..9999, garde-fou de saisie — pas un plafond documenté
        par MA3, voir wing_ma3.PLUGIN_SLOT_MAX) : repli sur le défaut (3) et
        message actionnable, pas un rejet muet de la requête.
        """
        import wing_ui as core
        mini, maxi, defaut = (wing_ma3.PLUGIN_SLOT_MIN, wing_ma3.PLUGIN_SLOT_MAX,
                              wing_ma3.PLUGIN_SLOT_DEFAUT)
        try:
            slot = wv.entier(body, "slot", mini, maxi, defaut)
        except wv.EntreeInvalide:
            core.reglage_poser(plugin_slot=defaut)
            core.save_settings()
            core.log("journal.reglage.plugin_slot_invalide",
                     slot=body.get("slot"), defaut=defaut)
            self._json({"ok": True, "slot": defaut,
                        "avertissement": _L("err.reglages.plugin_slot_hors_bornes",
                                            mini=mini, maxi=maxi, defaut=defaut)})
            return
        core.reglage_poser(plugin_slot=slot)
        core.save_settings()
        core.log("journal.reglage.plugin_slot", slot=slot)
        self._json({"ok": True, "slot": slot})

    def _post_verbe_cible(self, body):
        import wing_ui as core
        core.reglage_poser(verbe_cible=wv.booleen(body, "actif", True))
        core.save_settings()
        etat.E.VERBE["token"] = None              # on repart d'une ligne propre
        etat.E.CONSOLE_CIBLES["cmd"] = ""
        core.log("journal.reglage.verbe_on" if etat.E.SETTINGS["verbe_cible"]
                 else "journal.reglage.verbe_off")
        self._json({"ok": True, "actif": etat.E.SETTINGS["verbe_cible"]})

    def _post_suivre_ma3(self, body):
        import wing_ui as core
        core.reglage_poser(suivre_ma3=wv.booleen(body, "actif", True))
        core.save_settings()
        etat.E.SUIVI_VU.clear()      # les constats repartent de zéro
        core.log("journal.reglage.suivi_on" if etat.E.SETTINGS["suivre_ma3"]
                 else "journal.reglage.suivi_off")
        self._json({"ok": True, "actif": etat.E.SETTINGS["suivre_ma3"]})

    def _post_encodeurs_ma3(self, body):
        """Les roues suivent-elles l'Encoder Bar de MA3 ?

        🔑 Défaut FALSE (contrairement à `suivre_ma3`) : pilotage réel jamais
        éprouvé sur console, ne doit rien changer sans un geste explicite.
        """
        import wing_ui as core
        core.reglage_poser(encodeurs_ma3=wv.booleen(body, "actif", False))
        core.save_settings()
        etat.E.SUIVI_VU.clear()      # les constats repartent de zéro
        core.log("journal.reglage.enc_bar_on" if etat.E.SETTINGS["encodeurs_ma3"]
                 else "journal.reglage.enc_bar_off")
        self._json({"ok": True, "actif": etat.E.SETTINGS["encodeurs_ma3"]})

    def _post_osc_target(self, body):
        # {"ip": "192.168.1.50", "port": 8000} — cible OSC de MA3. Réglage MACHINE,
        # appliqué à chaud : aucun rebuild, aucun redémarrage.
        import wing_ui as core
        try:
            ip, port = core.valid_osc_target(body.get("ip"), body.get("port"))
        except ValueError as e:
            self._json({"ok": False, "error": str(e)}, 400)
            return
        core.apply_osc_target(ip, port)
        core.save_settings()
        core.log("journal.reglage.osc_cible", ip=ip, port=port)
        self._json({"ok": True, "ip": ip, "port": port})

    def _post_diagnostic(self, body):
        import wing_ui as core
        try:
            dest = core.build_diagnostic()
        except Exception as e:
            self._json({"ok": False, "error": str(e)}, 500)
            return
        # Révèle le fichier dans le Finder, sélectionné : l'utilisateur n'a
        # plus qu'à le glisser dans un mail.
        try:
            core.run_in_user_session(["open", "-R", str(dest)], timeout=5)
        except Exception:
            pass
        self._json({"ok": True, "path": str(dest), "name": dest.name})

    def _post_osc_listen(self, body):
        # {"port": 8001} — 0 pour arrêter. Phase d'OBSERVATION : on
        # journalise ce que MA3 envoie, on n'agit sur rien.
        import wing_ui as core
        try:
            p = wv.entier(body, "port", 0, 65535, 0)
        except wv.EntreeInvalide:
            self._json({"ok": False, "error": _L("err.port_invalide")}, 400)
            return
        if p and p == wb.MA3_PORT and wb.MA3_IP in ("127.0.0.1", "localhost", "::1"):
            self._json({"ok": False, "error":
                        f"le port {p} est celui sur lequel MA3 écoute déjà "
                        f"sur cette machine — choisis-en un autre"}, 400)
            return
        with core.OSC_IN["lock"]:
            core.OSC_IN["seen"].clear()
            core.OSC_IN["count"] = 0
            core.OSC_IN_HIST.clear()
        ok_bind = core.osc_in_bind(p)
        core.reglage_poser(osc_in_port=core.OSC_IN["port"])
        core.save_settings()
        self._json({"ok": ok_bind, "port": core.OSC_IN["port"],
                    "error": core.OSC_IN["error"]})

    def _post_osc_listen_clear(self, body):
        import wing_ui as core
        with core.OSC_IN["lock"]:
            core.OSC_IN["seen"].clear()
            core.OSC_IN["count"] = 0
            core.OSC_IN_HIST.clear()
        self._json({"ok": True})

    def _post_console_open_settings(self, body):
        # Bouton 🔓. Trois étapes, dans cet ordre :
        #   1. effacer l'enregistrement TCC périmé (sinon l'utilisateur voit
        #      une entrée « Wing Keyboard » déjà cochée qui n'autorise rien)
        #   2. relancer l'assistant → instance fraîche, non autorisée, qui
        #      déclenche la VRAIE pop-up système au démarrage
        #   3. lui demander d'ouvrir le volet Accessibilité des Réglages
        import wing_ui as core
        core.log("journal.console.accessibilite")
        core.forget_keyboard_authorization()
        core.restart_keyboard_helper()
        etat.E.WS["pending_action"] = "open_settings"
        self._json({"ok": True})

    def _post_console_action_done(self, body):
        import wing_ui as core
        etat.E.WS["pending_action"] = None
        self._json({"ok": True})

    def _post_console_test(self, body):
        # {"key": "s"} — met une frappe de test dans la file
        import wing_ui as core
        spec = body.get("key", "")
        ok = core.enqueue_key(spec)
        if not core.console_helper_alive():
            core.log("journal.console.test_sans_kbd", spec=spec)
        else:
            core.log("journal.console.test", spec=spec)
        self._json({"ok": ok, "helper": core.console_helper_alive()})

    def _post_dmx_config(self, body):
        import wing_ui as core
        if "enabled" in body:
            etat.E.DMX["enabled"] = wv.booleen(body, "enabled")
            core.log("journal.dmx.sortie_on" if etat.E.DMX['enabled']
                     else "journal.dmx.sortie_off",
                     a=etat.E.DMX['uni'][0], b=etat.E.DMX['uni'][1])
            if not etat.E.DMX["enabled"]:
                etat.E.DMX["buf"][0][:] = bytes(512)   # blackout en coupant
                etat.E.DMX["buf"][1][:] = bytes(512)
        if "universe" in body:
            etat.E.DMX["uni"][0] = wv.entier(body, "universe", 1, 63999)
            core.log("journal.dmx.xlr_a", uni=etat.E.DMX['uni'][0])
        if "universe2" in body:
            etat.E.DMX["uni"][1] = wv.entier(body, "universe2", 1, 63999)
            core.log("journal.dmx.xlr_b", uni=etat.E.DMX['uni'][1])
        if "local" in body:
            # Réglage MACHINE, persistant (≠ enabled/univers, qui ne durent
            # que la session) : c'est une décision de sécurité, pas un essai.
            local = wv.booleen(body, "local")
            core.reglage_poser(dmx_local=local)
            core.save_settings()
            core.log("journal.dmx.local_on" if local else "journal.dmx.local_off")
        self._json({"ok": True})

    def _post_usb_probe(self, body):
        import wing_ui as core
        vid = wv.hexa(body, "vid", 0, 0xFFFF)
        pid = wv.hexa(body, "pid", 0, 0xFFFF)
        # ⚠️ Pas de conseil « débranche/rebranche » : `probe()` revendique
        # l'interface, ce qui échoue sur une wing que l'app tient DÉJÀ. Le seul
        # obstacle est alors l'app elle-même — on le dit, sans envoyer l'utilisateur
        # débrancher son matériel.
        if (vid, pid) == (wing_init.VID, wing_init.PID) and etat.E.STATE["wing"]:
            msg = _L("err.detect.wing_active")
            core.log("journal.usb.handshake_non_tente", msg=msg)
            self._json({"ok": False, "verdict": msg})
            return
        core.log("journal.usb.handshake_test", vid=body.get('vid'), pid=body.get('pid'))
        result = wing_detect.probe(vid, pid)
        core.log("journal.usb.handshake_verdict",
                 verdict=result.get('verdict', result.get('error', '?')))
        self._json(result)

            # Un SEUL geste pour la wing : le client dit « fais marcher la wing », c'est
            # ICI qu'on décide, à partir de l'état RÉEL au moment du clic (un navigateur en
            # retard de 400 ms ne peut plus demander la mauvaise action). Et la réponse dit
            # ce qui s'est passé — jamais un « ok » sans rien faire. `/api/wing/reconnect`
            # reste accepté pour un vieil onglet.
    def _post_wing_connect(self, body):
        import wing_ui as core
        if etat.E.STATE["connecting"]:
            core.log("journal.wing.clic_ignore")
            self._json({"ok": False, "raison": "connexion déjà en cours"})
            return
        # Wing déjà là → l'utilisateur veut forcément une RÉ-INITIALISATION
        # (c'est ce que dit le bouton, qui affiche alors « ↻ Reconnecter »).
        force = bool(etat.E.STATE["wing"])
        core.log("journal.wing.reinit_demandee" if force
                 else "journal.wing.connexion_demandee")
        threading.Thread(target=lambda: core.connect_wing(force=force),
                         daemon=True).start()
        self._json({"ok": True, "force": force})

    # ══ CONFIGURER LE FIRMWARE ═══════════════════════════════════════════════
    #
    # Le firmware appartient à MA Lighting : la distribution OSS ne le livre pas.
    # Chaque utilisateur importe SA copie — extraite de sa capture (.pcapng) ou
    # d'un .bin déjà en sa possession — qui atterrit dans le cache
    # (wing_firmware.chemin_cache_firmware). Une fois en cache, la wing devient
    # connectable, et l'utilisateur peut RÉ-EXPORTER le .bin (ex. capturé sur un
    # PC Windows, rapporté sur un Mac). Voir docs/HARDWARE.md, « Obtenir le
    # firmware ».
    def _relancer_wing_apres_config(self):
        """Après un import réussi : tenter la connexion tout de suite.

        Sans ça, l'utilisateur devrait attendre le prochain tour de la boucle
        d'auto-reconnexion (jusqu'à 10 s d'espacement). On rejoue simplement le
        chemin du bouton « Connecter », dans un thread pour ne pas bloquer la
        réponse HTTP.
        """
        import wing_ui as core
        if etat.E.STATE["connecting"] or etat.E.STATE["wing"]:
            return
        threading.Thread(target=lambda: core.connect_wing(force=True),
                         daemon=True).start()


    def _post_firmware_import_capture(self, body):
        import wing_ui as core
        try:
            import wing_firmware_extract as fwx
        except Exception as e:
            self._json({"ok": False,
                        "raison": _L("err.module_extraction_absent", err=e)})
            return
        chemin = wing_dialogues.choisir_fichier(
            "Choisir une capture Wireshark de l'upload firmware (.pcapng)",
            exts=["pcapng", "pcap"])
        if chemin is None:
            self._json({"ok": False,
                        "raison": _L("err.selecteur_indisponible")})
            return
        if not chemin:
            self._json({"ok": False, "annule": True})   # annulation, pas erreur
            return
        try:
            blob = fwx.extract_from_pcapng(chemin)
        except fwx.ExtractionError as e:
            core.log("journal.fw.import_capture_ko", err=e)
            self._json({"ok": False, "raison": str(e)})
            return
        except Exception as e:
            self._json({"ok": False,
                        "raison": _L("err.lecture_capture", err=e)})
            return
        res = wing_firmware.enregistrer_firmware(blob)
        if res.get("ok"):
            core.log("journal.fw.extrait_ok", o=res['longueur'])
            self._relancer_wing_apres_config()
        else:
            core.log("journal.fw.extrait_rejete", raison=res.get('raison', '?'))
        self._json(res)

    def _post_firmware_import_bin(self, body):
        import wing_ui as core
        chemin = wing_dialogues.choisir_fichier("Choisir un firmware de wing (.bin)",
                                  exts=["bin"])
        if chemin is None:
            self._json({"ok": False,
                        "raison": _L("err.selecteur_indisponible")})
            return
        if not chemin:
            self._json({"ok": False, "annule": True})
            return
        try:
            blob = open(chemin, "rb").read()
        except Exception as e:
            self._json({"ok": False, "raison": _L("err.fichier_illisible", err=e)})
            return
        res = wing_firmware.enregistrer_firmware(blob)   # verify() est DEDANS
        if res.get("ok"):
            core.log("journal.fw.importe_ok", o=res['longueur'])
            self._relancer_wing_apres_config()
        else:
            core.log("journal.fw.refuse", raison=res.get('raison', '?'))
        self._json(res)

    def _post_firmware_export(self, body):
        import wing_ui as core
        src = wing_firmware.resoudre_firmware()
        if src is None:
            self._json({"ok": False,
                        "raison": _L("err.aucun_firmware_cache")})
            return
        dest = wing_dialogues.choisir_fichier("Enregistrer le firmware de la wing",
                                enregistrer=True, nom_defaut="wing_firmware.bin",
                                exts=["bin"])
        if dest is None:
            self._json({"ok": False,
                        "raison": _L("err.selecteur_indisponible")})
            return
        if not dest:
            self._json({"ok": False, "annule": True})
            return
        try:
            with open(src, "rb") as f:
                data = f.read()
            with open(dest, "wb") as f:
                f.write(data)
        except Exception as e:
            self._json({"ok": False, "raison": _L("err.ecriture_impossible", err=e)})
            return
        core.log("journal.fw.exporte", o=len(data), dest=dest)
        self._json({"ok": True, "path": dest, "longueur": len(data)})

    # ── Capture intégrée (Windows uniquement) ──────────────────────────────
    # Voie AUTOMATIQUE, en plus des imports manuels ci-dessus (jamais retirés
    # — c'est le repli si la capture intégrée échoue, ou pour macOS/Linux, ou
    # pour rapporter un firmware capturé sur une autre machine). Le gros du
    # travail (élévation, installation/désinstallation éphémère de USBPcap,
    # capture, extraction) vit dans wing_firmware_capture.py — cette route ne
    # fait que LANCER (thread à part : l'opération dure jusqu'à ~2 min,
    # installation comprise, hors de question de bloquer la réponse HTTP) et
    # laisser /api/status → « capture » (CAPTURE_STATE) informer l'UI en
    # direct (poll 400 ms, voir ui/init.js). Voir docs/WINDOWS.md,
    # « Capture firmware intégrée ».
    def _post_firmware_capture(self, body):
        import wing_ui as core
        if not sys.platform.startswith("win"):
            self._json({"ok": False, "raison": _L("err.capture_windows_only")})
            return
        try:
            import wing_firmware_capture as fwc
        except Exception as e:
            self._json({"ok": False, "raison": _L("err.module_capture_absent", err=e)})
            return
        if fwc.CAPTURE_STATE["actif"]:
            self._json({"ok": False, "raison": _L("err.capture_en_cours")})
            return
        core.log("journal.fw.capture_demandee")

        def _run():
            res = fwc.capturer_firmware()
            if res.get("ok"):
                core.log("journal.fw.capture_ok", o=res['longueur'],
                         residu=res.get('residu', ''))
                self._relancer_wing_apres_config()
            else:
                core.log("journal.fw.capture_ko", raison=res.get('raison', '?'))

        threading.Thread(target=_run, daemon=True).start()
        self._json({"ok": True, "started": True})

    def _post_firmware_capture_cancel(self, body):
        """Bouton « Annuler la démarche » de l'assistant de capture.

        Ne tue rien de force : pose le drapeau que la boucle de capture
        surveille. Si l'utilitaire élevé (USBPcap) tourne, la boucle lui donne
        le feu vert de désinstallation avant de rendre la main.
        """
        import wing_ui as core
        if not sys.platform.startswith("win"):
            self._json({"ok": False, "raison": _L("err.hors_windows")})
            return
        try:
            import wing_firmware_capture as fwc
        except Exception as e:
            self._json({"ok": False, "raison": _L("err.module_capture_absent", err=e)})
            return
        res = fwc.annuler_capture()
        if res.get("annulation"):
            core.log("journal.fw.capture_annulee")
        self._json(res)

    def _post_firmware_remove_capture_component(self, body):
        import wing_ui as core
        if not sys.platform.startswith("win"):
            self._json({"ok": False, "raison": _L("err.hors_windows")})
            return
        try:
            import wing_firmware_capture as fwc
        except Exception as e:
            self._json({"ok": False, "raison": _L("err.module_capture_absent", err=e)})
            return
        core.log("journal.fw.retrait_composant_demande")
        res = fwc.retirer_composant_capture()
        if res.get("ok"):
            core.log("journal.fw.composant_retire")
        else:
            core.log("journal.fw.retrait_composant_ko", raison=res.get('raison', '?'))
        self._json(res)

    # ⏏ « Déconnecter » a été RETIRÉ — ne pas le réintroduire sans lire ceci.
    # Il n'avait plus aucun usage :
    #   • il servait surtout à rendre l'USB avant de quitter… ce que
    #     « ⏻ Quitter » fait lui-même ;
    #   • pour céder la wing à `essai_wing_propre.py`, il ne suffit PAS :
    #     ce script refuse de tourner tant que wing_server vit, il faut
    #     donc quitter pour de bon ;
    #   • pour céder la wing à grandMA2 onPC, quitter est plus simple.
    # En face, il coûtait cher : « Déconnecter » puis « Connecter » est un
    # close→reopen, le déclencheur documenté de l'état LENT. C'est
    # exactement la séquence qui a fait échouer une connexion (676 ms, puis
    # wing coincée en bootloader).
    # `disconnect_wing()` est supprimée avec lui : un outil qui n'a plus
    # d'appelant mais reste appelable est un piège, pas un filet.

    def _post_quit(self, body):
        # Quitter RANGE derrière lui : `arret_propre()` fait `arreter_usb()` avant de
        # mourir — un `os._exit` sec pouvait laisser une lecture USB en vol, et le
        # matériel dans un état incertain.
        import wing_ui as core
        core.log("journal.moteur.arret_demande")
        self._json({"ok": True})

        # ⚠️ `core.arret_propre()` DOIT être atteint quoi qu'il arrive : un arrêt
        # qui refuse de s'arrêter serait pire que le bug corrigé ici. C'est LE
        # chemin d'arrêt unique (rend la wing en vol, tue l'assistant clavier,
        # `os._exit`) — partagé mot pour mot avec la fermeture d'onglet
        # (`wing_ui.vie_loop`).
        threading.Timer(0.3, core.arret_propre).start()

    def _post_hard_reset(self, body):
        # Filet de sécurité « gros bug » : redémarre le moteur EN PLACE (même process,
        # os.execv) sans passer par le Terminal, et reprend le code fraîchement
        # reconstruit (build_server.sh écrit dans le bundle). Relance aussi
        # l'assistant clavier (corrige entre autres un PID de MA3 périmé après un
        # redémarrage de MA3).
        import wing_ui as core
        core.log("journal.moteur.redemarrage_demande")
        with etat.E.LOCK:
            etat.E.STATE["mode"] = "idle"
            etat.E.STATE["want_connected"] = False   # pas d'auto-reconnexion pendant l'arrêt
            etat.E.STATE["resume_mode"] = None
        # ⚠️ On NE LIBÈRE PAS la wing ici — `restart_self()` s'en charge juste avant
        # l'execv. Libérer ici allongeait de ~2,4 s le trou entre fermeture et
        # réouverture, et c'est la LONGUEUR de ce trou qui fait décrocher la wing du
        # bus. Moins on la laisse seule, mieux elle se porte.
        self._json({"ok": True})
        # SYNCHRONE et AVANT restart_self() : os.execv() remplace tout le
        # process (tue tous les threads en vol, y compris un thread
        # d'arrière-plan pas encore terminé) — le redémarrage clavier doit
        # donc être fini avant que le minuteur ci-dessous ne se déclenche.
        core.restart_keyboard_helper()
        threading.Timer(0.4, core.restart_self).start()

    def _post_uninstall(self, body):
        # Désinstallation. Corps : {"keep": {"profiles": b, "log": b,
        # "ma3_plugin": b}, "dry_run": b}.
        #
        # 🔑 Calqué sur `_post_quit` : on renvoie d'ABORD les trois listes
        # ({deleted, kept, residue}), puis un `threading.Timer(0.3, …)` fait le
        # ménage et `os._exit(0)`. `dry_run: true` s'arrête après la réponse,
        # sans rien toucher ni quitter — c'est ce que teste le test de fumée.
        import wing_ui as core
        k = body.get("keep") or {}
        keep = {c: wv.booleen(k, c, False) for c in ("profiles", "log", "ma3_plugin")}
        dry_run = wv.booleen(body, "dry_run", False)

        a_supprimer, a_garder = wing_desinstall.plan(keep)
        rep = {"deleted": [str(p) for p in a_supprimer],
               "kept": [str(p) for p in a_garder],
               "residue": wing_desinstall.residu(),
               "dry_run": dry_run}

        if dry_run:
            self._json(rep)
            return

        # ⚠️ GARDE-FOU. Lancé depuis les sources, `PROFILE_DIR.parent` est le
        # dossier `src/` du projet : y passer le ménage effacerait le code. La
        # désinstallation réelle n'a de sens que sur l'app distribuée (figée).
        if not getattr(sys, "frozen", False):
            self._json({"error": "La désinstallation réelle n'est possible que "
                        "depuis l'application installée, pas depuis les "
                        "sources. Utilise dry_run pour prévisualiser."}, 400)
            return

        core.log("journal.desinstall.demandee", supp=len(a_supprimer),
                 garde=len(a_garder))
        self._json(rep)


        threading.Timer(0.3, wing_desinstall.executer,
                        args=(a_supprimer, a_garder)).start()


# ── Noms DÉMÉNAGÉS (audit du 25/09/2026, D3) : voir wing_demenagement.py.
import wing_demenagement
wing_demenagement.garder(__name__, {
    **{n: "wing_desinstall (plan/residu/…)" for n in (
        "_PLUGIN_NOMS", "_sous", "_desinstall_cibles_ma3", "_desinstall_dir_local",
        "_desinstall_plan", "_desinstall_residu")},
    "_chemin_profil": "wing_profils (chemin_profil)",
    "_choisir_fichier": "wing_dialogues (choisir_fichier)",
})
