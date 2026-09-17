# Données synthétiques pour test — pas du firmware réel

⚠️ **Rien ici n'appartient à MA Lighting.** Ce dossier contient uniquement des
données fabriquées pour le test de fumée (`smoke_firmware.py`).

- **`capture_exemple.pcapng`** — une capture USBPcap fabriquée qui imite la
  séquence d'upload de firmware (Hello → réponse bootloader → 68 morceaux → End
  packet). Sa charge « firmware » est un **motif connu** (bannière ASCII
  `FAKE-WING-FIRMWARE-NOT-MA-LIGHTING-…` + remplissage déterministe), PAS le
  firmware propriétaire. Elle sert à prouver que
  `wing_firmware_extract.extract_from_pcapng()` ressort exactement les octets
  présents dans une capture — **sans jamais avoir besoin du vrai blob**.

- **`generer_capture_exemple.py`** — le générateur, pour régénérer le `.pcapng`
  à l'identique (motif déterministe) :

  ```
  python generer_capture_exemple.py
  ```

Le vrai firmware, lui, ne se trouve nulle part dans le dépôt public : chaque
utilisateur l'extrait de sa propre capture (voir `docs/HARDWARE.md`, section
« Obtenir le firmware »).
