#!/bin/zsh
# Incrémente le numéro de build chronologique et régénère wing_version.py.
# Appelé par build_app.sh ET build_server.sh — un build = un numéro, jamais
# remis à zéro, jamais réutilisé. Sert à se repérer entre machines/versions
# (« tu es en build N, moi en N+3 » → on sait qui a quoi).
#
# Le compteur est stocké DANS wing_version.py : pas de second fichier à
# synchroniser, et le numéro voyage avec le code embarqué par PyInstaller.
#
# Usage : ./bump_build.sh <dossier source>   → affiche le nouveau numéro
set -e

SRC="${1:-${0:A:h}}"
VERF="$SRC/wing_version.py"

CUR=$(sed -n 's/^BUILD = \([0-9]*\).*/\1/p' "$VERF" 2>/dev/null || true)
[[ -z "$CUR" ]] && CUR=0
NEXT=$((CUR + 1))

cat > "$VERF" <<EOF
# ⚠️ GÉNÉRÉ AUTOMATIQUEMENT par bump_build.sh — NE PAS ÉDITER À LA MAIN.
# Numéro de build chronologique, incrémenté à chaque build (serveur ou complet).
# Le moteur et l'assistant clavier embarquent chacun le numéro du build qui les
# a produits : s'ils diffèrent dans l'interface, c'est qu'un build serveur seul
# a eu lieu depuis (normal), ou qu'un bundle a été mélangé (à surveiller).
BUILD = $NEXT
BUILD_DATE = "$(date '+%d/%m/%Y %H:%M')"
EOF

echo "$NEXT"
