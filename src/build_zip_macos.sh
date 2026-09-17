#!/bin/zsh
# Fabrique le zip macOS distribuable À PARTIR de « Wing Bridge Officiel/Wing
# Bridge.app » ET vérifie le round-trip complet : la signature ad-hoc de la
# coquille doit SURVIVRE à la compression puis à l'extraction, sinon l'asset ne
# vaut rien (macOS récent bloque l'ouverture sans recours « Ouvrir quand même »).
#
# À lancer APRÈS ./build_app.sh (ou ./build_server.sh) : ces scripts signent le
# bundle en fin de course. Ce script-ci ne build rien, il empaquette et contrôle.
#
# ⚠️ Comme signer_app_adhoc (build_env.sh) : on travaille sur une COPIE sur
# disque local (/var/folders, hors FileProvider). Le dépôt vit sous
# ~/Documents/… synchronisé, où macOS re-colle `com.apple.FinderInfo` sur les
# dossiers de framework — `codesign --verify --strict` sur l'app EN PLACE
# échouerait à tort. La signature (dans Contents/_CodeSignature/) est intacte ;
# c'est seulement le détritus d'attribut étendu qu'il faut purger avant de
# zipper, et il ne revient pas sur disque local.
#
# Usage : ./build_zip_macos.sh  [chemin de l'app]  [chemin du zip]
set -e

SRC="${0:A:h}"
source "$SRC/build_env.sh"   # _wb_purge_detritus
APP="${1:-${SRC:h}/Wing Bridge Officiel/Wing Bridge.app}"
ZIP="${2:-$HOME/WingBridge-macOS-universal.zip}"

[[ -d "$APP/Contents" ]] || { echo "✗ App introuvable : $APP"; exit 1; }

# ── 1. Copie de travail sur disque local + purge du détritus ────────────────
STAGEDIR="$(mktemp -d)"
trap 'rm -rf "$STAGEDIR"' EXIT
STAGE="$STAGEDIR/Wing Bridge.app"
echo "→ Copie de travail (disque local) + purge des attributs étendus…"
ditto "$APP" "$STAGE"
_wb_purge_detritus "$STAGE"

echo "→ Vérification de la signature (sur la copie purgée)…"
if ! codesign --verify --deep --strict "$STAGE" 2>/tmp/wb_zip_src.$$; then
  echo "✗ L'app n'est pas signée correctement — relance ./build_app.sh d'abord :"
  cat /tmp/wb_zip_src.$$; rm -f /tmp/wb_zip_src.$$
  exit 1
fi
rm -f /tmp/wb_zip_src.$$
codesign -dv "$STAGE" 2>&1 | grep -E 'Signature=|Identifier=' | sed 's/^/  /'

# ── 2. Compression ─────────────────────────────────────────────────────────
# --norsrc --noextattr : pas de forks de ressources, pas d'attributs étendus →
# aucun fichier « ._* » parasite, aucune métadonnée de quarantaine transportée.
# VÉRIFIÉ (round-trip ci-dessous) : la signature ad-hoc de la coquille — dans
# Contents/_CodeSignature/, pas dans un xattr — survit à ces deux options. Si un
# jour ce n'était plus le cas, l'étape 3 échouerait bruyamment.
echo "→ Compression : $ZIP"
rm -f "$ZIP"
ditto -c -k --keepParent --norsrc --noextattr "$STAGE" "$ZIP"

# ── 3. Round-trip : extraire dans un dossier neuf et TOUT re-vérifier ───────
EXDIR="$STAGEDIR/extrait"
mkdir -p "$EXDIR"
echo "→ Extraction de contrôle…"
ditto -x -k "$ZIP" "$EXDIR"
EX="$EXDIR/Wing Bridge.app"
[[ -d "$EX/Contents" ]] || { echo "✗ Le zip ne contient pas « Wing Bridge.app » à la racine."; exit 1; }

fail=0

echo "→ [1/5] Signature après extraction (codesign --verify --deep --strict)…"
if codesign --verify --deep --strict "$EX" 2>/tmp/wb_zip_ex.$$; then
  codesign -dv "$EX" 2>&1 | grep -E 'Signature=' | sed 's/^/    /'
  echo "    OK — la signature ad-hoc a survécu au zip"
else
  echo "    ✗ signature CASSÉE après extraction :"
  sed 's/^/      /' /tmp/wb_zip_ex.$$
  fail=1
fi
rm -f /tmp/wb_zip_ex.$$

echo "→ [2/5] Aucun fichier « ._* » parasite…"
n=$(find "$EX" -name '._*' | wc -l | tr -d ' ')
if [[ "$n" == "0" ]]; then echo "    OK"; else echo "    ✗ $n fichiers « ._* » trouvés"; fail=1; fi

echo "→ [3/5] Firmware NON embarqué (propriété MA Lighting)…"
if find "$EX" -name 'wing_firmware.bin' | grep -q .; then
  echo "    ✗ wing_firmware.bin présent dans le zip !"; fail=1
else echo "    OK"; fi

echo "→ [4/5] Aucune fuite de nom personnel…"
# ⚠️ Les motifs à chercher NE SONT PAS écrits ici en clair (audit du
# 27/09/2026) : un script suivi par le dépôt public qui épèle le nom qu'il
# protège serait lui-même la fuite. Ils viennent de WING_NOMS_PRIVES, une
# variable d'environnement définie localement (jamais dans le dépôt) —
# ex. `export WING_NOMS_PRIVES='prenom|nom'` dans le profil shell de la
# machine de build. Sans elle, ce contrôle est sauté proprement plutôt que
# d'échouer ou de ne rien vérifier en silence.
if [[ -z "${WING_NOMS_PRIVES:-}" ]]; then
  echo "    ⚠️  WING_NOMS_PRIVES non définie — contrôle sauté (voir commentaire)"
else
  hits=$(grep -rlIE "$WING_NOMS_PRIVES" "$EX" 2>/dev/null || true)
  if [[ -n "$hits" ]]; then echo "    ✗ occurrences trouvées :"; echo "$hits" | sed 's/^/      /'; fail=1
  else echo "    OK"; fi
fi

echo "→ [5/5] Moteur universel (x86_64 + arm64)…"
MOTEUR="$EX/Contents/Resources/app/wing_server"
arch=$(lipo -info "$MOTEUR" 2>/dev/null || echo "")
if echo "$arch" | grep -q 'x86_64' && echo "$arch" | grep -q 'arm64'; then
  echo "    OK — ${arch#*are: }"
else
  echo "    ✗ moteur pas universel : $arch"; fail=1
fi

echo
if (( fail )); then
  echo "✗ ZIP REFUSÉ — un contrôle du round-trip a échoué. $ZIP laissé en place pour inspection."
  exit 1
fi

SHA=$(shasum -a 256 "$ZIP" | awk '{print $1}')
SIZE=$(du -h "$ZIP" | awk '{print $1}')
echo "✓ Zip macOS prêt : $ZIP"
echo "  Taille : $SIZE"
echo "  sha256 : $SHA"
