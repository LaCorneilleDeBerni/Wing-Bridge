#!/usr/bin/env python3
"""
generer_capture_exemple.py — fabrique une capture pcapng SYNTHÉTIQUE pour les tests
==================================================================================
⚠️ DONNÉES SYNTHÉTIQUES POUR TEST — AUCUN firmware de MA Lighting ici.

Ce script produit `capture_exemple.pcapng` : une capture USBPcap synthétique qui
imite la séquence d'upload de firmware (Hello → réponse bootloader → 68 morceaux
→ End packet), mais dont la charge « firmware » est un MOTIF FABRIQUÉ connu
(`firmware_exemple()`), PAS le firmware propriétaire. Elle sert uniquement à
prouver que `wing_firmware_extract.extract_from_pcapng()` ressort exactement les
octets attendus, sans jamais avoir besoin du vrai blob.

Le fichier `capture_exemple.pcapng` est committé à côté ; ce script permet de le
régénérer à l'identique (motif déterministe) si besoin :

    python generer_capture_exemple.py
"""

import struct
import sys
from pathlib import Path

# Le module d'extraction est dans src/ (le parent de fixtures/).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import wing_firmware_extract as fwx   # noqa: E402

DEVICE = 7          # adresse device arbitraire de la « wing » d'exemple
CHUNK = 512


def firmware_exemple() -> bytes:
    """34 624 o d'un motif déterministe — CLAIREMENT PAS le firmware de MA.

    Commence par une bannière ASCII lisible (« FAKE-WING-FIRMWARE… ») pour que,
    même ouvert dans un éditeur hexa, il soit évident que ce n'est pas un binaire
    ARM réel, puis un remplissage déterministe reproductible.
    """
    banniere = b"FAKE-WING-FIRMWARE-NOT-MA-LIGHTING-TEST-DATA-"
    corps = bytearray(banniere)
    i = 0
    while len(corps) < fwx.FIRMWARE_LONGUEUR:
        corps.append((i * 37 + 11) & 0xFF)
        i += 1
    return bytes(corps[:fwx.FIRMWARE_LONGUEUR])


# ── Construction des enregistrements USBPcap et des blocs pcapng ───────────────
def _usbpcap(device, endpoint, depuis_device, data) -> bytes:
    """Un enregistrement USBPcap : pseudo-en-tête fixe (27 o) + données."""
    header_len = 27
    info = 1 if depuis_device else 0
    return (struct.pack("<H", header_len)      # headerLen
            + struct.pack("<Q", 0)             # irpId
            + struct.pack("<I", 0)             # status
            + struct.pack("<H", 0)             # function
            + struct.pack("<B", info)          # info (bit0 = venant du device)
            + struct.pack("<H", 1)             # bus
            + struct.pack("<H", device)        # device
            + struct.pack("<B", endpoint)      # endpoint
            + struct.pack("<B", 3)             # transfer = bulk
            + struct.pack("<I", len(data))     # dataLength
            + data)


def _pad4(b: bytes) -> bytes:
    return b + b"\x00" * (-len(b) % 4)


def _bloc(btype: int, corps: bytes) -> bytes:
    """Un bloc pcapng générique : type, longueur, corps (padé), longueur."""
    corps = _pad4(corps)
    total = 12 + len(corps)
    return (struct.pack("<I", btype) + struct.pack("<I", total)
            + corps + struct.pack("<I", total))


def _shb() -> bytes:
    corps = (struct.pack("<I", 0x1A2B3C4D)     # byte-order magic
             + struct.pack("<H", 1) + struct.pack("<H", 0)   # version 1.0
             + struct.pack("<q", -1))          # section length inconnue
    return _bloc(0x0A0D0D0A, corps)


def _idb() -> bytes:
    corps = (struct.pack("<H", fwx.LINKTYPE_USBPCAP)         # linktype 249
             + struct.pack("<H", 0)            # reserved
             + struct.pack("<I", 0))           # snaplen (0 = illimité)
    return _bloc(0x00000001, corps)


def _epb(data: bytes, ts: int) -> bytes:
    corps = (struct.pack("<I", 0)              # interface id
             + struct.pack("<I", ts >> 32)     # timestamp high
             + struct.pack("<I", ts & 0xFFFFFFFF)   # timestamp low
             + struct.pack("<I", len(data))    # captured length
             + struct.pack("<I", len(data))    # original length
             + _pad4(data))
    return _bloc(0x00000006, corps)


def construire() -> bytes:
    fw = firmware_exemple()
    paquets = []
    # Hello host → wing, réponse bootloader wing → host.
    paquets.append(_usbpcap(DEVICE, fwx.EP_OUT, False, fwx.HELLO_PKT))
    paquets.append(_usbpcap(DEVICE, fwx.EP_IN, True, fwx.HELLO_REP_BOOT))
    # 68 morceaux : 67 × 512 o + 1 × 320 o.
    for off in range(0, len(fw), CHUNK):
        paquets.append(_usbpcap(DEVICE, fwx.EP_OUT, False, fw[off:off + CHUNK]))
    # End packet.
    paquets.append(_usbpcap(DEVICE, fwx.EP_OUT, False, fwx.FW_END_PKT))

    out = _shb() + _idb()
    for i, p in enumerate(paquets):
        out += _epb(p, ts=i)
    return out


def main():
    dest = Path(__file__).resolve().parent / "capture_exemple.pcapng"
    dest.write_bytes(construire())
    # Contrôle immédiat : on doit ressortir EXACTEMENT le motif fabriqué.
    got = fwx.extract_from_pcapng(str(dest))
    assert got == firmware_exemple(), "l'extraction ne rend pas le motif d'exemple"
    print(f"✓ {dest.name} écrit ({dest.stat().st_size} o) — extraction vérifiée "
          f"({len(got)} o d'exemple).")


if __name__ == "__main__":
    main()
