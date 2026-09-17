"""Validation des entrées de l'API HTTP — un seul endroit, un seul refus.

POURQUOI (audit du 25/09/2026, point D3). Chaque route de `wing_handler.py`
lisait ses paramètres à la main : `int(body.get(...))` sans borne,
`bool(body.get("actif"))` — qui rend VRAI pour la chaîne "false" —,
`.strip()` qui plante sur un nombre. Résultat : des 500 au lieu de refus
clairs, et des défauts réels, par exemple :
  • `/api/fader/nom` avec un index de 10 000 ajoutait 10 000 étiquettes vides
    au profil ; avec un index NÉGATIF, il renommait un fader compté depuis la
    fin de la liste ;
  • un `exec` texte partait tel quel dans la commande envoyée à MA3.

Ici, chaque lecture dit ce qu'elle attend (type, bornes, valeurs permises).
Un écart lève `EntreeInvalide`, que `Handler._executer` transforme en
réponse 400 JSON avec la raison — jamais en 500, jamais en valeur devinée.

⚠️ Un paramètre ABSENT prend son défaut ; un paramètre PRÉSENT mais invalide
est REFUSÉ. On ne corrige pas en silence ce que l'interface a envoyé : si
elle envoie n'importe quoi, c'est un bug qu'on veut voir.

Les TYPES d'un profil (faders, pas des roues, raccourcis) restent validés par
`wing_mapper.valider_types` / `raccourci_valide` : ce module-ci ne s'occupe
que de la forme des requêtes. Contrôle test_validation_entrees.
"""

import math

_ABSENT = object()


class EntreeInvalide(ValueError):
    """Paramètre de requête inexploitable → réponse 400."""


def _L(cle_i18n, **params):
    # ⚠️ Le nom du champ refusé s'appelle `champ` dans les messages, PAS
    # `cle` : `wing_i18n.L(cle, **params)` prend déjà `cle` — conflit.
    import wing_i18n
    return wing_i18n.L(cle_i18n, **params)


def _lire(body, cle, defaut):
    if not isinstance(body, dict):
        raise EntreeInvalide(_L("err.entree.corps"))
    v = body.get(cle, _ABSENT)
    if v is _ABSENT or v is None:
        if defaut is _ABSENT:
            raise EntreeInvalide(_L("err.entree.manquant", champ=cle))
        return _ABSENT
    return v


def entier(body, cle, mini, maxi, defaut=_ABSENT) -> int:
    """Entier dans [mini, maxi]. Accepte un nombre entier ou une chaîne de
    chiffres (les <input type=number> envoient parfois du texte). Refuse
    booléen, flottant non entier, texte quelconque."""
    v = _lire(body, cle, defaut)
    if v is _ABSENT:
        return defaut
    if isinstance(v, bool):
        raise EntreeInvalide(_L("err.entree.entier", champ=cle, v=repr(v)[:40]))
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        v = int(v.strip())
    if not isinstance(v, int):
        raise EntreeInvalide(_L("err.entree.entier", champ=cle, v=repr(v)[:40]))
    if not (mini <= v <= maxi):
        raise EntreeInvalide(_L("err.entree.bornes", champ=cle, v=v,
                                mini=mini, maxi=maxi))
    return v


def hexa(body, cle, mini, maxi, defaut=_ABSENT) -> int:
    """Entier écrit en hexadécimal (« 0x03EB », « 78 »), dans [mini, maxi]."""
    v = _lire(body, cle, defaut)
    if v is _ABSENT:
        return defaut
    if isinstance(v, int) and not isinstance(v, bool):
        n = v
    else:
        try:
            n = int(str(v), 16)
        except ValueError:
            raise EntreeInvalide(_L("err.entree.hexa", champ=cle, v=repr(v)[:40]))
    if not (mini <= n <= maxi):
        raise EntreeInvalide(_L("err.entree.bornes", champ=cle, v=n,
                                mini=mini, maxi=maxi))
    return n


def reel(body, cle, mini, maxi, defaut=_ABSENT) -> float:
    """Nombre fini dans [mini, maxi]."""
    v = _lire(body, cle, defaut)
    if v is _ABSENT:
        return defaut
    if isinstance(v, str):
        try:
            v = float(v.strip())
        except ValueError:
            raise EntreeInvalide(_L("err.entree.reel", champ=cle, v=repr(v)[:40]))
    if isinstance(v, bool) or not isinstance(v, (int, float)) \
            or not math.isfinite(v):
        raise EntreeInvalide(_L("err.entree.reel", champ=cle, v=repr(v)[:40]))
    if not (mini <= v <= maxi):
        raise EntreeInvalide(_L("err.entree.bornes", champ=cle, v=v,
                                mini=mini, maxi=maxi))
    return float(v)


def booleen(body, cle, defaut=_ABSENT) -> bool:
    """Vrai booléen JSON (true/false), ou 0/1. ⚠️ Refuse la chaîne "false" :
    `bool("false")` vaut True en Python — c'était le piège."""
    v = _lire(body, cle, defaut)
    if v is _ABSENT:
        return defaut
    if isinstance(v, bool):
        return v
    if isinstance(v, int) and v in (0, 1):
        return bool(v)
    raise EntreeInvalide(_L("err.entree.booleen", champ=cle, v=repr(v)[:40]))


def texte(body, cle, longueur_max, defaut=_ABSENT) -> str:
    """Chaîne, espaces de bord retirés, au plus `longueur_max` caractères."""
    v = _lire(body, cle, defaut)
    if v is _ABSENT:
        return defaut
    if not isinstance(v, str):
        raise EntreeInvalide(_L("err.entree.texte", champ=cle, v=repr(v)[:40]))
    v = v.strip()
    if len(v) > longueur_max:
        raise EntreeInvalide(_L("err.entree.longueur", champ=cle,
                                n=len(v), maxi=longueur_max))
    return v


def choix(body, cle, permis, defaut=_ABSENT):
    """Une valeur parmi `permis`."""
    v = _lire(body, cle, defaut)
    if v is _ABSENT:
        return defaut
    if v not in permis:
        raise EntreeInvalide(_L("err.entree.choix", champ=cle, v=repr(v)[:40],
                                permis=", ".join(map(str, permis))[:200]))
    return v


def groupes_encodeurs(body, cle, nb_roues=4, groupes_max=16):
    """Liste de groupes ; chaque groupe = `nb_roues` noms d'attribut (texte
    de 40 caractères au plus) ou null. None si le paramètre est absent."""
    v = _lire(body, cle, None)
    if v is _ABSENT:
        return None
    if not isinstance(v, list) or not (1 <= len(v) <= groupes_max):
        raise EntreeInvalide(_L("err.entree.groupes", champ=cle))
    sortie = []
    for g in v:
        if not isinstance(g, list) or len(g) != nb_roues:
            raise EntreeInvalide(_L("err.entree.groupes", champ=cle))
        ligne = []
        for a in g:
            if a is None or a == "":
                ligne.append(None)
            elif isinstance(a, str) and len(a.strip()) <= 40:
                ligne.append(a.strip() or None)
            else:
                raise EntreeInvalide(_L("err.entree.groupes", champ=cle))
        sortie.append(ligne)
    return sortie
