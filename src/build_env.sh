#!/bin/zsh
# Choix de l'environnement de build — SOURCÉ par build_app.sh et build_server.sh.
# Définit : PY, PYI, ARCH_FLAGS, ARCH_LABEL
#
# On PRÉFÈRE ~/wing-env-universal (Python universal2 de python.org) : il produit
# une app qui tourne sur Mac Intel ET Apple Silicon, à partir de macOS 10.13.
# Repli sur ~/wing-env (Homebrew, arm64 seul, cible macOS 15) — le build
# fonctionne alors, mais le résultat ne démarrera PAS sur Intel.
#
# ⚠️ PIÈGE VÉRIFIÉ : passer --target-arch universal2 à PyInstaller
# avec un Python mono-architecture ne provoque AUCUNE erreur — il produit un
# lanceur « fat » avec un Python arm64 dedans, et l'app plante au lancement sur
# Intel. On ne passe donc l'option QUE si le Python est réellement universel,
# et le build final doit être validé en s'exécutant sous Rosetta, jamais sur la
# seule foi de `lipo -info`.

UNIVERSAL_ENV="$HOME/wing-env-universal"
FALLBACK_ENV="$HOME/wing-env"

if [[ -x "$UNIVERSAL_ENV/bin/python3" ]]; then
  BUILD_ENV="$UNIVERSAL_ENV"
elif [[ -x "$FALLBACK_ENV/bin/python3" ]]; then
  BUILD_ENV="$FALLBACK_ENV"
else
  echo "✗ Aucun environnement de build trouvé."
  echo "  Attendu : $UNIVERSAL_ENV (recommandé) ou $FALLBACK_ENV"
  exit 1
fi

PY="$BUILD_ENV/bin/python3"
PYI="$BUILD_ENV/bin/pyinstaller"
[[ -x "$PYI" ]] || { echo "✗ PyInstaller absent de $BUILD_ENV"; exit 1; }

# Le Python de cet environnement contient-il VRAIMENT les deux architectures ?
if lipo -info "$PY" 2>/dev/null | grep -q "x86_64.*arm64\|arm64.*x86_64"; then
  ARCH_FLAGS=(--target-arch universal2)
  ARCH_LABEL="universel (Intel + Apple Silicon)"
else
  ARCH_FLAGS=()
  ARCH_LABEL="$(uname -m) UNIQUEMENT — ne démarrera pas sur Mac Intel"
fi

echo "→ Environnement : ${BUILD_ENV/#$HOME/~}"
echo "→ Architecture  : $ARCH_LABEL"

# ── Coquille .app : la fabriquer si elle manque ──────────────────────────────
# La coquille (Info.plist + MacOS/launcher + Resources/icon.icns) était faite à
# la main et gitignorée (« Wing Bridge Officiel/ »). Résultat : un contributeur
# qui clone le dépôt ne pouvait pas builder l'app macOS — les deux scripts de
# build refusaient de démarrer (« ✗ App introuvable »). On la reconstruit ici à
# partir des fichiers du dépôt (src/wing_icon.icns, src/launcher.sh). Le reste
# du build (remplacement de Resources/app/ et Resources/Wing Keyboard.app/)
# fonctionne ensuite tel quel.
#
#   $1 = chemin du .app    $2 = dossier des sources (src/)
generer_coquille_app() {
  local app="$1" src="$2"
  [[ -d "$app/Contents" ]] && return 0
  echo "→ Coquille .app absente → génération depuis les sources : $app"
  [[ -f "$src/wing_icon.icns" ]] || { echo "✗ $src/wing_icon.icns introuvable — coquille impossible à générer."; exit 1; }
  [[ -f "$src/launcher.sh" ]]    || { echo "✗ $src/launcher.sh introuvable — coquille impossible à générer.";    exit 1; }
  mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
  cp "$src/wing_icon.icns" "$app/Contents/Resources/icon.icns"
  cp "$src/launcher.sh"    "$app/Contents/MacOS/launcher"
  chmod +x "$app/Contents/MacOS/launcher"
  cat > "$app/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key>            <string>Wing Bridge</string>
  <key>CFBundleDisplayName</key>     <string>Wing Bridge</string>
  <key>CFBundleIdentifier</key>      <string>com.lacorneilledeberni.wingbridge</string>
  <key>CFBundleVersion</key>         <string>1.0</string>
  <key>CFBundleShortVersionString</key> <string>1.0</string>
  <key>CFBundlePackageType</key>     <string>APPL</string>
  <key>CFBundleExecutable</key>      <string>launcher</string>
  <key>CFBundleIconFile</key>        <string>icon</string>
  <key>LSMinimumSystemVersion</key>  <string>11.0</string>
  <key>NSHighResolutionCapable</key> <true/>
  <key>LSUIElement</key>             <true/>
</dict>
</plist>
PLIST
  echo "✓ Coquille .app créée (Info.plist, MacOS/launcher, Resources/icon.icns)"
}

# Le bundle ID PUBLIC, forcé à chaque build : d'anciennes coquilles faites à la
# main portaient un identifiant qui citait un nom personnel — il ne doit rester
# nulle part. Sans effet si l'identifiant est déjà bon.
forcer_bundle_id_public() {
  local app="$1"
  plutil -replace CFBundleIdentifier -string "com.lacorneilledeberni.wingbridge" \
    "$app/Contents/Info.plist" >/dev/null 2>&1 || true
}

# 🐛 CORRIGÉ (27/09/2026) : l'icône Dock sautait sans arrêt au lancement,
# parfois pendant les 45 s d'attente du serveur (`attendre_serveur` dans
# launcher.sh). Cause confirmée (doc développeur Apple) : `launcher` est un
# script shell, pas une vraie app AppKit — il ne signale jamais à
# LaunchServices qu'il a « fini de démarrer », qui continue donc de faire
# rebondir l'icône tant que le processus reste en vie.
#
# `LSUIElement` dit à LaunchServices que cette app n'a justement PAS
# d'interface Dock à attendre : plus de rebond, et l'icône disparaît du Dock
# (l'interface reste dans le navigateur — rien n'y était affiché de toute
# façon). Forcé ici comme le bundle ID : une coquille ancienne, créée avant
# ce correctif, ne l'aurait pas sans cette étape.
forcer_lsuielement() {
  local app="$1"
  plutil -replace LSUIElement -bool true "$app/Contents/Info.plist" >/dev/null 2>&1 || true
}

# ── Purge des détritus interdits par codesign ────────────────────────────────
# `codesign` refuse un bundle qui porte `com.apple.FinderInfo` ou un fork de
# ressources (« resource fork, Finder information, or similar detritus not
# allowed »). `xattr -cr` NE SUFFIT PAS : il laisse `com.apple.FinderInfo` sur
# les DOSSIERS de framework (`Python.framework`) et sur leurs liens symboliques.
# Il faut le retrait ciblé, entrée par entrée, cible ET lien (`-s`).
#   $1 = racine à purger
_wb_purge_detritus() {
  local root="$1"
  find "$root" -name '._*' -delete 2>/dev/null || true
  find "$root" -print0 2>/dev/null | while IFS= read -r -d '' f; do
    xattr -d  com.apple.FinderInfo   "$f" 2>/dev/null || true
    xattr -sd com.apple.FinderInfo   "$f" 2>/dev/null || true
    xattr -d  com.apple.ResourceFork "$f" 2>/dev/null || true
  done
  return 0
}

# ── Signature ad-hoc du bundle (gratuite, sans compte développeur Apple) ──────
# La coquille .app (CFBundleExecutable = le script `launcher`) n'était signée
# NULLE PART — `spctl` : « no usable signature ». Seuls les binaires internes
# (wing_server, Wing Keyboard.app) recevaient une signature ad-hoc de
# PyInstaller. Sur macOS récent (26 compris), une .app non signée, à base de
# script et en quarantaine, est refusée SANS proposer « Ouvrir quand même » :
# l'utilisateur est bloqué net. Une signature ad-hoc (`codesign -s -`, ni
# compte ni notarisation) suffit à rétablir le parcours Réglages Système →
# Confidentialité et sécurité → « Ouvrir quand même ».
#
# ⚠️ Signature INSIDE-OUT, jamais `--deep` sur la coquille finale : on signe
# d'abord chaque binaire imbriqué, la coquille en DERNIER. `--deep` re-signerait
# les imbriqués au passage et a déjà cassé des scellés ailleurs.
#
# ⚠️ ON SIGNE DANS UNE COPIE SUR DISQUE LOCAL. Le dépôt vit sous
# ~/Documents/… (dossier géré par FileProvider — synchro iCloud) : macOS
# y RE-COLLE `com.apple.FinderInfo` sur les dossiers de framework en continu, et
# `codesign` REFUSE alors de signer. Dans /var/folders (hors FileProvider) la
# purge tient. On signe et on vérifie là, puis on repose le bundle signé en
# place. FileProvider peut re-coller un FinderInfo APRÈS coup sur les dossiers
# de framework : ça ne touche pas `Contents/_CodeSignature/`, la signature reste
# valide, et `build_zip_macos.sh` re-purge dans SA copie locale avant de zipper.
#
# ⚠️ L'assistant clavier n'est re-signé QUE si sa signature est réellement
# cassée : re-signer change son cdhash et fait retomber l'autorisation
# Accessibilité — exactement ce que build_server.sh s'attache à préserver.
#
#   $1 = chemin du .app
signer_app_adhoc() {
  local app="$1"
  echo "→ Signature ad-hoc du bundle (gratuite, sans compte développeur)…"

  # 1. Copie de travail sur disque local (hors FileProvider)
  local stagedir; stagedir="$(mktemp -d)"
  local stage="$stagedir/${app:t}"
  ditto "$app" "$stage"
  _wb_purge_detritus "$stage"

  # 2. Assistant clavier : re-signature SEULEMENT si nécessaire (voir ci-dessus)
  local kbd="$stage/Contents/Resources/Wing Keyboard.app"
  if [[ -d "$kbd" ]]; then
    if codesign --verify --strict "$kbd" 2>/dev/null; then
      echo "  · assistant clavier : signature déjà valide → intacte (Accessibilité préservée)"
    else
      echo "  · assistant clavier : signature absente/cassée → re-signature ad-hoc"
      [[ -f "$kbd/Contents/MacOS/Wing Keyboard" ]] && \
        { codesign --force -s - "$kbd/Contents/MacOS/Wing Keyboard" >/dev/null 2>&1 || true; }
      codesign --force -s - "$kbd"
    fi
  fi

  # 3. Moteur, puis coquille EN DERNIER
  [[ -f "$stage/Contents/Resources/app/wing_server" ]] && \
    codesign --force -s - "$stage/Contents/Resources/app/wing_server"
  codesign --force -s - "$stage"

  # 4. Vérification sur la copie locale : un échec ANNULE le build
  local _verr; _verr=$(mktemp)
  if ! codesign --verify --deep --strict "$stage" 2>"$_verr"; then
    echo "✗ BUILD ANNULÉ : signature ad-hoc invalide."
    cat "$_verr"; rm -f "$_verr"; rm -rf "$stagedir"
    exit 1
  fi
  rm -f "$_verr"

  # 5. Repose le bundle signé en place
  rm -rf "$app"
  ditto "$stage" "$app"
  rm -rf "$stagedir"

  # 6. Trace
  codesign -dv "$app" 2>&1 | grep -E 'Signature=|Identifier=' | sed 's/^/  /'
  echo "✓ Bundle signé ad-hoc — vérifié --deep --strict (copie disque local)"
}
