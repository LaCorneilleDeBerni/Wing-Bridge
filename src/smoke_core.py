#!/usr/bin/env python3
"""
smoke_core.py — Wing Bridge
============================
Le socle partagé du test de fumée : compteurs globaux (ECHECS/NOTES/SECTIONS),
affichage (ok/echec/note/section), et les extracteurs HTML/JS utilisés par
plusieurs domaines (_blocs_js, _js_manquants, _page, _js_de, _poster).

🔑 Issu du découpage de smoke_test.py en plusieurs fichiers, même principe que
le découpage de wing_ui.py. Ce fichier est ce qui garde le compteur
dynamique de contrôles VRAI après la répartition en plusieurs fichiers :
ECHECS/NOTES/SECTIONS restent des listes UNIQUES, importées partout, jamais
redéfinies ailleurs — un domaine qui ferait `SECTIONS = []` de son côté
casserait le décompte en silence. smoke_test.py reste le seul point d'entrée
et orchestre l'appel des contrôles ; ce fichier ne contient aucun `test_*`.
"""

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent

ECHECS = []
NOTES = []
SECTIONS = []   # titres joués, pour compter les contrôles réellement exécutés


def ok(titre):
    print(f"  \033[32m✓\033[0m {titre}")


def echec(titre, detail=""):
    print(f"  \033[31m✗\033[0m {titre}")
    if detail:
        for l in str(detail).strip().split("\n")[:12]:
            print(f"      {l}")
    ECHECS.append(titre)


def note(msg):
    print(f"  \033[33m•\033[0m {msg}")
    NOTES.append(msg)


def section(titre):
    SECTIONS.append(titre)
    print(f"\n\033[1m{titre}\033[0m")


def _blocs_js(html: str):
    """[(nom, code)] — le JS de l'interface : blocs inline PUIS `<script src>`.

    🔑 Cœur du découpage du JS. Trois contrôles (test_js, test_onclick, test_js_execute) extrayaient le
    `<script>` inline à la main. En sortant le JS dans `wing_ui.js`, ils
    seraient tous devenus AVEUGLES d'un coup — et test_js comme test_js_execute auraient
    échoué sur « aucun bloc <script> trouvé », ce qui est encore le cas
    heureux : le pire aurait été qu'ils passent au vert sur du vide.
    Ils passent donc tous par ici.

    Le NOM est rendu avec le code pour que les messages d'erreur disent QUEL
    fichier est en cause — avec plusieurs fichiers, « bloc n°3 » ne
    renseignerait sur rien.

    ⚠️ Un `<script src>` introuvable est signalé par `_js_manquants()`, pas
    ignoré : c'est exactement la panne « interface inerte » que le garde-fou
    des scripts de build vise aussi.
    """
    blocs = [(f"<script> inline n°{i}", c) for i, c in
             enumerate(re.findall(r"<script>(.*?)</script>", html, re.S), 1)]
    for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html):
        f = HERE / src.lstrip("/")
        if f.is_file():
            blocs.append((src, f.read_text(encoding="utf-8")))
    return blocs


def _js_manquants(html: str):
    """Les `<script src>` du HTML qui ne correspondent à aucun fichier."""
    return [src for src in re.findall(r'<script[^>]*\bsrc="([^"]+)"', html)
            if not (HERE / src.lstrip("/")).is_file()]


def _page(html: str) -> str:
    """Le balisage ET le JavaScript, bout à bout.

    🔑 Pour les contrôles qui cherchent « quelque part dans l'interface » sans
    se soucier du fichier : un libellé de bouton, un message de pastille, une
    liste déroulante construite en JS. Avant le découpage du JS tout vivait
    dans `wing_ui.html` et `html` suffisait ; depuis, la moitié est ailleurs.

    ⚠️ TROIS CONTRÔLES ONT SILENCIEUSEMENT DÉCROCHÉ en sortant le
    JS — test_types_fader_documentes (types de fader), test_encodeurs_ma3 (majEncMa3), test_messages_actionnables (pastille bootloader) —
    et deux autres (test_boutons_wing_uniques, test_diagnostic_osc) cherchaient des noms de fonction dans le
    balisage. Aucun n'a échoué : ils se sont mis en « contrôle sauté ». Un
    garde-fou qui se saute tout seul ne garde plus rien, et il ne le dit pas.
    """
    return html + "\n" + _js_de(html)


def _js_de(html: str) -> str:
    """Tout le JavaScript de l'interface — inline ET fichiers `<script src>`.

    🔑 Écrit pour le découpage du JS hors du HTML. Tant que le
    script est inline, on le lit là ; dès qu'il part dans un fichier à côté, on
    le lit là aussi. Les contrôles qui en dépendent n'ont pas à savoir lequel
    des deux — sans quoi le découpage les rendrait tous aveugles d'un coup,
    silencieusement, ce qui est exactement le contraire du but recherché.

    ⚠️ Un `<script src>` introuvable est IGNORÉ ici, mais le contrôle test_js des
    ressources, lui, le refuse : c'est son travail, pas celui de cette fonction.
    """
    return "\n".join(code for _, code in _blocs_js(html))


def _poster(ui, chemin, corps):
    """Appelle le handler POST de `chemin` sans ouvrir de socket.

    On instancie le handler sans passer par son __init__ (qui voudrait une
    connexion réseau) et on remplace la seule sortie qu'il utilise.

    🔑 Partagé entre deux domaines distincts (boutons/hardware et profils) :
    voir smoke_hardware.py::test_boutons_honnetes et
    smoke_profils.py::test_import_profil.
    """
    h = ui.Handler.__new__(ui.Handler)
    h.path = chemin
    rendu = {}
    h._json = lambda d, code=200: rendu.update(d)
    h.do_POST_body = corps
    # Le handler lit le corps depuis `body` : on court-circuite en appelant
    # directement la portion de dispatch via une méthode dédiée si elle existe,
    # sinon on rejoue do_POST avec un flux simulé.
    import io, json as _j
    brut = _j.dumps(corps).encode()
    h.rfile = io.BytesIO(brut)
    # X-Wing-Jeton : la vraie interface le joint à chaque POST (ui/core.js,
    # api()) — sans lui, le handler refuse désormais (test_jeton_api).
    h.headers = {"Content-Length": str(len(brut)),
                 "Origin": "http://127.0.0.1:8765",
                 "Host": "127.0.0.1:8765",
                 "X-Wing-Jeton": ui.API_JETON}
    h.send_response = lambda *a, **k: None
    h.send_header = lambda *a, **k: None
    h.end_headers = lambda *a, **k: None
    h.wfile = io.BytesIO()
    h.do_POST()
    return rendu
