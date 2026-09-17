# THIRD_PARTY — vendored third-party components

Wing Bridge is distributed with two third-party components, both vendored in
`src/vendor/`. Neither is a downloader: each has a pinned version and a verified
fingerprint.

## USBPcap 1.5.4.0 (Windows only)

**USB capture component, temporary.** Installed by Wing Bridge for the time it
takes to read the wing's firmware once, while grandMA2 onPC sends it
(`src/wing_firmware_capture.py`), then **uninstalled automatically** — unless it
was already present on the machine beforehand (in which case Wing Bridge doesn't
touch what isn't its own). See `docs/WINDOWS.md`, section « Capture firmware
intégrée », for the details of the mechanism and the proof that the machine
stays clean after use.

- Source: https://github.com/desowin/usbpcap (author: Tomasz Mon)
- Vendored version: `1.5.4.0`, sha256 in `src/vendor/usbpcap/README.md`
- Licenses (dual-licensed component, **not a single license**):
  - **USBPcapDriver** (the kernel driver) — **GPLv2**,
    `src/vendor/usbpcap/LICENSE-USBPcapDriver-GPLv2.txt`
  - **USBPcapCMD** (the command-line tool) — **BSD 2-Clause**,
    `src/vendor/usbpcap/LICENSE-USBPcapCMD-BSD-2-Clause.txt`
- Redistribution: the official installer is embedded **unmodified**, exactly as
  published on the GitHub release page cited above. The complete source code of
  the vendored version remains available at that same address (tag `1.5.4.0`),
  satisfying the source availability the GPLv2 requires for the driver part.

## libusb (macOS)

`src/vendor/libusb-1.0.0.dylib` — generic USB library used by `pyusb` to talk to
the wing under macOS (fallback under Windows: the WinUSB driver, no vendored
dylib on the Windows side). LGPL-2.1 license.
Source: https://github.com/libusb/libusb.

## Runtime dependencies (pip)

Not vendored: installed in the Python environment (`~/wing-env`), frozen into the
executable at build time by PyInstaller. These are the only ones actually
imported by the production code (verified by `grep`-ing the `import` statements
over `src/`).

| Package | Tested version | License | Role |
|---|---|---|---|
| **pyusb** | 1.3.1 | BSD 3-Clause | USB access to the wing (`usb.core`, `usb.util`). Relies on libusb (macOS) or WinUSB (Windows). |
| **python-osc** | 1.10.2 | The Unlicense (public domain) | OSC dialogue with grandMA3 (`pythonosc.udp_client`, `pythonosc.osc_packet`): sending keys/faders/wheels, receiving console feedback. |
| **pyobjc** (`pyobjc-core` + `Cocoa`, `Quartz`, `ApplicationServices` frameworks) | 12.2.1 | MIT | Console-mode keyboard helper under macOS (`wing_keyboard_macos.py`): synthesising keyboard events and the Accessibility API. Separate build (`build_app.sh`). |

`websocket-client` / `websockets` may appear in the venv as transitive
dependencies: **neither is imported** by Wing Bridge.

### PyInstaller — build tool (not embedded as a library)

**PyInstaller** 6.21.0 freezes the app into a standalone executable. It is under
**GNU GPL-2.0 (or later) with an explicit “Bootloader” exception**:

> “In addition to the permissions in the GNU General Public License, the
> authors give you unlimited permission to link or embed compiled bootloader
> and related files into combinations with other programs, and to distribute
> those combinations without any restriction coming from the use of those
> files.”
> — `pyinstaller-*/licenses/COPYING.txt`, *Bootloader Exception* section

Consequence: the PyInstaller bootloader embedded in `Wing Bridge.app` **does not
contaminate** the produced executable — it is **not** forced under GPL by the
mere fact of having been packaged with PyInstaller. (Wing Bridge is under
GPL-3.0 by the author's own choice, see `LICENSE` — not by any PyInstaller
obligation.) The *run-time hooks* PyInstaller embeds are themselves under
Apache-2.0.
