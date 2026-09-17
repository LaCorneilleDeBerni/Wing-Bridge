#!/bin/zsh
# Build SERVEUR SEUL — reconstruit uniquement le moteur (wing_server) et
# remplace Contents/Resources/app/. NE TOUCHE PAS à Wing Keyboard.app, donc
# l'autorisation Accessibilité du helper reste valide (pas de nouveau cdhash).
#
# À utiliser pour TOUTE modif hors wing_keyboard.py (UI, faders, DMX, LEDs…).
# Pour une modif du helper clavier lui-même → utiliser build_app.sh.
#
# Usage : ./build_server.sh  [--no-bump]  [--with-firmware]  [chemin de l'app]
#
#   --no-bump : ne PAS incrémenter le numéro de build. Aligné sur le -SkipBump
#   de build_windows.ps1 — lit BUILD tel quel dans wing_version.py et NE
#   réécrit PAS le fichier. Sert à recouper une release déjà numérotée par
#   l'autre plateforme, ou à rebuilder un correctif de la même plateforme, en
#   restant au même numéro sans salir l'arbre git.
#
#   --with-firmware : EMBARQUER wing_firmware.bin dans le bundle (build PRIVÉ).
#   Par défaut (build OSS), le firmware appartient à MA Lighting et n'est PAS
#   embarqué — l'utilisateur importe le sien (Paramètres → Configurer le
#   firmware). Ce drapeau sert aux builds privés qui ont déjà le .bin à côté
#   des sources.
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
# App CANONIQUE : « Wing Bridge Officiel/ », à côté des sources. Il n'y en a
# qu'UNE, et c'est SON assistant clavier qui détient l'autorisation
# Accessibilité — le CDHash est lié au binaire, donc une copie faite après coup
# ne serait pas autorisée. Ne pas en garder de second exemplaire.
#
# 🐛 Ce défaut a visé « ${SRC:h}/Wing Bridge.app », un bundle qui
# dormait là, périmé du 1er août : un build lancé sans argument allait donc
# dans l'app que PERSONNE ne lançait, pendant que la vraie restait en retard.
# Chemin RELATIF aux sources exprès — l'app a déjà déménagé une fois dans la
# journée, un chemin absolu redeviendrait faux au prochain déplacement.
APP="${1:-${SRC:h}/Wing Bridge Officiel/Wing Bridge.app}"
DEST="$APP/Contents/Resources/app"
source "$SRC/build_env.sh"   # définit PY, PYI, ARCH_FLAGS + generer_coquille_app

# Coquille .app absente (clone frais) → la fabriquer ; puis forcer le bundle ID
# public. Les deux fonctions sont définies dans build_env.sh.
#
# ⚠️ build_server.sh ne reconstruit PAS l'assistant clavier : sur un clone frais
# où la coquille vient d'être générée, « Wing Bridge Officiel/Wing Bridge.app »
# n'aura donc PAS de Wing Keyboard.app. Le mode console (frappes clavier) sera
# indisponible jusqu'à un ./build_app.sh. Pour un premier build complet, lancer
# build_app.sh.
generer_coquille_app "$APP" "$SRC"
forcer_bundle_id_public "$APP"
forcer_lsuielement "$APP"

if [[ ! -d "$APP/Contents" ]]; then
  echo "✗ App introuvable : $APP"; exit 1
fi

# Voir build_app.sh : on préfère la libusb universelle de vendor/.
LIBUSB="$SRC/vendor/libusb-1.0.0.dylib"
if [[ ! -f "$LIBUSB" ]]; then
  LIBUSB=$(readlink -f /opt/homebrew/lib/libusb-1.0.0.dylib 2>/dev/null || true)
  echo "⚠️  vendor/libusb-1.0.0.dylib absent → repli sur Homebrew"
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
echo "→ Build serveur seul (wing_server) — build #$BUILD…"
echo "  (l'assistant clavier n'est PAS reconstruit : il gardera son numéro"
echo "   précédent, c'est normal et visible dans l'interface)"
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
    echo "✗ Échec build — log :"; tail -20 "$TMP/pyinstaller.log"; exit 1
  }

echo "→ Remplacement du moteur (Wing Keyboard.app préservé)…"
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
# (repli français assuré côté client), mais le sélecteur ne basculerait rien —
# c'est un défaut de build, on bloque.
for _f in locales/fr.json locales/en.json; do
  if ! find "$DEST" -path "*/$_f" -print -quit | grep -q .; then
    echo "✗ $_f absent du bundle — le bilingue serait cassé (interface figée en français)."
    echo "  Vérifie la ligne --add-data \"\$SRC/locales:locales\" de ce script."
    exit 1
  fi
done

# Fichiers du plugin grandMA3 : l'auto-installation (Paramètres → Firmware →
# « Installer automatiquement ») les copie dans le pool de MA3. Absents du
# bundle, le bouton échoue proprement mais l'utilisateur ne peut plus installer
# le plugin qu'à la main.
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
rm -rf "$TMP"

# Signature ad-hoc de TOUT le bundle, EN DERNIER : on vient de remplacer le
# moteur (Contents/Resources/app/), donc la coquille et son scellé doivent être
# refaits. Défini dans build_env.sh. ⚠️ signer_app_adhoc NE re-signe PAS
# Wing Keyboard.app tant que sa signature est valide → cdhash inchangé →
# autorisation Accessibilité préservée. Un échec de vérification annule le build.
signer_app_adhoc "$APP"

touch "$APP"
echo "✓ Serveur reconstruit (build #$BUILD) : $APP"
echo "  (Wing Keyboard.app intact → autorisation Accessibilité préservée)"
