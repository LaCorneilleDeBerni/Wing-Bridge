#!/usr/bin/env python3
"""
wing_firmware_extract.py — reconstruire wing_firmware.bin depuis une capture USB
================================================================================
Le firmware applicatif de la wing appartient à MA Lighting : il ne peut pas être
redistribué avec ce projet (voir `docs/HARDWARE.md`, section « D'où vient
wing_firmware.bin »). Chaque utilisateur en extrait donc SA propre copie à partir
d'une capture Wireshark/USBPcap d'une session grandMA2 onPC poussant le firmware
à sa wing (procédure : `docs/HARDWARE.md`, section « Obtenir le firmware »).

Ce module fait ce travail SANS dépendance externe :
  • pas de tshark ni de Wireshark installé — on lit le fichier nous-mêmes ;
  • pas de pyshark/scapy — un parseur pcapng/pcap minimal est inclus ici ;
  • rien que la bibliothèque standard (struct, hashlib).

Format lu : LINKTYPE_USBPCAP (249), dans un conteneur **pcapng** (celui que
Wireshark enregistre) ou **pcap** classique (celui qu'écrit USBPcap en direct).
Le pseudo-en-tête USBPcap est documenté et de taille fixe — on le décode à la
main (voir `_decoder_usbpcap`).

⚠️ FIRMWARE_SHA256 est une EMPREINTE, pas une œuvre : la mettre en clair ici ne
redistribue rien. Elle sert à dire à l'utilisateur « oui, c'est le bon firmware »
au moment de l'import.

Usage CLI :
    python wing_firmware_extract.py capture.pcapng -o wing_firmware.bin
"""

import hashlib
import struct
import sys

# ── Ce qu'on cherche dans la capture (protocole, cf. docs/HARDWARE.md) ─────────
EP_OUT = 0x02          # bulk OUT : hôte → wing
EP_IN  = 0x81          # bulk IN  : wing → hôte

HELLO_PKT          = bytes.fromhex("0190040000000000")   # host → wing, EP 0x02
HELLO_REP_BOOT     = bytes.fromhex("0400079101000100")   # wing → host (bootloader)
FW_END_PKT         = bytes.fromhex("079004000000300000000000")  # borne de fin

# Longueur et empreinte du firmware attendu (67 × 512 o + 1 × 320 o).
FIRMWARE_LONGUEUR = 34624
FIRMWARE_SHA256 = "86a19dfc6ab24450391610fa978f2d591f52792eeada06e0d5a32eeb41004454"

# Link-layer type des captures USBPcap (cf. tcpdump/libpcap link-layer headers).
LINKTYPE_USBPCAP = 249


def _L(cle, **params):
    """Résout `cle` dans la langue courante — les messages `ExtractionError`
    et `verify()` remontent tels quels jusqu'à la `raison` JSON affichée dans
    l'UI (voir wing_handler._post_firmware_import_capture,
    wing_firmware.enregistrer_firmware)."""
    import wing_i18n
    return wing_i18n.L(cle, **params)


class ExtractionError(Exception):
    """Erreur d'extraction, avec un message ACTIONNABLE pour l'utilisateur.

    Toujours une phrase qui dit quoi faire (recapturer ? mauvaise interface ?),
    jamais une exception nue : c'est le point de contact avec quelqu'un qui n'a
    pas ce code sous les yeux.
    """


# ── Un transfert USB retenu de la capture ─────────────────────────────────────
class _PaquetUSB:
    __slots__ = ("device", "endpoint", "depuis_device", "data")

    def __init__(self, device, endpoint, depuis_device, data):
        self.device = device                 # adresse du périphérique sur le bus
        self.endpoint = endpoint             # 0x02 (OUT) / 0x81 (IN)
        self.depuis_device = depuis_device   # True = wing → hôte (IN complété)
        self.data = data                     # charge utile (sans le pseudo-en-tête)


# ── Décodage du pseudo-en-tête USBPcap ────────────────────────────────────────
#
# Structure USBPCAP_BUFFER_PACKET_HEADER, packée (alignement 1 octet),
# little-endian (cf. la doc USBPcap / le code de Wireshark) :
#
#   offset  taille  champ
#   0       2       headerLen   (longueur de CE pseudo-en-tête)
#   2       8       irpId
#   10      4       status
#   14      2       function
#   16      1       info        (bit 0 : 1 = PDO→FDO = venant du périphérique)
#   17      2       bus
#   19      2       device
#   21      1       endpoint    (bit 0x80 = IN)
#   22      1       transfer    (0 iso, 1 interrupt, 2 control, 3 bulk)
#   23      4       dataLength
#   -> les données commencent à `headerLen` (≥ 27 ; plus pour control/iso).
_USBPCAP_MIN = 27


def _decoder_usbpcap(buf):
    """buf = un enregistrement USBPcap (pseudo-en-tête + données). None si illisible."""
    if len(buf) < _USBPCAP_MIN:
        return None
    header_len = struct.unpack_from("<H", buf, 0)[0]
    if header_len < _USBPCAP_MIN or header_len > len(buf):
        return None
    info        = buf[16]
    device      = struct.unpack_from("<H", buf, 19)[0]
    endpoint    = buf[21]
    data_length = struct.unpack_from("<I", buf, 23)[0]
    data = buf[header_len:header_len + data_length]
    depuis_device = bool(info & 0x01)
    return _PaquetUSB(device, endpoint, depuis_device, data)


# ── Lecture du conteneur : pcapng d'abord, pcap classique en repli ────────────
def _lire_paquets(chemin):
    """Rend la liste ORDONNÉE des transferts USB (charge utile non vide).

    Accepte pcapng (Wireshark) et pcap classique (USBPcap brut). Lève
    ExtractionError avec un message clair si le fichier n'est ni l'un ni l'autre,
    ou n'est pas une capture USBPcap.
    """
    try:
        with open(chemin, "rb") as f:
            brut = f.read()
    except OSError as e:
        raise ExtractionError(_L("firmware.extract.capture_illisible", e=e))
    if len(brut) < 24:
        raise ExtractionError(_L("firmware.extract.fichier_trop_court"))

    magie = brut[:4]
    if magie == b"\x0a\x0d\x0d\x0a":
        return _lire_pcapng(brut)
    if magie in (b"\xd4\xc3\xb2\xa1", b"\xa1\xb2\xc3\xd4",
                 b"\x4d\x3c\xb2\xa1", b"\xa1\xb2\x3c\x4d"):
        return _lire_pcap(brut)
    raise ExtractionError(_L("firmware.extract.format_non_reconnu"))


def _lire_pcap(brut):
    """pcap classique (celui qu'écrit USBPcap directement)."""
    if brut[:4] in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1"):
        bo = "<"                         # little-endian
    else:
        bo = ">"                         # big-endian (rare, mais gratuit à gérer)
    network = struct.unpack_from(bo + "I", brut, 20)[0]
    if network != LINKTYPE_USBPCAP:
        raise ExtractionError(_L("firmware.extract.pas_usb",
                                 network=network, attendu=LINKTYPE_USBPCAP))
    paquets = []
    off = 24
    n = len(brut)
    while off + 16 <= n:
        incl = struct.unpack_from(bo + "I", brut, off + 8)[0]
        deb = off + 16
        fin = deb + incl
        if fin > n:
            break                        # dernier enregistrement tronqué : on s'arrête
        p = _decoder_usbpcap(brut[deb:fin])
        if p is not None and p.data:
            paquets.append(p)
        off = fin
    return paquets


def _lire_pcapng(brut):
    """pcapng (le format d'enregistrement par défaut de Wireshark)."""
    # Le Section Header Block porte la boutianité (magic 0x1A2B3C4D).
    if struct.unpack_from("<I", brut, 8)[0] == 0x1A2B3C4D:
        bo = "<"
    elif struct.unpack_from(">I", brut, 8)[0] == 0x1A2B3C4D:
        bo = ">"
    else:
        raise ExtractionError(_L("firmware.extract.pcapng_illisible"))

    paquets = []
    interfaces = []          # link-layer par interface, dans l'ordre d'apparition
    off = 0
    n = len(brut)
    while off + 12 <= n:
        btype = struct.unpack_from(bo + "I", brut, off)[0]
        blen  = struct.unpack_from(bo + "I", brut, off + 4)[0]
        if blen < 12 or off + blen > n:
            break                        # bloc tronqué : on arrête proprement
        corps = brut[off + 8:off + blen - 4]

        if btype == 0x00000001:          # Interface Description Block
            linktype = struct.unpack_from(bo + "H", corps, 0)[0]
            interfaces.append(linktype)
        elif btype == 0x00000006:        # Enhanced Packet Block
            iface_id = struct.unpack_from(bo + "I", corps, 0)[0]
            cap_len  = struct.unpack_from(bo + "I", corps, 12)[0]
            data = corps[20:20 + cap_len]
            if (iface_id < len(interfaces)
                    and interfaces[iface_id] == LINKTYPE_USBPCAP):
                p = _decoder_usbpcap(data)
                if p is not None and p.data:
                    paquets.append(p)
        elif btype == 0x00000003:        # Simple Packet Block (sans interface_id)
            data = corps[4:]
            if any(lt == LINKTYPE_USBPCAP for lt in interfaces):
                p = _decoder_usbpcap(data)
                if p is not None and p.data:
                    paquets.append(p)
        # les autres blocs (options, statistiques…) ne nous concernent pas

        off += blen

    if not interfaces:
        raise ExtractionError(_L("firmware.extract.pcapng_sans_interface"))
    if not any(lt == LINKTYPE_USBPCAP for lt in interfaces):
        raise ExtractionError(_L("firmware.extract.pas_interface_usbpcap"))
    return paquets


# ── Extraction proprement dite ────────────────────────────────────────────────
def extract_from_pcapng(chemin):
    """Reconstruit le firmware depuis une capture. Rend les octets, ou lève.

    Repère la séquence d'upload d'après le protocole connu :
      1. Hello `0190040000000000` (hôte → wing, EP 0x02) ;
      2. on se cale sur CE périphérique (adresse device du Hello) ;
      3. on concatène les transferts bulk OUT (EP 0x02) qui suivent, dans
         l'ordre, jusqu'au End packet `079004000000300000000000` ;
      4. le total doit faire 34 624 o (67 × 512 + 320).

    Le nom « from_pcapng » est historique : la fonction lit aussi le pcap
    classique d'USBPcap (voir `_lire_paquets`).
    """
    paquets = _lire_paquets(chemin)

    # 1. Le Hello, host → wing, sur l'endpoint de sortie.
    idx_hello = None
    device = None
    for i, p in enumerate(paquets):
        if (not p.depuis_device and p.endpoint == EP_OUT
                and p.data == HELLO_PKT):
            idx_hello = i
            device = p.device
            break
    if idx_hello is None:
        raise ExtractionError(_L("firmware.extract.aucune_sequence"))

    # 2. Les morceaux du firmware, jusqu'au End packet, sur le même device.
    morceaux = []
    fin_vue = False
    for p in paquets[idx_hello + 1:]:
        if p.device != device:
            continue
        if p.depuis_device or p.endpoint != EP_OUT:
            continue                     # on ne compte QUE les OUT vers la wing
        if p.data == FW_END_PKT:
            fin_vue = True
            break
        if p.data == HELLO_PKT:
            continue                     # un Hello isolé n'est pas un morceau
        morceaux.append(p.data)

    blob = b"".join(morceaux)

    if not fin_vue:
        raise ExtractionError(_L("firmware.extract.sequence_incomplete_fin",
                                 morceaux=len(morceaux), o=len(blob)))
    if len(blob) != FIRMWARE_LONGUEUR:
        raise ExtractionError(_L("firmware.extract.sequence_incomplete_taille",
                                 morceaux=len(morceaux), o=len(blob),
                                 attendu=FIRMWARE_LONGUEUR))
    return blob


# ── Vérification ──────────────────────────────────────────────────────────────
def verify(blob):
    """(ok, message). Vrai si taille ET empreinte sha256 correspondent."""
    if len(blob) != FIRMWARE_LONGUEUR:
        return (False, _L("firmware.extract.taille_inattendue",
                          o=len(blob), attendu=FIRMWARE_LONGUEUR))
    h = hashlib.sha256(blob).hexdigest()
    if h != FIRMWARE_SHA256:
        return (False, _L("firmware.extract.empreinte_differente", h=h))
    return (True, _L("firmware.extract.valide", o=FIRMWARE_LONGUEUR))


# ── CLI ───────────────────────────────────────────────────────────────────────
def _main(argv):
    import argparse
    ap = argparse.ArgumentParser(
        description="Reconstruit wing_firmware.bin depuis une capture "
                    "Wireshark/USBPcap (.pcapng ou .pcap).")
    ap.add_argument("capture", help="fichier de capture (.pcapng ou .pcap)")
    ap.add_argument("-o", "--output",
                    help="fichier de sortie (par défaut : wing_firmware.bin)",
                    default="wing_firmware.bin")
    args = ap.parse_args(argv)

    try:
        blob = extract_from_pcapng(args.capture)
    except ExtractionError as e:
        print(f"✗ {e}")
        return 2

    ok, msg = verify(blob)
    sha = hashlib.sha256(blob).hexdigest()
    print(f"  {len(blob)} octets extraits")
    print(f"  sha256 : {sha}")
    if ok:
        print(f"  ✓ {msg}")
        with open(args.output, "wb") as f:
            f.write(blob)
        print(f"  → écrit dans {args.output}")
        return 0
    print(f"  ✗ {msg}")
    print("  Fichier NON écrit (le firmware extrait ne correspond pas à "
          "l'empreinte attendue).")
    return 1


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
