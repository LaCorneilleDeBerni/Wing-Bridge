<#
.SYNOPSIS
  Helper élevé du bouton de secours « Retirer le composant de capture ».

.DESCRIPTION
  Séparé de wing_firmware_capture_eleve.ps1 (qui installe ET capture) : ce
  script ne fait qu'UNE chose, désinstaller USBPcap, pour le cas où le
  nettoyage automatique en fin de capture a échoué (voir
  wing_firmware_capture.retirer_composant_capture()). Même mécanisme
  d'écriture de statut (JSON, atomique) que l'autre script, pour rester
  cohérent côté Python.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$StatusFile
)

$ErrorActionPreference = 'Stop'

# ⚠️ DÉCOUVERT EN RÉEL (test Windows du 26/09/2026) : ce script (élevé) écrit
# $StatusFile dans un dossier créé par Python NON élevé (tempfile.mkdtemp) —
# le fichier hérite d'un ACL qui refuse la LECTURE au process non élevé qui
# l'a pourtant créé et doit le relire (`_lire_status` → PermissionError
# systématique). Même piège, même remède que wing_firmware_capture_eleve.ps1
# (`icacls ... /grant "*<SID du propriétaire>:(OI)(CI)RX"`) : ce script n'a
# pas de paramètre `$WorkDir` dédié, donc on cible directement le dossier
# parent de `$StatusFile`.
try {
    $workDir = Split-Path -Path $StatusFile -Parent
    $lecteur = $null
    try {
        $lecteur = (Get-Acl -LiteralPath $workDir).GetOwner(
            [System.Security.Principal.SecurityIdentifier]).Value
    } catch { }
    if (-not $lecteur) {
        $lecteur = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
    }
    icacls $workDir /grant "*${lecteur}:(OI)(CI)RX" /T | Out-Null
} catch { }

function Find-UsbpcapDir {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
        if (-not $base) { continue }
        $cand = Join-Path $base 'USBPcap'
        if (Test-Path (Join-Path $cand 'USBPcapCMD.exe')) { return $cand }
    }
    return $null
}

function Write-Status {
    param([string]$Etape, [hashtable]$Extra = @{})
    $o = @{ etape = $Etape; termine = $false }
    foreach ($k in $Extra.Keys) { $o[$k] = $Extra[$k] }
    try {
        # ⚠️ PAS `Set-Content -Encoding UTF8` : pose un BOM sous PowerShell 5.1,
        # que Python lit en `utf-8` strict → JSONDecodeError (même piège corrigé
        # dans wing_firmware_capture_eleve.ps1, cf. docs/WINDOWS.md).
        $tmp = "$StatusFile.tmp"
        $json = $o | ConvertTo-Json -Compress -Depth 5
        [System.IO.File]::WriteAllText($tmp, $json, [System.Text.UTF8Encoding]::new($false))
        Move-Item -Force $tmp $StatusFile
    } catch { }
}

# Détacher USBPcap du filtre de classe + remonter les root hubs AVANT
# Uninstall.exe — sinon USBPcap.sys reste chargé (service bloqué jusqu'au
# reboot) et une wing branchée reste muette. Même logique que
# wing_firmware_capture_eleve.ps1 / Remove-UsbpcapClassFilter.
function Remove-UsbpcapClassFilter {
    $k = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{36FC9E60-C465-11CF-8056-444553540000}'
    try {
        $uf = (Get-ItemProperty -Path $k -Name UpperFilters -ErrorAction SilentlyContinue).UpperFilters
        if ($uf -contains 'USBPcap') {
            $n = @($uf | Where-Object { $_ -ne 'USBPcap' })
            if ($n.Count) { Set-ItemProperty -Path $k -Name UpperFilters -Value $n }
            else { Remove-ItemProperty -Path $k -Name UpperFilters }
        }
    } catch { }
    $ids = @()
    try {
        $ids = Get-PnpDevice -PresentOnly -Class USB -ErrorAction SilentlyContinue |
               Where-Object { $_.InstanceId -like 'USB\ROOT_HUB*' } |
               Select-Object -ExpandProperty InstanceId
    } catch { }
    foreach ($id in $ids) {
        $ok = $false
        try { & pnputil /restart-device "$id" 2>&1 | Out-Null; $ok = ($LASTEXITCODE -eq 0) } catch { $ok = $false }
        if (-not $ok) {
            try { Disable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction Stop }
            catch { } finally { try { Enable-PnpDevice -InstanceId $id -Confirm:$false -ErrorAction SilentlyContinue } catch { } }
        }
    }
}

# Même filet que wing_firmware_capture_eleve.ps1 : un Uninstall.exe qui
# n'en finit pas (boîte de dialogue imprévue) ne doit jamais pendre ce
# script pour de bon.
function Start-ProcessAvecTimeout {
    param([string]$FilePath, [string[]]$ArgumentList, [int]$TimeoutMs = 30000)
    $p = Start-Process -FilePath $FilePath -ArgumentList $ArgumentList -PassThru -WindowStyle Hidden
    if (-not $p.WaitForExit($TimeoutMs)) {
        try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch { }
        return $null
    }
    return $p
}

$uninstallOk  = $null
$uninstallErr = $null

try {
    $InstallDir = Find-UsbpcapDir
    if (-not $InstallDir) {
        Write-Status "USBPcap déjà absent — rien à retirer"
        $uninstallOk = $true
    } else {
        $UninstallExe = Join-Path $InstallDir 'Uninstall.exe'
        if (-not (Test-Path $UninstallExe)) {
            throw "Uninstall.exe introuvable dans $InstallDir"
        }
        Write-Status "détachement du composant de capture (remontage des hubs USB, ~2 s)…"
        Remove-UsbpcapClassFilter
        Start-Sleep -Seconds 1
        Write-Status "retrait de USBPcap…"
        $u = Start-ProcessAvecTimeout -FilePath $UninstallExe -ArgumentList @('/S') -TimeoutMs 30000
        if ($null -eq $u) {
            throw "Uninstall.exe ne s'est pas terminé en 30 s — bloqué sur une confirmation Windows non automatisable ?"
        }
        Start-Sleep -Seconds 1
        $CmdExe = Join-Path $InstallDir 'USBPcapCMD.exe'
        $uninstallOk = -not (Test-Path $CmdExe)
        if (-not $uninstallOk) {
            $uninstallErr = "USBPcapCMD.exe toujours présent après Uninstall.exe /S (code $($u.ExitCode))"
        }
        # Balayage final : dossier vide et USBPcap.sys (déchargé).
        # PendingFileRenameOperations n'est PAS touché — cf.
        # wing_firmware_capture_eleve.ps1, même endroit.
        try {
            # Attendre la fin de l'auto-suppression NSIS (Un_A.exe) avant de balayer.
            $fin = (Get-Date).AddSeconds(20)
            while ((Get-Date) -lt $fin) {
                $nsu = @(Get-CimInstance Win32_Process -Filter "Name='Un_A.exe'" -ErrorAction SilentlyContinue)
                if ($nsu.Count -eq 0) { break }
                Start-Sleep -Milliseconds 500
            }
            Start-Sleep -Seconds 1
            foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)})) {
                if (-not $base) { continue }
                $d = Join-Path $base 'USBPcap'
                for ($k = 0; $k -lt 3 -and (Test-Path $d); $k++) {
                    Remove-Item $d -Recurse -Force -ErrorAction SilentlyContinue
                    if (Test-Path $d) { Start-Sleep -Seconds 1 }
                }
            }
            $sys = Join-Path $env:windir 'System32\drivers\USBPcap.sys'
            if (Test-Path $sys) { Remove-Item $sys -Force -ErrorAction SilentlyContinue }
            # ⛔ PendingFileRenameOperations : on N'Y TOUCHE PLUS (audit du 25/09/2026).
            # Ce bloc réécrivait cette valeur système, lue par Windows au démarrage, pour
            # en retirer les paires USBPcap — alors que ces entrées ne font plus que
            # « supprimer un chemin déjà absent » au prochain boot : gain nul. Le risque,
            # lui, ne l'était pas : si PowerShell écartait les chaînes vides du
            # REG_MULTI_SZ (hypothèse jamais vérifiée), les paires [source, cible] se
            # décalaient et une suppression différée d'un AUTRE logiciel devenait un
            # renommage vers le mauvais chemin. Retiré purement et simplement ; ne pas
            # le remettre sans l'avoir mesuré sur une vraie machine Windows.
        } catch { }
    }
} catch {
    $uninstallOk = $false
    $uninstallErr = "$($_.Exception.Message)"
} finally {
    Write-Status "terminé" @{
        termine         = $true
        uninstall_ok    = $uninstallOk
        uninstall_error = $uninstallErr
    }
}
