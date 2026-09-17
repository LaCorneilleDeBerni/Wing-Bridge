"""Jeton d'API — partagé par le serveur (wing_ui / wing_handler) et
l'assistant clavier (wing_keyboard_macos / wing_keyboard_windows).

POURQUOI (audit du 25/09/2026). Le serveur HTTP n'écoute que sur 127.0.0.1 et
refuse les requêtes dont l'en-tête `Origin` ou `Host` trahit un autre site.
Mais une requête SANS `Origin` (tout programme local hors navigateur) était
acceptée sans condition : `curl -X POST …/api/uninstall` suffisait, depuis
n'importe quel compte de la machine, et l'assistant clavier — qui détient
l'autorisation Accessibilité — tapait dans MA3 tout ce qu'on mettait dans sa
file. Désormais tout POST et `GET /api/keystrokes` exigent ce jeton.

COMMENT ON L'OBTIENT :
  • l'onglet du navigateur : injecté dans la page servie (`<meta
    name="wing-jeton">`, voir wing_handler._get_page) ;
  • l'assistant clavier : lu dans un fichier du dossier de l'utilisateur,
    écrit en permissions 0600 au démarrage du serveur.

⚠️ LIMITE ASSUMÉE (choix de l'auteur, 25/09/2026) : la page servie contient
le jeton, pour que taper l'adresse à la main dans un navigateur continue de
marcher en régie. Un programme local qui télécharge D'ABORD la page obtient
donc le jeton. Le jeton arrête les requêtes aveugles (script générique,
outil qui tente l'API sans la connaître), pas une attaque écrite pour cette
app. Un programme qui tourne sous le MÊME compte peut de toute façon lire le
fichier 0600 : ce compte est la frontière de confiance, pas le jeton.
→ docs/ETAT_PROJET.md, correction 6 de l'audit.

Contrôle test_jeton_api (smoke_securite.py).
"""

import os
import secrets
import sys
from pathlib import Path

EN_TETE = "X-Wing-Jeton"      # en-tête HTTP qui porte le jeton
PARAM = "jeton"               # repli en paramètre d'URL : `navigator.sendBeacon`
                              # ne sait pas poser d'en-tête


def nouveau_jeton() -> str:
    """Un jeton neuf, imprévisible (256 bits)."""
    return secrets.token_urlsafe(32)


def chemin_jeton() -> Path:
    """Où le serveur dépose le jeton pour l'assistant clavier.

    ⚠️ Un emplacement FIXE par utilisateur, indépendant du mode de lancement du
    serveur : l'assistant est un programme à part, qui ne sait pas où le
    serveur range ses profils. On prend le dossier où l'assistant écrit déjà
    son propre journal (macOS : ~/Library/Application Support/Wing Bridge ;
    Windows : %LOCALAPPDATA%\\Wing Bridge) — la désinstallation le balaie déjà.
    `WING_JETON_FICHIER` le déplace (tests).
    """
    force = os.environ.get("WING_JETON_FICHIER")
    if force:
        return Path(force)
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")))
        return base / "Wing Bridge" / "api_jeton"
    if sys.platform == "darwin":
        return (Path.home() / "Library" / "Application Support"
                / "Wing Bridge" / "api_jeton")
    return Path.home() / ".local" / "share" / "wing-bridge" / "api_jeton"


def ecrire_jeton(jeton: str, chemin: Path = None) -> Path:
    """Écrit le jeton, lisible par le SEUL utilisateur courant (0600).

    Le fichier temporaire est CRÉÉ en 0600 (`os.open` + mode) : un `write_text`
    suivi d'un `chmod` laisserait un instant le jeton lisible par tous.
    Remplacement atomique ensuite, comme partout dans le projet.
    ⚠️ Windows : le mode POSIX y est ignoré ; c'est l'ACL par défaut de
    %LOCALAPPDATA% (réservé à l'utilisateur) qui protège le fichier.
    """
    chemin = Path(chemin or chemin_jeton())
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".part")
    try:
        tmp.unlink()
    except FileNotFoundError:
        pass
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, jeton.encode("ascii"))
    finally:
        os.close(fd)
    os.replace(str(tmp), str(chemin))
    return chemin


def lire_jeton(chemin: Path = None) -> str:
    """Le jeton courant, ou "" s'il n'est pas (encore) lisible."""
    try:
        return Path(chemin or chemin_jeton()).read_text(encoding="ascii").strip()
    except (OSError, UnicodeDecodeError):
        return ""


def ouvrir(url: str, jeton: str, data: bytes = None, timeout: float = 2):
    """`urllib.request.urlopen` avec le jeton joint — pour l'assistant clavier.

    Lève comme `urlopen`. Sur `urllib.error.HTTPError` 403, l'appelant relit
    le jeton (`lire_jeton()`) : l'app a été relancée et en a publié un neuf.
    """
    import urllib.request
    req = urllib.request.Request(url, data=data, headers={EN_TETE: jeton})
    return urllib.request.urlopen(req, timeout=timeout)
