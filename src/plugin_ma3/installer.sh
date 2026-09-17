#!/bin/bash
# Copie le plugin Wing Bridge dans le dossier des plugins de grandMA3.
#
# La source de vérité reste ce dossier de projet ; MA3 n'en reçoit qu'une
# copie. Après chaque modification du .lua, relancer ce script PUIS taper
#   ReloadAllPlugins
# dans la ligne de commande de MA3 — le code est rechargé sans réimporter.
# (Documenté dans plugins.html : « useful when Lua files are edited and copied
# into the folder using an external editor ».)
set -e

SRC="$(cd "$(dirname "$0")" && pwd)"
DEST="$HOME/MALightingTechnology/gma3_library/datapools/plugins"

if [[ ! -d "$DEST" ]]; then
  echo "✗ Dossier des plugins MA3 introuvable :"
  echo "  $DEST"
  echo "  grandMA3 est-il installé pour cet utilisateur ?"
  exit 1
fi

# Contrôle de syntaxe avant de livrer quoi que ce soit à MA3 : une faute ne se
# verrait sinon qu'au moment de lancer le plugin, dans la console.
if command -v luac >/dev/null 2>&1; then
  for f in "$SRC"/*.lua; do luac -p "$f"; done
  echo "✓ syntaxe Lua valide"
else
  echo "• luac absent — contrôle de syntaxe sauté"
fi

# Liste EXPLICITE (pas de glob) : seuls les 4 fichiers de PRODUCTION vont dans
# le pool de plugins de MA3. verif_encodeur.lua (banc d'essai de l'encodeur JSON,
# lancé par le test de fumée) reste dans le dépôt mais n'a rien à faire dans MA3.
FICHIERS=(wingbridge.lua wingbridge.xml wingloader.lua wingloader.xml)
for f in "${FICHIERS[@]}"; do
  cp "$SRC/$f" "$DEST/"
done
echo "✓ plugin copié dans $DEST"
ls -l "${FICHIERS[@]/#/$DEST/}"
echo ""
echo "Dans grandMA3 — INSTALLATION EN 3 COMMANDES (aucune manip souris) :"
echo "  Emplacement (slot) 3 ci-dessous = le defaut de l'app. Si ce slot est"
echo "  deja pris par un autre plugin chez toi, remplace le \"3\" par un slot"
echo "  libre dans les 3 commandes (coherent avec Parametres -> grandMA3 ->"
echo "  Emplacement du plugin si tu passes aussi par l'app -- verifie ton"
echo "  reglage)."
echo "  Import Plugin Library \"wingloader.xml\" At 3"
echo "  Set Plugin 3.1 Property \"Installed\" \"Yes\""
echo "  Plugin 3        (bascule marche/arret de la sonde)"
echo "  puis ENREGISTRER LE SHOW."
echo ""
echo "  L'amorce relit wingbridge.lua a chaque appel : une nouvelle version"
echo "  prend effet au prochain 'Plugin 3', sans ReloadAllPlugins ni re-import."
echo "  Ces commandes passent aussi en OSC (/cmd), donc a distance."
echo ""
echo "Ancienne methode, par la fenetre d'import :"
echo "  • 1re fois  : Edit Plugin 1  →  bouton Import  →  WingBridge"
echo "                vérifier Installed = Yes et Source = Library"
echo "                (sinon : Set Plugin 1.1 Property \"Installed\" \"Yes\")"
echo "                ⚠️ PUIS ENREGISTRER LE SHOW. L'emplacement du plugin dans"
echo "                le pool fait partie du showfile : sans sauvegarde, il"
echo "                disparaît au redémarrage de MA3 (« illegal object:"
echo "                Plugin 1 ») — le .lua sur disque, lui, reste."
echo "  • ensuite   : ReloadAllPlugins   (après chaque modification du .lua)"
echo "                ⚠️ ne remplace PAS toujours le code déjà chargé : si le"
echo "                message de démarrage n'affiche pas la bonne version,"
echo "                redémarrer MA3."
echo "  • lancer    : Plugin 1           (relancer = arrêter)"
