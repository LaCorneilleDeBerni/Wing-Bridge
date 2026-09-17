#!/bin/zsh
# Build de Wing Bridge.app — binaire AUTONOME (PyInstaller)
# L'app finale fonctionne sans Python ni venv installé.
#
# Architecture : décidée par build_env.sh, PAS ici. Avec ~/wing-env-universal
# le résultat est universel (Intel + Apple Silicon, macOS 11+) ; avec le repli
# ~/wing-env il ne tourne QUE sur cette machine. Le script l'affiche au
# démarrage — lire cette ligne avant de distribuer l'app.
#
# Prérequis (machine de build uniquement) :
#   ~/wing-env avec : pyusb, python-osc, pyinstaller
#   Homebrew libusb  (brew install libusb)
#
# Usage : ./build_app.sh  [--no-bump]  [--with-firmware]  [chemin de l'app]
#
#   --no-bump : ne PAS incrémenter le numéro de build. Aligné sur le -SkipBump
#   de build_windows.ps1 — lit BUILD tel quel dans wing_version.py et NE
#   réécrit PAS le fichier. Sert à recouper une release déjà numérotée par
#   l'autre plateforme, ou à rebuilder un correctif de la même plateforme, en
#   restant au même numéro sans salir l'arbre git.
#
#   --with-firmware : EMBARQUER wing_firmware.bin (build PRIVÉ). Par défaut
#   (build OSS), le firmware appartient à MA Lighting et n'est PAS embarqué —
#   l'utilisateur importe le sien (Paramètres → Configurer le firmware).
set -e

SRC="${0:A:h}"                          # dossier des sources (src/)

# Extrait --no-bump / --with-firmware ; le reste (chemin de l'app) garde sa place.
NO_BUMP=0
WITH_FW=0
_args=()
for _a in "$@"; do
  case "$_a" in
    --no-bump) NO_BUMP=1 ;;
    --with-firmware) WITH_FW=1 ;;
    *) _args+=("$_a") ;;
  esac
done
set -- "${_args[@]}"
# App CANONIQUE : « Wing Bridge Officiel/ », à côté des sources — voir la note
# détaillée dans build_server.sh. Chemin RELATIF : l'app peut être déplacée
# avec le projet sans casser les builds.
APP="${1:-${SRC:h}/Wing Bridge Officiel/Wing Bridge.app}"
DEST="$APP/Contents/Resources/app"
source "$SRC/build_env.sh"   # définit PY, PYI, ARCH_FLAGS + generer_coquille_app

# Coquille .app absente (clone frais) → la fabriquer ; puis forcer le bundle ID
# public. Les deux fonctions sont définies dans build_env.sh.
generer_coquille_app "$APP" "$SRC"
forcer_bundle_id_public "$APP"
forcer_lsuielement "$APP"

if [[ ! -d "$APP/Contents" ]]; then
  echo "✗ App introuvable : $APP"; exit 1
fi

# libusb : on PRÉFÈRE la version universelle de vendor/ (Intel + Apple
# Silicon, cible macOS 11). Celle de Homebrew ne contient QUE l'architecture
# de cette machine — une app buildée avec elle ne démarre pas sur Mac Intel.
# Repli sur Homebrew si vendor/ est absent, pour ne jamais bloquer un build.
LIBUSB="$SRC/vendor/libusb-1.0.0.dylib"
if [[ -f "$LIBUSB" ]]; then
  echo "→ libusb universelle : $(lipo -info "$LIBUSB" | sed 's/.*are: //')"
else
  LIBUSB=$(readlink -f /opt/homebrew/lib/libusb-1.0.0.dylib 2>/dev/null || true)
  echo "⚠️  vendor/libusb-1.0.0.dylib absent → repli sur Homebrew"
  echo "   (build limité à cette architecture — ./build_libusb_universal.sh"
  echo "    pour régénérer la version universelle)"
fi
if [[ -z "$LIBUSB" || ! -f "$LIBUSB" ]]; then
  echo "✗ libusb introuvable (./build_libusb_universal.sh, ou brew install libusb)"; exit 1
fi

# Garde-fou : un build ne part JAMAIS si le test de fumée échoue. Il coûte
# ~2 s et attrape les cassures silencieuses (JS mort = interface figée sans
# la moindre erreur en console).
echo "→ Test de fumée…"
if ! "$PY" "$SRC/smoke_test.py"; then
  echo ""
  echo "✗ BUILD ANNULÉ : le test de fumée a échoué (rien n'a été modifié)."
  exit 1
fi
echo ""

if (( NO_BUMP )); then
  BUILD=$(sed -n 's/^BUILD = \([0-9]*\).*/\1/p' "$SRC/wing_version.py")
  [[ -z "$BUILD" ]] && { echo "✗ Numéro de build illisible dans wing_version.py"; exit 1; }
  echo "→ build #$BUILD — numéro NON incrémenté (--no-bump), wing_version.py inchangé"
else
  BUILD=$("$SRC/bump_build.sh" "$SRC")
fi
echo "→ Build complet — build #$BUILD (moteur + assistant clavier)…"
TMP=$(mktemp -d)
# Firmware embarqué UNIQUEMENT sur demande (--with-firmware, build privé). Le
# build OSS par défaut ne l'inclut pas : l'utilisateur importe le sien.
FW_ARGS=()
if (( WITH_FW )); then
  if [[ -f "$SRC/wing_firmware.bin" ]]; then
    FW_ARGS=(--add-data "$SRC/wing_firmware.bin:.")
    echo "→ firmware EMBARQUÉ (build privé, --with-firmware)"
  else
    echo "✗ --with-firmware demandé mais $SRC/wing_firmware.bin est absent."; exit 1
  fi
else
  echo "→ firmware NON embarqué (build OSS) — l'utilisateur importe le sien"
fi
"$PYI" --noconfirm --onedir $ARCH_FLAGS --name wing_server \
  --distpath "$TMP/dist" --workpath "$TMP/build" --specpath "$TMP" \
  "${FW_ARGS[@]}" \
  --add-data "$SRC/wing_ui.html:." \
  --add-data "$SRC/ui:ui" \
  --add-data "$SRC/locales:locales" \
  --add-data "$SRC/plugin_ma3:plugin_ma3" \
  --add-binary "$LIBUSB:." \
  "$SRC/wing_ui.py" > "$TMP/pyinstaller.log" 2>&1 || {
    echo "✗ Échec build serveur — log :"; tail -20 "$TMP/pyinstaller.log"; exit 1
  }

echo "→ Build assistant clavier (Wing Keyboard.app, utilisateur)…"
# En VRAIE .app (--windowed) : macOS lui donne une identité de bundle propre,
# affiche une demande d'autorisation Accessibilité claire, et l'assistant
# apparaît proprement dans la liste. Indispensable pour que l'autorisation
# "prenne" de façon fiable (un binaire brut ne déclenche pas le prompt).
"$PYI" --noconfirm --onedir --windowed $ARCH_FLAGS --name "Wing Keyboard" \
  --osx-bundle-identifier com.wingbridge.keyboard \
  --hidden-import Quartz --hidden-import AppKit \
  --hidden-import ApplicationServices \
  --distpath "$TMP/dist" --workpath "$TMP/build2" --specpath "$TMP" \
  "$SRC/wing_keyboard.py" > "$TMP/pyinstaller2.log" 2>&1 || {
    echo "✗ Échec build assistant — log :"; tail -20 "$TMP/pyinstaller2.log"; exit 1
  }

KBDAPP="$TMP/dist/Wing Keyboard.app"
# Agent en arrière-plan : pas d'icône Dock, ne vole pas le focus.
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" \
  "$KBDAPP/Contents/Info.plist" 2>/dev/null \
  || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$KBDAPP/Contents/Info.plist"
# Signature ad-hoc (requise pour tourner + identité stable pour l'Accessibilité)
codesign --force --deep -s - --identifier com.wingbridge.keyboard "$KBDAPP" \
  > /dev/null 2>&1 || echo "  (codesign ad-hoc échoué — l'app tournera quand même)"

echo "→ Copie dans le bundle…"
rm -rf "$DEST"
mkdir -p "$DEST"
cp -R "$TMP/dist/wing_server/." "$DEST/"

# L'interface est un fichier embarqué : si PyInstaller ne
# l'a pas emporté, l'app démarre et ne sert AUCUNE page. On le vérifie ici
# plutôt que de le découvrir à l'ouverture du navigateur.
# ⚠️ LES DEUX fichiers, pas seulement le HTML. Le JavaScript vit dans ui/,
# un fichier par onglet : s'il en
# manque UN SEUL, l'app démarre,
# sert une page complète… et AUCUN bouton ne répond. Une panne muette.
# ⚠️ LE BALISAGE **ET** LES 7 FICHIERS JS. Le JavaScript vit dans ui/
# le JavaScript vit dans ui/, un fichier par onglet. Il en manque un seul et
# l'app démarre, sert une page complète… et AUCUN bouton ne répond. Une panne
# muette : ni erreur, ni journal, rien. D'où ce garde-fou.
for _f in wing_ui.html ui/core.js ui/i18n.js ui/aides.js ui/bridge.js ui/touches.js \
          ui/faders_encodeurs.js ui/profils.js ui/parametres.js ui/init.js; do
  if ! find "$DEST" -path "*/$_f" -print -quit | grep -q .; then
    echo "✗ $_f absent du bundle — l'interface serait inerte."
    echo "  Vérifie les lignes --add-data de ce script."
    exit 1
  fi
done

# Catalogues de langue (i18n) : une absence ne rend pas l'interface inerte
# (repli français assuré côté client), mais le sélecteur ne basculerait rien.
for _f in locales/fr.json locales/en.json; do
  if ! find "$DEST" -path "*/$_f" -print -quit | grep -q .; then
    echo "✗ $_f absent du bundle — le bilingue serait cassé (interface figée en français)."
    echo "  Vérifie la ligne --add-data \"\$SRC/locales:locales\" de ce script."
    exit 1
  fi
done

# Fichiers du plugin grandMA3 : l'auto-installation (Paramètres → Firmware →
# « Installer automatiquement ») les copie dans le pool de MA3.
for _f in plugin_ma3/wingbridge.lua plugin_ma3/wingbridge.xml \
          plugin_ma3/wingloader.lua plugin_ma3/wingloader.xml; do
  if ! find "$DEST" -path "*/$_f" -print -quit | grep -q .; then
    echo "✗ $_f absent du bundle — l'auto-installation du plugin serait cassée."
    echo "  Vérifie les lignes --add-data de ce script."
    exit 1
  fi
done


# PyInstaller collecte AUSSI la libusb de Homebrew (mono-architecture) en plus
# de celle qu'on lui donne — constaté : `libusb-1.0.dylib` en
# arm64 seul se retrouvait à côté de notre `libusb-1.0.0.dylib` universelle.
# Si l'app charge la mauvaise sur un Mac Intel, elle plante. On écrase donc
# TOUTE libusb du bundle par la version universelle.
if [[ -f "$SRC/vendor/libusb-1.0.0.dylib" ]]; then
  for f in "$DEST"/_internal/libusb*.dylib; do
    [[ -f "$f" ]] && cp "$SRC/vendor/libusb-1.0.0.dylib" "$f"
  done
fi
# Wing Keyboard.app rangée dans Resources du bundle principal
rm -rf "$APP/Contents/Resources/Wing Keyboard.app"
cp -R "$KBDAPP" "$APP/Contents/Resources/Wing Keyboard.app"
rm -rf "$TMP"

# Le launcher vit dans les SOURCES et est réinstallé à chaque build complet.
# Avant (≤ build 9) il n'existait QUE dans le .app déployé : perdre ce dossier
# faisait disparaître un fichier qu'aucun build ne savait régénérer.
if [[ -f "$SRC/launcher.sh" ]]; then
  cp "$SRC/launcher.sh" "$APP/Contents/MacOS/launcher"
  chmod +x "$APP/Contents/MacOS/launcher"
  echo "→ Launcher réinstallé depuis les sources"
else
  echo "⚠️  launcher.sh absent des sources — celui du bundle est conservé"
fi

# Signature ad-hoc de TOUT le bundle, EN DERNIER : la coquille .app n'est pas
# signée par PyInstaller, et sans elle macOS récent bloque l'ouverture sans
# recours. Défini dans build_env.sh. Un échec de vérification annule le build.
signer_app_adhoc "$APP"

touch "$APP"
echo "✓ App autonome buildée (build #$BUILD) : $APP"
du -sh "$DEST" | awk '{print "  Taille du moteur : " $1}'
