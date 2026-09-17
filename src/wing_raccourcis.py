#!/usr/bin/env python3
"""
wing_raccourcis.py — envoi de la table de raccourcis clavier vers MA3
==============================================================================
Extrait de `wing_ui.py` (module issu du découpage, étape 4). Lit l'état
partagé via `etat.E.PROFILE`, les fonctions via `core.log`… — voir
`docs/ARCHITECTURE.md`.

⚠️ `MA3_SHCUTS_DIR` reste DÉFINI dans `wing_ui.py`, pas ici : `smoke_test.py`
le monkeypatche directement sur le module `wing_ui` (`wv.MA3_SHCUTS_DIR =
bac`, sections 19 et 20) pour rediriger les fonctions de ce fichier vers un
dossier temporaire pendant les tests. Si cette constante vivait ICI, un
appel nu à `MA3_SHCUTS_DIR` depuis `_shcuts_fichier()`/`_shcuts_gabarit()`/
`shcuts_etat()` se serait résolu dans l'espace de noms DE CE FICHIER, où le
monkeypatch posé sur `wing_ui` n'a aucun effet — même piège que `ma3_etat()`
dans wing_ma3.py, même remède : accès
qualifié `core.MA3_SHCUTS_DIR` partout, y compris entre fonctions de CE
fichier. `MA3_SHCUTS_NOM`/`MA3_SHCUTS_ORIGINE`, eux, ne sont que LUS par
`smoke_test.py` (jamais réassignés) : ils déménagent sans risque.

⚠️ `import wing_ui as core` est PARESSEUX — DANS chaque fonction qui s'en
sert, jamais en tête de fichier (cycle d'import sûr sous CPython nu, mais
pas sous le bootloader figé de PyInstaller). Et parce que `wing_ui.py` est
le POINT D'ENTRÉE du programme, `wing_ui.py` s'auto-enregistre dans
`sys.modules["wing_ui"]` en tête de fichier, AVANT d'importer ce module.
"""

import etat
import os
import re
import threading
import time
from pathlib import Path

import wing_mapper as wm


# ── Envoi des raccourcis clavier vers MA3 ────────────────────────────────────
#
# L'app et MA3 tiennent chacun une table de raccourcis : l'app ÉCRIT celle de
# MA3 depuis la sienne, pour qu'elles ne divergent jamais. Le format du fichier
# est connu (MA3 l'exporte lui-même), le numéro d'objet de chaque raccourci se
# déduit de sa position (voir shcuts_envoyer).
#
# ⚠️ TROIS RÈGLES :
#  1. UN SEUL FICHIER, toujours le même nom — jamais de copie datée.
#  2. RIEN NE PART SI C'EST DÉJÀ EN PLACE : on compare avant d'écrire.
#  3. ON NE TOUCHE QU'À CE QU'ON GÈRE (49 des 82 touches de MA3) : on PART du
#     fichier existant et on y substitue nos valeurs, sans régénérer le XML.

MA3_SHCUTS_NOM = "WingBridge"          # un seul fichier — voir règle 1
MA3_SHCUTS_ORIGINE = "KeyboardShortCuts"   # gabarit de secours

# ⚠️⚠️ TROIS PIÈGES DU FORMAT :
#  1. UN KEYCODE PEUT AVOIR PLUSIEURS RACCOURCIS (OOPS → Ctrl+Z ET Backspace,
#     MINUS → Minus ET kpSubtract, DOT → Period ET kpDecimal, PLUS → Equal ET
#     kpAdd : clavier principal + pavé numérique). On remplace UNE occurrence —
#     tout remplacer supprimait le pavé numérique en silence.
#  2. LES ATTRIBUTS NE SONT PAS TOUJOURS DANS LE MÊME ORDRE, et certaines
#     entrées n'ont PAS de Shortcut :
#       <KeyboardShortcut KeyCode="EXEC" ExecutorIndex="101" Shortcut="Ctrl+F1"/>
#       <KeyboardShortcut KeyCode="X9"/>
#  3. LES ENTRÉES « EXEC » (ExecutorIndex 101→415) NE SE TOUCHENT JAMAIS : ce
#     sont les raccourcis d'executor de la console.
_RE_SHCUT = re.compile(r'<KeyboardShortcut\b[^>]*?/>')
_RE_ATTR_KC = re.compile(r'\bKeyCode="([^"]*)"')
_RE_ATTR_SC = re.compile(r'\bShortcut="([^"]*)"')
_RE_ATTR_EXEC = re.compile(r'\bExecutorIndex="')


_RE_ATTR_SPECIAL = re.compile(r'\bSpecialExec="([^"]*)"')


def _shcut_est_executor(balise: str) -> bool:
    """Entrée de RACCOURCI D'EXECUTOR (Ctrl+F1, Alt+F5, GrandKnob…) ?

    ⚠️ Deux formes, et j'avais raté la seconde :
        KeyCode="EXEC" ExecutorIndex="101"          → Ctrl+F1
        KeyCode="EXEC" SpecialExec="GrandKnob"      → Ctrl+B
    Ne filtrer que la première laissait le GrandKnob passer pour une touche
    ordinaire nommée « EXEC ».
    """
    return bool(_RE_ATTR_EXEC.search(balise) or _RE_ATTR_SPECIAL.search(balise))


def _shcut_libelle(balise: str, kc: str) -> str:
    """Nom lisible d'une entrée, pour les messages de collision."""
    ei = re.search(r'\bExecutorIndex="([^"]*)"', balise)
    if ei:
        return f"l'executor {ei.group(1)}"
    sp = _RE_ATTR_SPECIAL.search(balise)
    if sp:
        return f"l'executor « {sp.group(1)} »"
    return kc


def _shcuts_entrees(texte: str, executors: bool = False):
    """[(balise, KeyCode, Shortcut|None)] — dans l'ordre du fichier.

    `executors=False` (défaut) écarte les raccourcis d'executor : ce ne sont
    pas des touches de la wing, on ne les réécrit JAMAIS.
    `executors=True` les inclut — indispensable pour détecter les collisions,
    car ils occupent réellement des frappes (Ctrl+F1…F12, Alt+F1…F12,
    Ctrl+Alt+F1…F12, Ctrl+B). Choisir l'une d'elles ferait partir un executor
    au lieu de la fonction voulue.
    """
    out = []
    for m in _RE_SHCUT.finditer(texte):
        balise = m.group(0)
        kc = _RE_ATTR_KC.search(balise)
        if not kc:
            continue
        if not executors and _shcut_est_executor(balise):
            continue
        sc = _RE_ATTR_SC.search(balise)
        out.append((balise, kc.group(1), sc.group(1) if sc else None))
    return out


def _shcuts_par_touche(texte: str) -> dict:
    """{KeyCode: [raccourcis…]} — une LISTE, jamais une valeur (piège 1)."""
    d = {}
    for _, kc, sc in _shcuts_entrees(texte):
        if sc:
            d.setdefault(kc, []).append(sc)
    return d


def _shcuts_fichier() -> Path:
    import wing_ui as core
    return core.MA3_SHCUTS_DIR / f"{MA3_SHCUTS_NOM}.xml"


def _shcuts_gabarit():
    """Texte XML de départ : notre fichier s'il existe, sinon celui de MA3.

    Sans gabarit on ne peut PAS écrire : on ne connaît que 49 touches sur 82,
    et fabriquer un fichier partiel effacerait les 33 autres.
    """
    import wing_ui as core
    for nom in (MA3_SHCUTS_NOM, MA3_SHCUTS_ORIGINE):
        p = core.MA3_SHCUTS_DIR / f"{nom}.xml"
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8"), p
            except Exception:
                continue
    return None, None


def _shcut_norme(spec: str) -> str:
    """Forme comparable d'une frappe. « S » et « s » sont LA MÊME TOUCHE.

    🐛 Vu au premier essai. Sans ça, la comparaison trouvait 18 « écarts »
    dont 16 n'étaient qu'une différence de casse (MA3 écrit « S », l'app
    « s »), et « PageUp » contre « pageup ». Le bouton aurait réécrit le
    fichier à chaque clic pour ne rien changer — précisément ce qu'on veut
    éviter (voir règle 2).
    """
    return "+".join(p.strip().lower() for p in str(spec or "").split("+") if p.strip())


def _shcuts_vocabulaire(texte: str) -> dict:
    """Orthographe exacte de MA3 pour chaque touche : {forme normalisée: mot}.

    On l'APPREND du fichier de MA3 plutôt que de la recopier : il contient
    déjà Ctrl, Alt, Shift, PageUp, Backspace, LeftBracket, kpAdd… avec leur
    casse officielle. La liste suit donc la version installée, sans rien à
    maintenir ici — même principe que pour les attributs et les mots-clés.
    """
    vocab = {}
    for _, _, sc in _shcuts_entrees(texte):
        if not sc:
            continue
        vocab.setdefault(_shcut_norme(sc), sc)      # la frappe entière
        for part in sc.split("+"):                  # …et chaque morceau
            p = part.strip()
            if p:
                vocab.setdefault(p.lower(), p)
    return vocab


def _shcut_style_ma3(spec: str, vocab: dict) -> str:
    """Réécrit une frappe DANS L'ORTHOGRAPHE DE MA3.

    🐛 Signalé : « Update » mis sur « n » ;
    l'app a écrit `Shortcut="n"` et MA3 n'a plus rien fait sur cette touche —
    alors qu'avec les raccourcis désactivés, le « n » s'écrivait bien dans la
    ligne de commande (donc la frappe partait correctement). Or MA3 note TOUJOURS
    ses lettres en majuscule dans ce fichier : S, U, E, B, H, Q, O…
    Écrire « n » là où MA3 écrit « N » est le genre de détail qui fait rejeter
    une entrée en silence — la signature de ce projet.

    On respecte donc son orthographe, apprise de son propre fichier.

    ⚠️ MAIS on ne consulte PAS le vocabulaire pour un caractère seul, et c'est
    délibéré : le fichier dont on l'apprend est celui que l'app a déjà écrit.
    Au premier essai, « n » s'y trouvait — écrit par nous — et le vocabulaire
    a donc « confirmé » notre propre erreur. Un dictionnaire qui apprend de ses
    élèves ne corrige plus rien. Pour les lettres seules, la règle de MA3
    s'applique sans discuter : MAJUSCULE (son fichier d'origine n'a que
    S, U, E, B, H, L, O, Q, C, F, G, P, T, I, A).
    """
    morceaux = []
    for part in str(spec).split("+"):
        p = part.strip()
        if not p:
            continue
        # Caractère seul → majuscule, point. Sinon, l'orthographe de MA3.
        morceaux.append(p.upper() if len(p) == 1 else vocab.get(p.lower(), p))
    return "+".join(morceaux)


def _shcuts_du_profil() -> dict:
    """Ce que l'app veut voir dans MA3 : {KeyCode: frappe}.

    Renvoie aussi la liste des touches volontairement écartées, pour que
    l'interface puisse les MONTRER : une exclusion muette est un piège.

    Deux exclusions :
      • frappe VIDE → une absence de réglage n'est pas un réglage ; l'écrire
        effacerait celui de l'utilisateur ;
      • écart ASSUMÉ **encore à sa valeur documentée** (wm.ecart_assume).
        Cas vécu : « Oops » part en Ctrl+Z, qui fonctionne, pendant que MA3
        garde Backspace — y écrire Ctrl+Z priverait du Backspace pour rien.

    ⚠️ L'exclusion suit la VALEUR, pas le token. Si l'utilisateur change la
    touche, c'est son choix qui gagne et elle repart vers MA3. La version
    précédente excluait le token quoi qu'il arrive : un « Assign » modifié à
    la main n'était jamais envoyé, en silence.
    """
    import wing_ui as core
    with etat.E.LOCK:
        keys = dict(etat.E.PROFILE.get("console_keys", {}))
    table, ecartes = {}, []
    for token, spec in keys.items():
        if not spec:
            continue
        if wm.ecart_assume(token, spec):
            ecartes.append({"touche": token, "frappe": spec,
                            "pourquoi": wm.ECARTS_ASSUMES[token][1]})
            continue
        table[wm.keycode_de(token)] = spec
    return table, ecartes


def _shcuts_ma3_reel(texte: str):
    """Table de raccourcis TELLE QUE MA3 LA TIENT, vue par la sonde Lua.

    Renvoie ({KeyCode: [frappes]}, via) ou (None, note). C'est la SEULE source
    qui prouve quelque chose : le fichier, lui, est écrit par l'app elle-même
    et ne dit rien de ce que la console a réellement chargé.

    ⚠️ JOINTURE PAR POSITION, pas par nom. La sonde rend `keycode` sous forme
    de NOMBRE (3, 4, 5…), pas de nom (« PREV », « SET »). On associe donc
    chaque entrée à son rang, et c'est le fichier
    qui fournit le nom.

    C'est légitime pour deux raisons : la même clé sert déjà à ÉCRIRE
    (`Set KeyboardShortcut <n>`), et l'égalité des deux listes a été vérifiée
    entrée par entrée — 157 positions sur 157 identiques, y compris l'ordre.

    ⚠️⚠️ GARDE-FOU : si les deux listes n'ont PAS la même longueur, la jointure
    ne vaut plus rien et on rend None. Mieux vaut dire « non vérifié » que
    comparer deux touches qui n'ont rien à voir — ce serait pire que pas de
    vérification du tout.
    """
    import wing_ui as core
    e = core.ma3_etat()
    if not e.get("actif"):
        return None, "sonde MA3 absente"
    liste = e.get("raccourcis")
    if not liste:
        return None, (e.get("raccourcis_note")
                      or "la sonde ne remonte pas les raccourcis "
                         "(plugin MA3 à relancer : Plugin 3 deux fois)")
    entrees = _shcuts_entrees(texte, executors=True)
    if len(entrees) != len(liste):
        return None, (f"désaccord de structure : {len(liste)} raccourcis dans "
                      f"MA3, {len(entrees)} dans le fichier — jointure "
                      f"impossible, aucune vérification faite")
    table = {}
    for (balise, kc, _), r in zip(entrees, liste):
        if _shcut_est_executor(balise):
            continue                  # pas des touches de la wing
        fr = str(r.get("frappe") or "").strip()
        if kc and fr:
            table.setdefault(kc, []).append(fr)
    return (table or None), e.get("raccourcis_via")


def shcuts_etat() -> dict:
    """Compare la table de l'app à celle de MA3. N'écrit rien.

    Deux sources, et elles ne se valent PAS :
      • la SONDE (dans MA3) → ce que la console a vraiment. Preuve.
      • le FICHIER           → ce que l'app a écrit. Ne prouve rien.
    Quand la sonde répond, c'est elle qui fait autorité, et l'écart entre les
    deux devient une information de premier ordre : il dit que MA3 n'a PAS
    appliqué ce qu'on lui a envoyé.
    """
    import wing_ui as core
    texte, source = _shcuts_gabarit()
    voulu, ecartes = _shcuts_du_profil()
    base = {"dossier": str(core.MA3_SHCUTS_DIR),
            "fichier": _shcuts_fichier().name,
            "existe": _shcuts_fichier().is_file(),
            "gabarit": source.name if source else None,
            # Montrées à l'interface : une touche écartée en silence est
            # exactement le piège qu'on vient de corriger.
            "ecartees": ecartes,
            "geres": len(voulu)}
    if texte is None:
        import wing_i18n
        base.update(possible=False, a_jour=False, ecarts=[],
                    erreur=wing_i18n.L("err.shcuts.fichier_ma3_absent",
                                       dossier=core.MA3_SHCUTS_DIR))
        return base

    actuel = _shcuts_par_touche(texte)
    vocab = _shcuts_vocabulaire(texte)
    ecarts, collisions = [], []
    for kc, spec in sorted(voulu.items()):
        if kc not in actuel:
            continue              # touche que CE MA3 ne connaît pas : on passe
        # ✅ ACCORD = l'orthographe EXACTE de MA3 figure déjà parmi ses valeurs.
        #
        # Deux raisons de comparer la forme canonique et non la forme brute :
        #   • OOPS vaut [Ctrl+Z, Backspace] — les deux marchent, aucun écart.
        #     Comparer à « la dernière » inventait une divergence (c'est ce qui
        #     avait fait naître ECARTS_ASSUMES) ;
        #   • une valeur juste MAIS mal orthographiée doit être corrigée. Le
        #     fichier contenait « n » là où MA3 écrit « N » — écrit par nous —
        #     et une comparaison insensible à la casse la déclarait conforme.
        #     La faute se serait installée à demeure.
        canon = _shcut_style_ma3(spec, vocab)
        if canon in actuel[kc]:
            continue
        ecarts.append({"touche": kc, "ma3": " / ".join(actuel[kc]),
                       "app": spec if spec == canon else f"{spec} → {canon}"})

    # ⚠️ COLLISION : notre frappe est-elle DÉJÀ celle d'une AUTRE touche de MA3 ?
    # MA3 ne peut pas deviner laquelle on veut (Assign sur Ctrl+Alt+F, déjà pris
    # par SELFIX → SelectFixtures s'affichait). Balayage COMPLET, executors compris
    # (Ctrl/Alt/Ctrl+Alt+F1…F12 et Ctrl+B sont occupés).
    occupe = {}
    for balise, kc, sc in _shcuts_entrees(texte, executors=True):
        if sc:
            occupe.setdefault(_shcut_norme(sc), set()).add(
                _shcut_libelle(balise, kc))
    for kc, spec in sorted(voulu.items()):
        # ⚠️ Uniquement les touches que CE MA3 connaît : on ne signale pas une
        # collision sur une touche qu'on n'écrira jamais. Sans ce filtre, le
        # contrôle criait sur 15 touches absentes du fichier.
        if kc not in actuel:
            continue
        autres = occupe.get(_shcut_norme(spec), set()) - {kc, _shcut_libelle("", kc)}
        if autres:
            collisions.append({"touche": kc, "frappe": spec,
                               "occupee_par": sorted(autres)})
    actif = 'KeyboardShortcutsActive="Yes"' in texte
    # « À jour » exige AUSSI que la table soit active : un fichier juste mais
    # désactivé ne produit aucun raccourci dans MA3.
    # ⚠️ Santé de la liaison OSC. SANS ELLE, « à jour » ne veut rien dire :
    # l'état est lu dans le FICHIER, que l'app vient d'écrire elle-même. Si
    # MA3 n'écoute pas, les commandes `Set` sont tombées dans le vide et
    # l'interface annoncerait quand même le succès — le mensonge poli que ce
    # projet a déjà payé deux fois (PID de MA3 périmé, frappes « ✓ envoyées »).
    # ── CONFIRMATION HONNÊTE : ce que MA3 tient vraiment ─────────────────────
    # ⚠️ DEUX QUESTIONS DIFFÉRENTES, ne pas les mélanger — le premier jet les
    # mélangeait et le test l'a attrapé :
    #
    #   ecarts        app ≠ FICHIER   → « il reste des choses à envoyer »
    #   non_applique  FICHIER ≠ MA3   → « on a écrit, la console n'a pas pris »
    #
    # Seule la seconde dit quelque chose sur l'ENVOI. Comparer l'app à MA3
    # confondait « pas encore envoyé » et « envoyé mais refusé » — or c'est
    # exactement la différence qu'on cherche à établir.
    reel, via = _shcuts_ma3_reel(texte)
    non_applique, confirme = [], []
    if reel:
        for kc, ecrits in sorted(actuel.items()):
            if kc not in voulu or kc not in reel:
                continue              # touche non gérée par l'app
            attendu = ecrits[0]       # ce que le fichier porte
            if any(_shcut_norme(v) == _shcut_norme(attendu) for v in reel[kc]):
                confirme.append(kc)
            else:
                # 🎯 LE CAS QUI COMPTE. C'est la panne déjà vécue : « Import »
                # écrivait le fichier sans que MA3 le relise, et l'app
                # annonçait le succès en relisant son propre fichier.
                non_applique.append({"touche": kc, "voulu": attendu,
                                     "dans_ma3": " / ".join(reel[kc])})

    base.update(possible=True, ecarts=ecarts, actif=actif,
                osc=core.ma3_reachable(),
                # sonde=None : aucune preuve, on le DIT au lieu de supposer.
                sonde=bool(reel), sonde_via=via,
                confirmes=len(confirme), non_applique=non_applique,
                collisions=collisions,
                inconnus=sorted(set(voulu) - set(actuel)),
                intacts=len(set(actuel) - set(voulu)),
                # ⚠️ « À jour » exige AUSSI que MA3 n'ait rien de contradictoire
                # quand la sonde répond. Sans elle, on retombe sur le fichier —
                # et l'interface précise alors que ce n'est pas une preuve.
                a_jour=(not ecarts and not non_applique and actif
                        and _shcuts_fichier().is_file()))
    return base


def _marquer_shcuts_envoyes():
    """Horodate le dernier succès de shcuts_envoyer() — SETTINGS, pas le
    profil (voir le commentaire au-dessus de `shcuts_horodate` dans
    wing_ui.SETTINGS : c'est un fait de CETTE machine, pas du profil)."""
    import wing_ui as core
    core.reglage_poser(shcuts_horodate=time.time())
    core.save_settings()


def shcuts_envoyer(force: bool = False) -> dict:
    """Écrit la table dans MA3 et demande l'import. Ne fait RIEN si c'est déjà
    en place — sauf `force`, pour le cas où MA3 aurait été rechargé."""
    import wing_ui as core
    constat = shcuts_etat()
    if not constat.get("possible"):
        return {"ok": False, "erreur": constat.get("erreur")}
    if constat["a_jour"] and not force:
        core.log("journal.shcut.deja_jour")
        _marquer_shcuts_envoyes()
        return {"ok": True, "inchange": True, "etat": constat}

    # ⚠️ COLLISION = ON N'ÉCRIT PAS. Envoyer une frappe déjà utilisée par une
    # autre touche de MA3 ne « marche à moitié » pas : la console choisit
    # l'autre fonction, et l'utilisateur croit à une panne de la wing. Vécu :
    # Ctrl+Alt+F, déjà pris par SELFIX → SelectFixtures s'affichait à la place
    # d'Assign. Mieux vaut refuser en le disant.
    if constat.get("collisions") and not force:
        c = constat["collisions"][0]
        core.log("journal.shcut.collision", frappe=c['frappe'],
                 qui=', '.join(c['occupee_par']))
        import wing_i18n
        return {"ok": False, "collisions": constat["collisions"],
                "erreur": wing_i18n.L("err.shcuts.collision"),
                "etat": constat}

    texte, _ = _shcuts_gabarit()
    voulu, _ecartes = _shcuts_du_profil()
    actuel = _shcuts_par_touche(texte)
    vocab = _shcuts_vocabulaire(texte)
    faits = []

    # Touches à corriger : celles dont l'orthographe EXACTE de MA3 n'est pas
    # déjà présente. Même critère que shcuts_etat — les deux doivent rester
    # d'accord, sinon le bouton annonce « à jour » et n'écrit rien, ou l'
    # inverse.
    a_faire = {kc: _shcut_style_ma3(spec, vocab)
               for kc, spec in voulu.items()
               if kc in actuel
               and _shcut_style_ma3(spec, vocab) not in actuel[kc]}
    # …et celles que la SONDE dément (fichier bon, MA3 qui tient autre chose) : on
    # ré-émet la valeur du fichier. Sans ça, 0 commande partait et « envoyé »
    # s'affichait quand même. (Un redémarrage de MA3 laisse la table intacte : ne
    # pas l'invoquer comme cause.)
    for x in constat.get("non_applique") or []:
        kc = x["touche"]
        if kc in voulu and kc in actuel:
            a_faire.setdefault(kc, _shcut_style_ma3(voulu[kc], vocab))

    # Numéro d'objet de chaque entrée = sa POSITION dans le fichier, 1-based,
    # entrées d'executor COMPRISES.
    #
    # ✅ CONFIRMÉ SUR LA CONSOLE (`List KeyboardShortcut`) :
    #     120 ASSIGN · 121 TIME · 122 UPDATE · 123 STORE · … · 157 ONPC_SCREEN7
    # Ce sont exactement les positions calculées depuis le fichier. C'est ce
    # numéro qu'attend `Set KeyboardShortcut <n> Property "Shortcut" "<v>"`.
    #
    # ⚠️ Ne JAMAIS ajouter ni retirer d'entrée : toute la numérotation
    # glisserait, et un `Set` irait modifier la mauvaise touche. On se contente
    # de changer des valeurs en place — c'est ce qui rend ces numéros stables.
    compteur = {"n": 0}
    commandes = []

    def _remplacer(m):
        balise = m.group(0)
        compteur["n"] += 1
        no = compteur["n"]
        kc = _RE_ATTR_KC.search(balise)
        if not kc or _shcut_est_executor(balise):
            return balise                  # jamais les executors
        kc = kc.group(1)
        neuf = a_faire.pop(kc, None)       # ⚠️ pop : UNE SEULE occurrence
        if neuf is None:
            return balise                  # pas géré, déjà bon, ou déjà traité
        # 🔒 Défense en profondeur (audit du 25/09/2026) : le profil est déjà
        # filtré au chargement et à la saisie (wm.raccourci_valide), mais ce
        # texte part dans le XML de MA3 ET dans une commande OSC entre
        # guillemets. Un chemin d'entrée oublié ne doit rien pouvoir y glisser.
        if not wm.raccourci_valide(neuf):
            core.log("journal.shcut.frappe_refusee", touche=kc, frappe=neuf[:40])
            return balise
        sc = _RE_ATTR_SC.search(balise)
        ancien = sc.group(1) if sc else None
        faits.append(f"{kc} {ancien or '—'} → {neuf}  (n°{no})")
        commandes.append(
            f'Set KeyboardShortcut {no} Property "Shortcut" "{neuf}"')
        echappe = (neuf.replace("&", "&amp;").replace('"', "&quot;")
                   .replace("<", "&lt;").replace(">", "&gt;"))
        if sc:
            return balise[:sc.start(1)] + echappe + balise[sc.end(1):]
        # Entrée sans Shortcut (ex. X9) : on en ajoute un.
        return balise[:-2].rstrip() + f' Shortcut="{echappe}"/>'

    # ⚠️ `pop` ci-dessus est le cœur du correctif : une touche n'est réécrite
    # QU'UNE FOIS. OOPS possède deux entrées (Ctrl+Z et Backspace) ; l'ancienne
    # version les remplaçait toutes les deux par la même valeur et supprimait
    # donc Backspace. Même piège pour MINUS/PLUS/DOT/SLASH, qui font cohabiter
    # le clavier principal et le pavé numérique.
    texte = _RE_SHCUT.sub(_remplacer, texte)
    texte = texte.replace('KeyboardShortcutsActive="No"',
                          'KeyboardShortcutsActive="Yes"')

    cible = _shcuts_fichier()
    try:
        core.MA3_SHCUTS_DIR.mkdir(parents=True, exist_ok=True)
        # Écriture atomique, sur le MÊME nom : aucune copie ne s'accumule.
        tmp = cible.with_suffix(".xml.part")
        tmp.write_text(texte, encoding="utf-8")
        os.replace(tmp, cible)
        wm.own_like_parent(cible)
    except Exception as e:
        core.log("journal.shcut.ecriture_ko", err=e)
        return {"ok": False, "erreur": str(e)}

    # ── Application IMMÉDIATE dans MA3 ───────────────────────────────────────
    #
    # ❌ `Import KeyboardShortcut Library "…"` NE MARCHE PAS. Syntaxe tirée du
    # manuel, envoyée 5 fois, jamais appliquée : constaté en réel — la touche
    # ne répondait qu'après un Import fait À LA MAIN dans le menu de MA3.
    # Signalée « non vérifiée », elle l'est maintenant, et elle est fausse.
    # Ne pas la remettre.
    #
    # ✅ `Set KeyboardShortcut <n> Property "Shortcut" "<v>"` est documentée
    # AVEC un exemple, et la numérotation a été confirmée sur la console.
    # Elle s'applique tout de suite, sans fichier ni import.
    #
    # On fait quand même LES DEUX : la commande pour l'effet immédiat, le
    # fichier pour que le réglage survive au rechargement du profil.
    for i, cmd in enumerate(commandes):
        # Espacées : la ligne de commande de MA3 sature quand on la bombarde
        # (leçon des faders). Quelques touches à la fois, jamais un
        # flot.
        threading.Timer(0.15 * i,
                        lambda c=cmd: etat.E.OSC.send_message("/cmd", c)).start()
    core.log("journal.shcut.applique", n=len(faits), fichier=cible.name,
             m=len(commandes))
    for f in faits[:12]:
        core.log(f"   • {f}")
    for c in commandes[:12]:
        core.log(f"   → {c}")
    _marquer_shcuts_envoyes()
    return {"ok": True, "inchange": False, "modifies": faits,
            "commandes": commandes, "etat": shcuts_etat()}
