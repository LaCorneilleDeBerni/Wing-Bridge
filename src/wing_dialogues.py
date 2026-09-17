"""Sélecteurs de fichiers NATIFS (macOS : osascript ; Windows : WinForms via PowerShell).

Sorti de `wing_handler.py` (audit du 25/09/2026, point D3) : ouvrir une
boîte de dialogue du système n'est pas le métier d'un Handler HTTP.
"""

import os
import subprocess
import sys


# ══ SÉLECTEUR DE FICHIER NATIF, MULTIPLATEFORME ════════════════════════════
#
# 🔑 Un `<input type="file">` du navigateur ne peut PAS choisir son dossier de
# départ ni renvoyer un chemin disque au serveur, et pour une capture de
# plusieurs Mo on veut lire le fichier CÔTÉ SERVEUR, pas le remonter en base64.
# On passe donc par le sélecteur natif de l'OS, comme `_post_profile_parcourir`
# le fait déjà sous macOS (osascript). Ici, les deux plateformes.
#
# Retour : le chemin choisi, "" si l'utilisateur ANNULE (ce n'est pas une
# erreur), ou None si le sélecteur lui-même est indisponible.
def choisir_fichier(prompt, dossier="", exts=None, enregistrer=False,
                     nom_defaut=""):
    exts = exts or []
    if sys.platform == "darwin":
        # ⚠️ Pas de filtre d'extension : macOS attend des UTI, pas des
        #    extensions, et un mauvais filtre GRISE tout (vécu sur les
        #    profils). Le contenu est validé ensuite, de toute façon.
        if enregistrer:
            nom = nom_defaut or "wing_firmware.bin"
            script = (f'POSIX path of (choose file name with prompt "{prompt}" '
                      f'default name "{nom}"'
                      + (f' default location POSIX file "{dossier}"'
                         if dossier else "")
                      + ')')
        else:
            script = ('POSIX path of (choose file with prompt '
                      f'"{prompt}"'
                      + (f' default location POSIX file "{dossier}"'
                         if dossier else "")
                      + ')')
        cmd = ["osascript", "-e", script]
    elif sys.platform.startswith("win"):
        if exts:
            motifs = ";".join(f"*.{e}" for e in exts)
            filtre = (f"Fichiers pris en charge ({motifs})|{motifs}"
                      f"|Tous les fichiers (*.*)|*.*")
        else:
            filtre = "Tous les fichiers (*.*)|*.*"
        boite = "SaveFileDialog" if enregistrer else "OpenFileDialog"
        # WinForms exige un thread STA → -STA. Le chemin ressort tel quel sur
        # la sortie standard, sans saut de ligne parasite (Console.Out.Write).
        ps = ["Add-Type -AssemblyName System.Windows.Forms | Out-Null",
              f"$d = New-Object System.Windows.Forms.{boite}",
              f"$d.Filter = '{filtre}'"]
        if dossier:
            ps.append(f"$d.InitialDirectory = '{dossier}'")
        if enregistrer and nom_defaut:
            ps.append(f"$d.FileName = '{nom_defaut}'")
        ps.append("if ($d.ShowDialog() -eq "
                  "[System.Windows.Forms.DialogResult]::OK) "
                  "{ [Console]::Out.Write($d.FileName) }")
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", "; ".join(ps)]
    else:
        return None                      # plateforme sans sélecteur natif câblé
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    except Exception:
        return None
    return r.stdout.strip()
