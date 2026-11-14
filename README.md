# AMDB OANS

[English](README.md) · [Русский](README.ru.md)

Local airport moving-map for Microsoft Flight Simulator 2020 — FlyByWire A380 OANS in the aircraft, plus a browser map on your PC.

Source code, docs, and app updates: https://github.com/csv4211/Free-OANS-ANF-BTV-For-MSFS2020

## What it does

- **OANS in the aircraft** — feeds AMDB airport charts into the FlyByWire A380 ND/OANS view while you taxi.
- **Web map** — same airport data in your browser, with aircraft position from SimConnect and simple taxi routing.
- **Online origin** — maps are fetched from the AMDB server.
- **Auto-update** — on launch the app checks for a newer build and installs it by itself.
- **Device access** — first run registers this PC; language switch EN / RU in the window.

## Requirements

- Internet connection to the AMDB server
- **Administrator** rights only if you enable **OANS in the aircraft** (hosts + port 443). The web map works without admin.

## Quick start

1. Download `AmdbOansClient.exe`.
2. Run it.
3. Wait until status shows ready / server online.
4. Turn on **Web map** and/or **OANS in the aircraft**.
5. For OANS: start the sim with the FBW A380 and open the OANS/ND as usual.

It is recommended to run `AmdbOansClient.exe` before starting the simulator.

## Notes

- If Windows SmartScreen warns on first run: *More info* → *Run anyway* (unsigned build).
- Antivirus may flag the MITM helper used for OANS; that path is only active while OANS is enabled and runs locally.

## Support

If activation fails or the map stays empty, check that the origin server is online and that you are on the required client version (the app should update itself when a new build is published).
