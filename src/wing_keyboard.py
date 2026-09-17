#!/usr/bin/env python3
"""
wing_keyboard.py — sélecteur de plateforme de l'assistant clavier
==================================================================
L'assistant clavier consomme la file de frappes (`/api/keystrokes`) et les
injecte dans grandMA3. La LOGIQUE D'ENVOI de la frappe est spécifique à l'OS
et vit dans un module par plateforme, choisi ICI à l'exécution via
`sys.platform` :

  • macOS   → `wing_keyboard_macos.py`   — CGEvent/Quartz (`CGEventPostToPid`),
              autorisation Accessibilité. **Code inchangé** : c'est l'ancien
              contenu de ce fichier, déplacé tel quel.
  • Windows → `wing_keyboard_windows.py` — `SendInput` (vrais événements
              clavier) avec vol de focus MINIMAL : MA3 est amené au premier
              plan le temps d'injecter, puis le focus est rendu. ⚠️ Écart
              ASSUMÉ vs macOS : en ShCuts ON (le mode réel de la wing), MA3 ne
              réagit qu'au vrai clavier ET seulement s'il a le focus — mesuré ;
              PostMessage (sans focus) ne marche qu'en mode texte (ShCuts OFF),
              pas en usage réel. Voir l'en-tête de `wing_keyboard_windows.py`.

⚠️ Découpage par plateforme. Le comportement macOS est
IDENTIQUE à avant : tout le code macOS a été copié VERBATIM dans
`wing_keyboard_macos.py` (seul l'ancien bloc `if __name__ == "__main__"` y est
devenu la fonction `cli()`). **Seul le chemin Windows est nouveau.**

Le nom de fichier reste « wing_keyboard.py » à dessein : c'est le point
d'entrée attendu par le build (`build_app.sh` → PyInstaller) et le module
importé par `smoke_test.py`. Le `import *` ci-dessous ré-exporte l'API du
backend (`build_layout_map`, `resolve_spec`, `LAYOUT`, `type_items`…) pour que
`import wing_keyboard` fonctionne identiquement des deux côtés.

⚠️ Ne PAS ajouter de logique métier ici : ce fichier ne fait que router. Toute
la mécanique d'envoi appartient au module de la plateforme.
"""

import sys

if sys.platform == "darwin":
    # Ré-export de l'API macOS (Quartz importé transitivement par ce module).
    from wing_keyboard_macos import *        # noqa: F401,F403
    from wing_keyboard_macos import main, cli
elif sys.platform.startswith("win"):
    from wing_keyboard_windows import *      # noqa: F401,F403
    from wing_keyboard_windows import main, cli
else:
    def cli():
        print(f"wing_keyboard : plateforme non supportée ({sys.platform}). "
              "macOS et Windows uniquement.")
        sys.exit(1)


if __name__ == "__main__":
    cli()
