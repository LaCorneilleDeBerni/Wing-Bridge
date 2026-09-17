#!/bin/zsh
# Recompile libusb en binaire UNIVERSEL (Intel + Apple Silicon).
#
# POURQUOI : la libusb de Homebrew ne contient QUE l'architecture de la machine
# (arm64 ici). Une app buildée avec elle ne démarre pas sur un Mac Intel. Celle
# produite ici contient les DEUX architectures et cible **macOS 11**, alors que
# le Python de Homebrew impose macOS 15 — ce qui exclurait la plupart des Mac
# Intel encore en service.
#
# Le résultat est VERSIONNÉ dans vendor/ : ce script n'a pas besoin d'être
# relancé à chaque build. Il existe pour que la bibliothèque soit
# reproductible, et pas un binaire tombé du ciel que personne ne sait refaire.
#
# Prérequis : Command Line Tools (clang, make) + accès réseau.
# Usage : ./build_libusb_universal.sh [version]
set -e

SRC="${0:A:h}"
VERSION="${1:-1.0.29}"
DEST="$SRC/vendor/libusb-1.0.0.dylib"
TMP=$(mktemp -d)

# macOS 11 = compromis : couvre les Mac Intel encore utilisés (Big Sur et
# au-delà) sans traîner de compatibilité inutile.
export MACOSX_DEPLOYMENT_TARGET=11.0

echo "→ Téléchargement de libusb $VERSION…"
curl -sL -o "$TMP/libusb.tar.bz2" \
  "https://github.com/libusb/libusb/releases/download/v$VERSION/libusb-$VERSION.tar.bz2"
tar xf "$TMP/libusb.tar.bz2" -C "$TMP"
cd "$TMP/libusb-$VERSION"

# On compile SÉPARÉMENT puis on fusionne avec lipo : autotools ne gère pas
# proprement une compilation bi-architecture en une passe.
for arch in arm64 x86_64; do
  echo "→ Compilation $arch…"
  mkdir -p "build-$arch" && cd "build-$arch"
  ../configure --host="${arch/arm64/aarch64}-apple-darwin" \
    --disable-udev --enable-shared --disable-static \
    CC="clang -arch $arch" > conf.log 2>&1 || { tail -20 conf.log; exit 1; }
  make -j4 > make.log 2>&1 || { tail -20 make.log; exit 1; }
  cd ..
done

echo "→ Fusion en binaire universel…"
mkdir -p "$SRC/vendor"
lipo -create "build-arm64/libusb/.libs/libusb-1.0.0.dylib" \
             "build-x86_64/libusb/.libs/libusb-1.0.0.dylib" \
     -output "$DEST"

# Retrait des infos de débogage : autotools compile en -g, et les chemins de
# build ABSOLUS (dont le dossier personnel de qui a lancé le script) se
# retrouvent en clair dans __debug_str. On les enlève — la bibliothèque
# distribuée ne doit rien révéler de la machine de build. `strip -S` retire les
# symboles de debug, `-x` les symboles locaux ; la signature ad-hoc est
# refaite ensuite (obligatoire, sinon la dylib ne se charge pas sur ARM).
strip -S -x "$DEST"
codesign --remove-signature "$DEST" 2>/dev/null || true
codesign -s - "$DEST"

rm -rf "$TMP"
echo "✓ $DEST"
lipo -info "$DEST"
for a in arm64 x86_64; do
  printf "  macOS minimum (%s) : " "$a"
  otool -l -arch $a "$DEST" | grep -A 3 LC_BUILD_VERSION | grep minos | awk '{print $2}'
done
