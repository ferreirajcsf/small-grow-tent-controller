[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/github/v/release/ferreirajcsf/small-grow-tent-controller?display_name=tag&sort=semver)](https://github.com/ferreirajcsf/small-grow-tent-controller/releases)
[![License](https://img.shields.io/github/license/ferreirajcsf/small-grow-tent-controller)](LICENSE)

# Small Grow Tent Controller (Home Assistant Integration)

A Home Assistant custom integration to **monitor and actively control the environment of a small grow tent** using temperature, humidity, VPD, and dew-point–aware logic.

> **Status:** Early development (pre-1.0).  
> Expect breaking changes until a stable release is tagged.

---

## What This Integration Does

The Small Grow Tent Controller continuously monitors temperature and humidity sensors and automatically controls connected devices to maintain a healthy **Vapor Pressure Deficit (VPD)** inside a grow tent.

The controller is designed for **hands-off, safety-aware operation**, balancing plant needs while protecting equipment and preventing rapid cycling.

### Core control behavior includes:

- VPD-based environmental control
- Automatic calculation of VPD and dew point
- Hard safety limits for temperature and humidity
- Anti-cycling protections via configurable hold times
- Optional night-time dew-point protection
- Support for drying modes and safety trips

---

## Features

- Config Flow UI setup
- Automatically created entities for:
  - Sensors (averages, VPD, dew point, diagnostics)
  - Switches (controller + devices)
  - Numbers (limits, deadbands, hold times)
  - Selects (growth stage)
  - Time helpers (light schedules)

All entities are exposed through Home Assistant’s standard UI once the integration is installed.

---

## Installation

### Option A — HACS (Custom Repository)

1. In Home Assistant, open **HACS → Integrations**
2. Open the menu (⋮) → **Custom repositories**
3. Add this repository URL and select **Integration** as the category
4. Install **Small Grow Tent Controller**
5. Restart Home Assistant


### Option B — Manual

1. Copy the folder `custom_components/small_grow_tent_controller/` into:
   `config/custom_components/small_grow_tent_controller/`
2. Restart Home Assistant.


## Configuration

1. Go to **Settings → Devices & Services**
2. Click **Add Integration**
3. Search for **Small Grow Tent Controller**
4. Follow the configuration wizard

After setup, all entities will appear under the integration’s device page.

---

## Example Dashboard

This repository includes an example Lovelace dashboard for the
Small Grow Tent Controller integration.

📁 Location:
examples/dashboard.yaml


### Dashboard requirements

Install the following custom cards via HACS:

- layout-card (with grid-layout)
- Mushroom cards
- card-mod

### How to use the dashboard

1. Open Home Assistant
2. Go to **Settings → Dashboards**
3. Add a **YAML dashboard**
4. Copy the contents of `examples/dashboard.yaml`
5. Adjust entity IDs to match your setup

![Dashboard example](images/Screenshot_GTC.png)

---

## Support

- Bug reports and feature requests:  
  https://github.com/ferreirajcsf/small-grow-tent-controller/issues

When reporting issues, please include:
- Home Assistant version
- Integration version
- Relevant logs (with debug enabled if possible)

---

## Development

Recommended checks before publishing a release:

- `hassfest`
- `ruff` or `flake8`
- `pytest` (if tests are added)

Pull requests are welcome.

---

## License

MIT — see `LICENSE`
