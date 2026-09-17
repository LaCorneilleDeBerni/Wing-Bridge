# USBPcap vendoré

Installeur officiel **USBPcap 1.5.4.0** (desowin/usbpcap), figé ici pour
la capture intégrée du firmware (`src/wing_firmware_capture.py`, Windows
uniquement). Voir `docs/WINDOWS.md`, section « Capture firmware
intégrée », pour le contexte.

| | |
|---|---|
| **Fichier** | `USBPcapSetup-1.5.4.0.exe` |
| **Version épinglée** | `1.5.4.0` (dernière release à ce jour, 22/05/2020) |
| **Source** | https://github.com/desowin/usbpcap/releases/tag/1.5.4.0 |
| **Taille** | 195 040 o |
| **sha256** | `87a7edf9bbbcf07b5f4373d9a192a6770d2ff3add7aa1e276e82e38582ccb622` |

`build_windows.ps1` **revérifie ce sha256 avant chaque build** — si le fichier
diffère (mise à jour manuelle sans mise à jour de l'empreinte, ou altération),
le build s'arrête au lieu d'embarquer un binaire non vérifié.

## Pour mettre à jour la version épinglée

1. Télécharger le nouvel installeur depuis une release GitHub **officielle**
   de `desowin/usbpcap` (jamais depuis un miroir tiers).
2. `Get-FileHash <exe> -Algorithm SHA256` → reporter la nouvelle empreinte
   ici **et** dans `build_windows.ps1`.
3. Remplacer `USBPcapSetup-1.5.4.0.exe`, renommer selon la nouvelle version,
   mettre à jour toutes les références (ce fichier, `build_windows.ps1`,
   `wing_firmware_capture.py`).

## Licences (⚠️ pas GPLv3 — vérifié dans le README du dépôt source)

USBPcap n'est **pas** un projet mono-licence : le pilote et l'outil en ligne
de commande sont sous deux licences différentes (source :
`README` du dépôt `desowin/usbpcap`, tag `1.5.4.0`) :

| Composant | Licence | Fichier ici |
|---|---|---|
| **USBPcapDriver** (le pilote noyau, installé par le setup) | **GPLv2** | `LICENSE-USBPcapDriver-GPLv2.txt` |
| **USBPcapCMD** (l'outil de capture en ligne de commande, piloté par `wing_firmware_capture.py`) | **BSD 2-Clause** | `LICENSE-USBPcapCMD-BSD-2-Clause.txt` |

Le binaire vendoré ici (`USBPcapSetup-1.5.4.0.exe`) est redistribué **tel
quel**, non modifié, tel que publié par l'auteur (Tomasz Mon) sur la release
GitHub officielle — aucune source de ce composant n'est compilée par ce
projet. Voir `THIRD_PARTY.md` à la racine pour le résumé global des
composants tiers du projet.
