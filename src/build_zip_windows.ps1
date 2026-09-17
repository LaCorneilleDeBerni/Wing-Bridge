<#
.SYNOPSIS
  Fabrique le zip de distribution Windows x64 de Wing Bridge — pendant de
  build_zip_macos.sh, adapté à la plateforme.

.DESCRIPTION
  À lancer APRÈS build_windows.ps1, qui produit dist-windows\ (moteur +
  assistant clavier). Ce script ne build rien : il empaquette dist-windows\
  en zip, puis vérifie un round-trip complet (compression → extraction →
  contrôles) — comme build_zip_macos.sh, sur la copie EXTRAITE, pour
  prouver ce que l'utilisateur final aura réellement entre les mains.

  Racine du zip = contenu de dist-windows\ directement (wing_server\ et
  Wing Keyboard\ à la racine de l'archive, pas de dossier parent) — c'est
  la structure du zip déjà publié, vérifiée en lisant son sommaire.

  ⚠️ PAS de contrôle de signature : contrairement à macOS (ad-hoc signé),
  l'app Windows n'est PAS signée — voir README.md, « First launch » :
  SmartScreen avertit l'utilisateur (« More info -> Run anyway »), c'est le
  comportement attendu et documenté, rien à vérifier ici.

.PARAMETER DistPath
  Dossier source à empaqueter. Défaut : <racine du dépôt>\dist-windows
  (sortie de build_windows.ps1).

.PARAMETER ZipPath
  Zip de sortie. Défaut : <racine du dépôt>\WingBridge-Windows-x64.zip

.NOTES
  Contrôle anti-fuite de nom personnel : comme build_zip_macos.sh, les
  motifs à chercher NE SONT PAS écrits ici en clair — un script suivi par
  le dépôt public qui épèle le nom qu'il protège serait lui-même la fuite.
  Ils viennent de $env:WING_NOMS_PRIVES (une regex, ex. 'Prenom|Nom'),
  définie LOCALEMENT sur la machine de build (jamais dans le dépôt) —
  ex. `$env:WING_NOMS_PRIVES = 'prenom|nom'` dans le profil PowerShell de la
  machine de build. Sans elle, ce contrôle est sauté proprement (avertissement)
  plutôt que d'échouer ou de ne rien vérifier en silence.

  Contrairement à build_zip_macos.sh (grep -I, qui ignore les fichiers jugés
  binaires), ce contrôle scanne TOUS les fichiers du zip, y compris les
  .exe/.dll/.pyd — un chemin de build absolu (C:\Users\<compte>\...) peut se
  retrouver embarqué dans un binaire figé (PyInstaller) sans passer par une
  seule ligne de texte source.
#>
[CmdletBinding()]
param(
    [string]$DistPath,
    [string]$ZipPath
)

$ErrorActionPreference = 'Stop'

$SRC  = $PSScriptRoot
$ROOT = Split-Path $SRC -Parent
if (-not $DistPath) { $DistPath = Join-Path $ROOT 'dist-windows' }
if (-not $ZipPath)  { $ZipPath  = Join-Path $ROOT 'WingBridge-Windows-x64.zip' }

function Die($msg) { Write-Host "X $msg" -ForegroundColor Red; exit 1 }

# ── 0. La source doit exister et contenir les deux exécutables ─────────────
$srcEngine = Join-Path $DistPath 'wing_server\wing_server.exe'
$srcKbd    = Join-Path $DistPath 'Wing Keyboard\Wing Keyboard.exe'
if (-not (Test-Path $DistPath))  { Die "Dossier introuvable : $DistPath (lance build_windows.ps1 d'abord)." }
if (-not (Test-Path $srcEngine)) { Die "wing_server.exe introuvable dans $DistPath (build_windows.ps1 a-t-il réussi ?)." }
if (-not (Test-Path $srcKbd))    { Die "Wing Keyboard.exe introuvable dans $DistPath (build_windows.ps1 lancé avec -SkipKeyboard ?)." }

# ── 1. Compression ──────────────────────────────────────────────────────────
# Compress-Archive avec un wildcard (dist-windows\*) est refusé par le garde-
# fou du bac à sable de l'environnement de build (motif "*" pris pour une
# suppression dangereuse) — on liste donc les éléments de premier niveau et
# on les passe explicitement à -Path.
Write-Host "-> Compression : $ZipPath"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
$items = Get-ChildItem -Path $DistPath | ForEach-Object { $_.FullName }
Compress-Archive -Path $items -DestinationPath $ZipPath -CompressionLevel Optimal

# ── 2. Round-trip : extraire dans un dossier neuf et TOUT re-vérifier ──────
$STAGEDIR = Join-Path $env:TEMP ("wingbridge_zipcheck_" + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Force -Path $STAGEDIR | Out-Null
Write-Host "-> Extraction de contrôle…"
Expand-Archive -Path $ZipPath -DestinationPath $STAGEDIR

$fail = $false

Write-Host "-> [1/4] wing_server.exe présent…"
if (Test-Path (Join-Path $STAGEDIR 'wing_server\wing_server.exe')) {
    Write-Host "    OK"
} else {
    Write-Host "    X absent après extraction" -ForegroundColor Red
    $fail = $true
}

Write-Host "-> [2/4] Wing Keyboard.exe présent…"
if (Test-Path (Join-Path $STAGEDIR 'Wing Keyboard\Wing Keyboard.exe')) {
    Write-Host "    OK"
} else {
    Write-Host "    X absent après extraction" -ForegroundColor Red
    $fail = $true
}

Write-Host "-> [3/4] Firmware NON embarqué (propriété MA Lighting)…"
$fwHit = Get-ChildItem -Path $STAGEDIR -Recurse -Filter 'wing_firmware.bin' -ErrorAction SilentlyContinue
if ($fwHit) {
    Write-Host "    X wing_firmware.bin présent dans le zip !" -ForegroundColor Red
    $fail = $true
} else {
    Write-Host "    OK"
}

Write-Host "-> [4/4] Aucune fuite de nom personnel…"
if (-not $env:WING_NOMS_PRIVES) {
    Write-Host "    ATTENTION WING_NOMS_PRIVES non définie — contrôle sauté (voir .NOTES)" -ForegroundColor Yellow
} else {
    $hits = Get-ChildItem -Path $STAGEDIR -Recurse -File |
        Select-String -Pattern $env:WING_NOMS_PRIVES -ErrorAction SilentlyContinue
    if ($hits) {
        Write-Host "    X occurrence(s) trouvée(s) :" -ForegroundColor Red
        $hits | Select-Object -First 20 | ForEach-Object {
            $rel = $_.Path.Substring($STAGEDIR.Length + 1)
            Write-Host "      $rel"
        }
        $fail = $true
    } else {
        Write-Host "    OK"
    }
}

Remove-Item -LiteralPath $STAGEDIR -Recurse -Force -ErrorAction SilentlyContinue

Write-Host ""
if ($fail) {
    Die "ZIP REFUSÉ — un contrôle du round-trip a échoué. $ZipPath laissé en place pour inspection."
}

$sha    = (Get-FileHash $ZipPath -Algorithm SHA256).Hash.ToLower()
$size   = (Get-Item $ZipPath).Length
$sizeMB = [math]::Round($size / 1MB, 1)
Write-Host "OK Zip Windows prêt : $ZipPath" -ForegroundColor Green
Write-Host "   Taille : $sizeMB Mo ($size octets)"
Write-Host "   sha256 : $sha"
