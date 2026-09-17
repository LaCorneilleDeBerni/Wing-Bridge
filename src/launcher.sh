#!/bin/zsh
# Wing Bridge — lanceur .app 100 % AUTONOME
# Le moteur (Python figé + libusb + firmware) est dans Contents/Resources/app/.
# Aucune dépendance externe : fonctionne sur tout Mac Apple Silicon.

SELF="${0:A}"                              # .../Wing Bridge.app/Contents/MacOS/launcher
RES="${SELF:h:h}/Resources"
APP_DIR="$RES/app"                         # moteur serveur embarqué
BIN="$APP_DIR/wing_server"
KBDAPP="$RES/Wing Keyboard.app"            # assistant clavier (vraie .app)
DATA_DIR="$HOME/Library/Application Support/Wing Bridge"
URL="http://127.0.0.1:8765"
LOGF="$DATA_DIR/wing_bridge.log"

# Démarre l'assistant clavier EN UTILISATEUR via `open` (jamais root — sinon
# macOS bloque l'injection clavier). `open` donne à l'app une identité de
# bundle propre → demande d'autorisation Accessibilité fiable. L'assistant
# poll le serveur ; tant que le mode console est off, il ne tape rien.
start_keyboard() {
  if [[ -d "$KBDAPP" ]] && ! pgrep -f "Wing Keyboard" > /dev/null 2>&1; then
    open "$KBDAPP" 2>/dev/null
  fi
}

# ── Qui décide d'ouvrir le navigateur ? LE MOTEUR, pas ce script ──────────────
# Ce launcher ne fait plus AUCUN `open "$URL"`. Le binaire wing_server gère
# l'ouverture dans les trois cas de lancement :
#   • serveur déjà là + onglet ouvert  → il ne fait rien (pas de 2ᵉ onglet) ;
#   • serveur déjà là sans onglet       → il rouvre le navigateur ;
#   • rien en écoute                    → il démarre puis ouvre le navigateur
#     (y compris en repli admin : lancé en root, il détourne par la session
#      graphique de l'utilisateur — voir wing_ui._ouvrir_url).
# Un seul point de décision, identique quel que soit le navigateur (Safari,
# Firefox…) et sans dépendre d'un mode --app.
start_server() {
  WING_PROFILE_DIR="$DATA_DIR/profiles" "$BIN" >> "$LOGF" 2>&1 < /dev/null &
}

start_server_admin() {
  # NB : pas de nohup — sans terminal il échoue ("can't detach from console").
  # stdin sur /dev/null + sorties vers le log suffisent à détacher le process.
# NB : ce fichier ($LOGF) reste VIDE — vérifié, la sortie standard
# du binaire figé n'y arrive pas, même avec PYTHONUNBUFFERED=1 (testé : 0 octet
# y compris en lisant PENDANT l'exécution, donc ce n'est pas du tamponnage).
# Cause exacte non identifiée. On ne compte donc PAS sur stdout : le vrai
# journal est écrit par l'app elle-même dans wing_server.log, et les exceptions
# non rattrapées y sont capturées explicitement (voir install_crash_logging()
# dans wing_ui.py). La redirection est conservée : elle ne coûte rien et
# attraperait une erreur du bootloader avant même le démarrage de Python.
  osascript -e "do shell script \"WING_PROFILE_DIR='$DATA_DIR/profiles' '$BIN' >> '$LOGF' 2>&1 < /dev/null & echo started\" with administrator privileges with prompt \"Wing Bridge a besoin des droits administrateur pour accéder à la wing en USB.\""
}

# Attend que le serveur réponde. $1 = nombre de demi-secondes, $2 = pid à
# surveiller (facultatif). Si ce pid meurt, inutile d'attendre la fin du délai.
# Le 1er lancement après un build est LENT (macOS revérifie la signature du
# binaire) : un délai trop court faisait basculer à tort sur le mode admin.
attendre_serveur() {
  local max="$1" pid="$2"
  for i in $(seq "$max"); do
    if curl -s -m 1 "$URL/api/instance" > /dev/null 2>&1; then
      return 0
    fi
    if [[ -n "$pid" ]] && ! kill -0 "$pid" 2>/dev/null; then
      return 2          # le process est mort : ne pas attendre pour rien
    fi
    sleep 0.5
  done
  return 1
}

# Dossier des profils (côté utilisateur, survit aux mises à jour de l'app)
mkdir -p "$DATA_DIR/profiles"

# Serveur déjà en écoute → on lance quand même le binaire : il sonde
# /api/instance, rouvre l'onglet s'il avait été fermé, sinon ressort aussitôt.
# On NE touche PAS au repli admin dans ce cas (le serveur qui tourne va bien).
#
# 🐛 CORRIGÉ (27/09/2026) : ce test tapait sur /api/status, PAS /api/instance
# — or /api/status est le battement de cœur de l'onglet (`_get_status` pose
# `UI_VIE["dernier_ping"]` à CHAQUE appel, sans exception). Chaque relance de
# l'app rafraîchissait donc elle-même le ping juste avant que le nouveau
# process ne demande « un onglet est-il ouvert ? » — la réponse était
# TOUJOURS oui, même onglet fermé depuis longtemps, et le navigateur ne se
# rouvrait jamais. `/api/instance` ne touche à rien (voir son commentaire
# dans wing_handler.py) : c'est la bonne route pour une simple sonde de
# présence.
if curl -s -m 1 "$URL/api/instance" > /dev/null 2>&1; then
  start_keyboard
  start_server
  exit 0
fi

# Vérifier le moteur embarqué
if [[ ! -x "$BIN" ]]; then
  osascript -e "display alert \"Wing Bridge\" message \"Moteur introuvable dans le bundle :\n$BIN\nRe-builde l'app avec build_app.sh.\" as critical"
  exit 1
fi

# ── Démarrage du serveur ─────────────────────────────────────────────────────
# VÉRIFIÉ : le root n'est PAS nécessaire pour la wing. Testé
# étape par étape en utilisateur normal (uid 501) — énumération, ouverture,
# set_configuration, claim_interface et écriture réelle passent tous ; seul
# detach_kernel_driver échoue, avec ENOENT (« aucun pilote noyau attaché »),
# ce qui n'est PAS une erreur de permission et que le code ignore déjà.
# Puis full_init() COMPLET (upload firmware + reboot + re-énumération +
# handshake) exécuté en utilisateur : succès intégral.
#
# On démarre donc SANS mot de passe. Bénéfice secondaire : plus aucun fichier
# créé en root dans le dossier de l'utilisateur.
#
# Repli conservé : si le serveur non privilégié ne répond pas, on retente AVEC
# les droits admin. Une machine ou une wing qui se comporterait autrement doit
# pouvoir fonctionner quand même — la fiabilité prime.

# 1er essai : SANS privilèges (cas normal)
start_server
SRV_PID=$!
attendre_serveur 90 "$SRV_PID"        # jusqu'à 45 s
case $? in
  0) start_keyboard; exit 0 ;;
esac

# Le serveur non privilégié n'a pas abouti. Le repli admin ne corrige QUE les
# problèmes de droits — les autres causes (port occupé, binaire cassé) sont
# visibles dans wing_server.log, que l'utilisateur peut envoyer.
pkill -f "$BIN" 2>/dev/null
sleep 1
start_server_admin || exit 1
if attendre_serveur 90; then
  start_keyboard
  exit 0
fi

osascript -e "display alert \"Wing Bridge\" message \"Le serveur n'a pas démarré, même avec les droits administrateur.\n\nRegarde le journal :\n$DATA_DIR/wing_server.log\" as critical"
exit 1
