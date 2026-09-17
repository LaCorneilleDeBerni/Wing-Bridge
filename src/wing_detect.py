#!/usr/bin/env python3
"""
Wing Detect — scan USB, identification des wings compatibles et test de handshake
================================================================================
Sert à répondre à : "cette command wing est-elle compatible ?"

- scan()  : liste tous les périphériques USB avec classification
            (supportée / candidate / autre)
- probe() : envoie le HELLO du protocole MATRIX_USB à un périphérique
            candidat et enregistre sa réponse → empreinte du modèle

Comment savoir si une wing a une puce différente ?
  → Son VID:PID et ses descripteurs USB le révèlent. Deux wings avec le
    même VID:PID (0x03EB:0x160B) et la même réponse au HELLO utilisent
    très probablement le même PCB → compatibles direct.
    Un VID:PID différent = puce différente → il faudra capturer son
    protocole (Wireshark USB) et ajouter un module d'init dédié.
"""

import usb.core
import usb.util

from wing_init import _backend, HELLO_PKT


def _L(cle, **params):
    import wing_i18n
    return wing_i18n.L(cle, **params)

# ── Base des modèles connus ───────────────────────────────────────────────────
# (vid, pid) → (nom, statut)
# Enrichir au fur et à mesure que des modèles sont identifiés.
KNOWN_DEVICES = {
    (0x03EB, 0x160B): ("Command wing MA2 onPC — protocole MATRIX_USB", "supported"),
}

# Réponse HELLO attendue pour le protocole MATRIX_USB (préfixe)
# La wing connue répond un paquet commençant par 0x01 0x91.
HELLO_RESP_PREFIX = bytes.fromhex("0191")


def _safe_string(dev, index):
    if not index:
        return None
    try:
        return usb.util.get_string(dev, index)
    except Exception:
        return None


def _endpoints_info(dev):
    """Retourne [(addr, type, direction), ...] ou [] si illisible."""
    eps = []
    try:
        for cfg in dev:
            for iface in cfg:
                for ep in iface:
                    addr = ep.bEndpointAddress
                    tp   = usb.util.endpoint_type(ep.bmAttributes)
                    tname = {0: "ctrl", 1: "iso", 2: "bulk", 3: "int"}.get(tp, "?")
                    direction = "IN" if addr & 0x80 else "OUT"
                    eps.append({"addr": f"0x{addr:02x}", "type": tname, "dir": direction})
    except Exception:
        pass
    return eps


def _classify(vid, pid, dev, eps):
    """→ (statut, raison)  statut ∈ supported | candidate | other"""
    if (vid, pid) in KNOWN_DEVICES:
        return "supported", KNOWN_DEVICES[(vid, pid)][0]

    reasons = []
    if vid == 0x03EB:
        reasons.append(_L("err.detect.puce_atmel"))

    # Vendor-specific + bulk IN 0x81 / OUT 0x02 comme la wing connue
    try:
        cls = dev.bDeviceClass
    except Exception:
        cls = None
    bulk_in  = any(e["addr"] == "0x81" and e["type"] == "bulk" for e in eps)
    bulk_out = any(e["addr"] == "0x02" and e["type"] == "bulk" for e in eps)
    if cls == 0xFF and bulk_in and bulk_out:
        reasons.append(_L("err.detect.vendor_bulk"))

    if reasons:
        return "candidate", " ; ".join(reasons)
    return "other", ""


def scan():
    """Scan complet du bus USB. Retourne une liste de dicts."""
    out = []
    try:
        devices = list(usb.core.find(find_all=True, backend=_backend()))
    except Exception as e:
        return {"error": _L("err.detect.scan_ko", err=e)}

    for dev in devices:
        vid, pid = dev.idVendor, dev.idProduct
        eps = _endpoints_info(dev)
        status, reason = _classify(vid, pid, dev, eps)
        try:
            cls = f"0x{dev.bDeviceClass:02x}"
        except Exception:
            cls = "?"
        out.append({
            "vid":          f"0x{vid:04x}",
            "pid":          f"0x{pid:04x}",
            "manufacturer": _safe_string(dev, dev.iManufacturer),
            "product":      _safe_string(dev, dev.iProduct),
            "serial":       _safe_string(dev, dev.iSerialNumber),
            "class":        cls,
            "endpoints":    eps,
            "status":       status,
            "reason":       reason,
        })

    # Supportées d'abord, puis candidates
    order = {"supported": 0, "candidate": 1, "other": 2}
    out.sort(key=lambda d: order[d["status"]])
    return out


def probe(vid: int, pid: int):
    """
    Test de handshake MATRIX_USB : envoie HELLO, lit la réponse.
    → empreinte du périphérique. À n'utiliser que sur un candidat
    (déclenché manuellement depuis l'UI).
    """
    dev = usb.core.find(idVendor=vid, idProduct=pid, backend=_backend())
    if dev is None:
        return {"ok": False, "error": _L("err.detect.introuvable")}

    try:
        for iface in range(2):
            try:
                if dev.is_kernel_driver_active(iface):
                    dev.detach_kernel_driver(iface)
            except Exception:
                pass
        try:
            dev.set_configuration()
        except Exception:
            pass
        try:
            usb.util.claim_interface(dev, 0)
        except Exception:
            pass

        dev.write(0x02, HELLO_PKT, timeout=500)
        try:
            resp = bytes(dev.read(0x81, 2048, timeout=1500))
        except Exception:
            resp = None

        if resp is None:
            return {"ok": False, "verdict": _L("err.detect.pas_de_reponse")}

        matrix = resp[:2] == HELLO_RESP_PREFIX
        return {
            "ok": True,
            "response_hex": resp.hex(),
            "response_len": len(resp),
            "matrix_usb": matrix,
            "verdict": _L("err.detect.verdict_match") if matrix
                       else _L("err.detect.verdict_mismatch"),
        }
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            usb.util.dispose_resources(dev)
        except Exception:
            pass


if __name__ == "__main__":
    import json
    print(json.dumps(scan(), indent=2, ensure_ascii=False))
