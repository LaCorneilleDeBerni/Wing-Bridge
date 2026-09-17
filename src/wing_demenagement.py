"""Garde des noms DÉMÉNAGÉS d'un module vers un autre.

POURQUOI (audit du 25/09/2026, point D3). Découper un gros module déplace des
noms que le test de fumée remplace (« monkeypatch ») : `wi.ETAT_FICHIER =
dossier_jetable`, `wi.blocage_connu = lambda: False`… Après le déplacement,
une telle affectation RÉUSSIT quand même — elle crée juste un attribut que
plus personne ne lit. Le test croit avoir redirigé le fichier d'état matériel
et écrit dans le VRAI ; il croit avoir neutralisé un verrou et teste autre
chose. Une régression silencieuse, exactement ce que ce projet chasse.

`garder(module, {nom: "module_cible"})` fait LEVER toute lecture ou écriture
d'un nom déménagé, avec l'adresse où le trouver désormais.
Contrôle test_handler_mince.
"""

import sys
import types


def garder(nom_module: str, demenages: dict, motif: str = "D3"):
    """Pose la garde sur le module `nom_module` (déjà dans sys.modules).
    `demenages` : {nom: nouvelle adresse lisible, ex. "etat.E.STATE"}."""
    module = sys.modules[nom_module]

    class _ModuleGarde(types.ModuleType):
        def __setattr__(self, nom, valeur):
            if nom in demenages:
                raise AttributeError(_message(nom_module, nom, demenages[nom], motif))
            super().__setattr__(nom, valeur)

        def __getattr__(self, nom):
            if nom in demenages:
                raise AttributeError(_message(nom_module, nom, demenages[nom], motif))
            raise AttributeError(f"module '{nom_module}' has no attribute '{nom}'")

    module.__class__ = _ModuleGarde


def _message(source, nom, cible, motif):
    return (f"{source}.{nom} a déménagé : utiliser {cible} "
            f"(audit du 25/09/2026, {motif})")
