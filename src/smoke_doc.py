#!/usr/bin/env python3
"""
smoke_doc.py — Wing Bridge
===========================
Domaine cohérence de la doc du test de fumée : tout renvoi `docs/…` écrit
dans le code mène-t-il vraiment quelque part. Voir smoke_core.py pour
ok/echec/note/section/HERE.

🔑 `_ancre` vivait à l'origine juste avant test_branchement_laisse_trace dans
smoke_test.py, par pure proximité physique — mais son seul appelant est
test_renvois_doc, ici. Le script de vérification d'ordre (verifie_ordre_main.py)
l'a détecté immédiatement au premier run après découpage (NameError) : preuve
que grouper par proximité au lieu de par usage réel est le vrai risque de ce
chantier, pas la mécanique du découpage elle-même.
"""

import re

from smoke_core import HERE, ok, echec, note, section


def _ancre(titre: str) -> str:
    """Titre Markdown → ancre, façon GitHub (accents et emoji retirés).

    `## 🔴 Valeurs fantômes après une reconnexion` → `valeurs-fantomes-apres-une-reconnexion`
    """
    import unicodedata
    t = titre.lstrip("#").strip()
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = "".join(c if (c.isalnum() or c in " -_") else " " for c in t.lower())
    return re.sub(r"[\s_]+", "-", t.strip()).strip("-")


def test_renvois_doc(html):
    """Tout renvoi vers la doc écrit dans le code mène-t-il quelque part ?

    Forme visée : une flèche, le chemin du fichier, et une ancre facultative —
    par exemple « voir docs/<fichier>.md#<ancre> ». (Écrit avec des chevrons
    ICI exprès : ce contrôle scanne son propre fichier, et un exemple
    ressemblant à un vrai renvoi se signalerait lui-même. Vécu à la 1re
    exécution.)

    🔑 LE FILET DE LA RÉORGANISATION DES COMMENTAIRES.

    Parti pris : les post-mortems de 20 à 46 lignes recopiés dans le code
    déménagent dans `docs/`, et il ne reste sur place que la RÈGLE en une à
    trois lignes, plus un renvoi. Mesure de départ : 40 % du code était du
    commentaire, dont 116 pavés de 10 lignes et plus.

    ⚠️ LE RISQUE DE CETTE OPÉRATION EST DE PERDRE DU SAVOIR PAYÉ CHER. Ce
    projet le dit lui-même : sa valeur n'est pas le code, ce sont les pièges
    consignés. Un renvoi qui ne mène nulle part, c'est la leçon perdue — et
    perdue EN SILENCE, ce qui est la signature de toutes les pannes chères
    d'ici.

    Ce contrôle supprime ce risque : un lien mort casse le build. Le savoir ne
    peut donc plus disparaître, il peut seulement DÉMÉNAGER.

    ⚠️ Il connaît déjà le piège des renvois morts : `HISTORIQUE.md` pointait
    vers une section « voir plus bas » supprimée sans son renvoi. C'était de
    la doc vers la doc ; ici c'est du code
    vers la doc, et personne ne le verrait passer.
    """
    section("43. Renvois du code vers la doc")
    docs = HERE / "../docs"
    # Ancres disponibles, par fichier
    ancres, titres = {}, {}
    for f in sorted(docs.glob("*.md")):
        t = f.read_text(encoding="utf-8")
        a = {_ancre(l) for l in t.splitlines() if l.startswith("#")}
        a |= set(re.findall(r'<a\s+(?:name|id)="([^"]+)"', t))
        ancres[f.name] = a
        titres[f.name] = [l.strip() for l in t.splitlines() if l.startswith("#")]

    # Renvois écrits dans le code
    fichiers = sorted(HERE.glob("*.py")) + sorted(HERE.glob("ui/*.js"))
    renvois = []          # (source, ligne, cible, ancre)
    for f in fichiers:
        for n, l in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            for m in re.finditer(r"docs/([\w.]+\.md)(?:#([\w-]+))?", l):
                renvois.append((f.name, n, m.group(1), m.group(2)))
    if not renvois:
        note("aucun renvoi `docs/…` dans le code — rien à vérifier pour l'instant")
        return

    # 🔓 Ces trois fichiers (journal de bord daté) sont tenus hors du dépôt
    # public : en local leurs ancres sont vérifiées normalement ; sur un clone
    # public ils sont simplement absents. Un renvoi du code vers l'un d'eux,
    # quand le fichier manque, est donc toléré (noté), pas compté comme lien
    # mort.
    HORS_DEPOT_PUBLIC = {"HISTORIQUE.md", "RELEASES.md", "ETAT_PROJET.md"}

    morts, toleres = [], []
    for src, n, cible, anc in renvois:
        if cible not in ancres:
            if cible in HORS_DEPOT_PUBLIC:
                toleres.append(f"{src}:{n} → {cible}")
                continue
            morts.append(f"{src}:{n} → {cible} (fichier inexistant)")
        elif anc and anc not in ancres[cible]:
            proches = [a for a in sorted(ancres[cible]) if anc[:8] in a][:2]
            indice = f" — voulais-tu {', '.join(proches)} ?" if proches else ""
            morts.append(f"{src}:{n} → {cible}#{anc} (ancre inexistante){indice}")
    if morts:
        echec(f"{len(morts)} renvoi(s) du code vers la doc ne mènent NULLE PART",
              " ; ".join(morts[:6]) + " — la leçon que ce renvoi devait "
              "préserver est perdue. Corriger le lien, ou remettre le contenu")
        return
    avec_ancre = sum(1 for *_, a in renvois if a)
    if toleres:
        note(f"{len(toleres)} renvoi(s) du code vers un journal de bord tenu "
             f"hors dépôt public (absent ici) : "
             f"{', '.join(t.split(' → ')[1] for t in toleres[:4])}… — à "
             f"nettoyer lors de la passe « regard public » des commentaires")
    ok(f"{len(renvois)} renvoi(s) vers docs/ ({avec_ancre} avec ancre), "
       f"{len(renvois) - len(toleres)} résolus"
       + (f", {len(toleres)} tolérés (hors dépôt public)" if toleres else ""))
