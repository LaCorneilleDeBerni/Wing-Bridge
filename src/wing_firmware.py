"""Le firmware de la wing CÔTÉ FICHIERS : où il est, lequel on prend, s'il est
bon, et comment on en range une copie.

Sorti de `wing_init.py` (audit du 25/09/2026, point D3) : ce module-là
s'annonçait « CONNEXION seulement » et portait aussi toute la gestion des
fichiers firmware. `wing_init` garde le DIALOGUE avec la wing (Hello, envoi
par morceaux, poignée de main) et appelle ceci pour savoir QUOI envoyer.
"""

import os
import sys
from pathlib import Path

# En mode figé (PyInstaller), les ressources sont dans sys._MEIPASS — même
# règle que wing_init._DIR.
if getattr(sys, "frozen", False):
    _DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    _DIR = os.path.dirname(os.path.abspath(__file__))


# ── D'OÙ VIENT LE FIRMWARE, et dans quel ordre on le cherche ──────────────────
#
# 🔑 Le firmware applicatif appartient à MA Lighting : la distribution
# open-source ne le contient PAS (voir docs/HARDWARE.md, « D'où vient
# wing_firmware.bin »). Chaque utilisateur importe SA copie — extraite de sa
# capture (wing_firmware_extract.py) ou d'un .bin — qui atterrit dans le CACHE,
# à côté de ses profils (dossier de données utilisateur, inscriptible).
#
# Ordre de résolution (resoudre_firmware) :
#   1. le CACHE utilisateur (importé via l'écran « Configurer le firmware ») ;
#   2. le BLOB LIVRÉ à côté de l'exe — présent uniquement dans un build privé
#      (build_*.sh --with-firmware / build_windows.ps1 -WithFirmware). Absent du
#      build OSS par défaut ;
#   3. rien → l'app renvoie vers « Paramètres → Configurer le firmware ».
#
# Empreinte du firmware attendu : c'est une EMPREINTE, pas une œuvre — la mettre
# en clair ne redistribue rien. Source unique : wing_firmware_extract.
FW_BUNDLE = os.path.join(_DIR, "wing_firmware.bin")   # blob livré (build privé)

try:
    from wing_firmware_extract import FIRMWARE_LONGUEUR as FW_LONGUEUR, \
        FIRMWARE_SHA256 as FW_SHA256
except Exception:                       # extraction absente : valeurs de repli
    FW_LONGUEUR = 34624
    FW_SHA256 = ("86a19dfc6ab24450391610fa978f2d59"
                 "1f52792eeada06e0d5a32eeb41004454")


def chemin_cache_firmware() -> str:
    """Où l'utilisateur pose SON firmware — à côté de ses profils.

    Recalculé à chaque appel : `wing_mapper.PROFILE_DIR` peut être monkeypatché
    (test de fumée) ou dépendre du mode de lancement (sources / app figée).
    Import paresseux pour ne pas coupler wing_init à wing_mapper au chargement.
    """
    try:
        import wing_mapper
        base = wing_mapper.PROFILE_DIR.parent
    except Exception:
        base = Path(_DIR)               # repli : à côté du code (rare)
    return str(base / "wing_firmware.bin")


def resoudre_firmware():
    """Chemin du firmware à envoyer, ou None. Cache utilisateur → blob livré."""
    cache = chemin_cache_firmware()
    if os.path.exists(cache):
        return cache
    if os.path.exists(FW_BUNDLE):
        return FW_BUNDLE
    return None


def firmware_configure() -> bool:
    """Y a-t-il un firmware disponible (cache OU blob livré) ?"""
    return resoudre_firmware() is not None


# Cache de l'empreinte, pour ne pas relire+hacher 34 ko à chaque /api/status.
# Clé : (chemin, taille, mtime). Voir firmware_statut().
_FW_SHA_CACHE = {"cle": None, "sha": None}


def firmware_statut() -> dict:
    """État du firmware pour l'interface (/api/status → « firmware »)."""
    chemin = resoudre_firmware()
    if chemin is None:
        return {"configure": False, "source": None,
                "longueur": None, "sha256_ok": False}
    source = "cache" if chemin == chemin_cache_firmware() else "livré"
    try:
        st = os.stat(chemin)
        cle = (chemin, st.st_size, int(st.st_mtime))
        if _FW_SHA_CACHE["cle"] != cle:
            import hashlib
            with open(chemin, "rb") as f:
                _FW_SHA_CACHE["sha"] = hashlib.sha256(f.read()).hexdigest()
            _FW_SHA_CACHE["cle"] = cle
        sha = _FW_SHA_CACHE["sha"]
        return {"configure": True, "source": source,
                "longueur": st.st_size, "sha256_ok": (sha == FW_SHA256)}
    except OSError:
        return {"configure": False, "source": None,
                "longueur": None, "sha256_ok": False}


def enregistrer_firmware(blob) -> dict:
    """Écrit `blob` dans le cache APRÈS vérification. Rend un dict de résultat.

    ⚠️ Refuse un blob qui ne passe pas `verify` : on ne met JAMAIS en cache un
    firmware qui ne correspond pas à l'empreinte — mieux vaut « non configuré »
    qu'un firmware douteux envoyé à la wing.
    """
    import wing_i18n
    try:
        from wing_firmware_extract import verify
    except Exception as e:
        return {"ok": False,
                "raison": wing_i18n.L("err.module_extraction_absent", err=e)}
    ok_v, msg = verify(blob)
    if not ok_v:
        return {"ok": False, "raison": msg}
    dest = Path(chemin_cache_firmware())
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Écriture atomique : un .tmp puis un remplacement, pour ne jamais
        # laisser un cache à moitié écrit si l'app est coupée en plein import.
        tmp = dest.with_name(dest.name + ".tmp")
        tmp.write_bytes(blob)
        os.replace(str(tmp), str(dest))
    except OSError as e:
        return {"ok": False,
                "raison": wing_i18n.L("err.firmware.ecriture_cache_impossible", e=e)}
    # Filet du repli admin du launcher (sans effet quand le serveur n'est pas
    # root — le cas normal). Règle : toute écriture serveur
    # passe par own_like_parent.
    try:
        import wing_mapper
        wing_mapper.own_like_parent(dest)
    except Exception:
        pass
    _FW_SHA_CACHE["cle"] = None          # forcer un recalcul de l'empreinte
    import wing_init
    wing_init.DERNIER_ECHEC["firmware_absent"] = False
    return {"ok": True, "sha256": FW_SHA256, "longueur": len(blob),
            "source": "cache", "chemin": str(dest)}
