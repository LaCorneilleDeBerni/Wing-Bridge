#!/usr/bin/env python3
"""
smoke_leds.py — Wing Bridge
============================
Domaine LEDs du test de fumée. Un seul contrôle ici (test_carte_led) : c'est
le domaine le plus isolé de smoke_test.py, choisi en premier pour éprouver le
découpage — voir smoke_core.py pour ok/echec/note/section.
"""

from smoke_core import ok, echec, section


def test_carte_led(ui):
    """Chaque bouton a une LED, sans aucune configuration.

    🔑 Signalé : « lorsqu'on appuie sur un bouton, il ne s'allume pas ».
    Cause : seuls les executors avaient un slot LED ; les autres touches
    dépendaient d'une cartographie manuelle que **personne n'avait jamais
    remplie** (zéro entrée dans les profils de référence).

    La carte a été retrouvée dans `a-1.pcapng`, en corrélant les événements
    d'appui avec les paquets LED de 264 o : sur les 7 boutons pressés, le même
    slot passe de 64 (veilleuse) à 2040 (plein feu). Ces 7 mesures sont les
    valeurs de référence ci-dessous — elles viennent de la capture, pas d'une
    déduction.
    """
    section("32. Carte des LEDs — un slot par bouton, sans réglage")
    # (bouton, slot) relevés dans a-1.pcapng — NE PAS « corriger » sans capture
    mesures = [(0x0e, 28), (0x26, 76), (0x2a, 84), (0x2b, 86),
               (0x3b, 118), (0x3c, 120), (0x42, 132)]
    faux = [f"0x{b:02x} → {ui.slot_led(b)} (mesuré : {att})"
            for b, att in mesures if ui.slot_led(b) != att]
    if faux:
        echec("la carte LED ne colle plus aux mesures de la capture",
              " ; ".join(faux) + " — source : a-1.pcapng, corrélation appui/LED")
    else:
        ok(f"{len(mesures)} boutons retrouvent leur slot mesuré dans la capture")

    # Les executors gardent leur bloc propre, vérifié en juillet sur les 12
    ex = [(b, 196 + 2 * (b - 0x70)) for b in (0x70, 0x76, 0x7d)]
    fauxe = [f"0x{b:02x} → {ui.slot_led(b)} au lieu de {att}"
             for b, att in ex if ui.slot_led(b) != att]
    if fauxe:
        echec("le bloc LED des executors a changé", " ; ".join(fauxe))
    else:
        ok("executors 0x70-0x7d : bloc 196-222 préservé")

    # Aucun bouton ordinaire ne doit tomber dans le bloc des executors
    collisions = [hex(b) for b in range(0x05, 0x70)
                  if (s := ui.slot_led(b)) is not None and s >= 196]
    if collisions:
        echec("des boutons ordinaires empiètent sur le bloc des executors",
              ", ".join(collisions))
    else:
        ok("aucune collision entre boutons ordinaires et executors")
