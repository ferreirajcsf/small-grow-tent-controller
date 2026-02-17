# Small Grow Tent Controller (Home Assistant Integration)

A Home Assistant custom integration to control and monitor a small grow tent.

> **Status:** early development (pre-1.0). Expect breaking changes until a stable release is tagged.

## Features

- Config Flow UI setup
- Entities for sensors, switches, numbers, selects, and time helpers (see Entities section after installation)

## Installation

### Option A — HACS (custom repository)

1. In Home Assistant, open **HACS → Integrations**.
2. Open the menu (⋮) → **Custom repositories**.
3. Add this repository URL and choose **Integration** as the category.
4. Install **Small Grow Tent Controller**.
5. Restart Home Assistant.

### Option B — Manual

1. Copy the folder `custom_components/small_grow_tent_controller/` into:
   `config/custom_components/small_grow_tent_controller/`
2. Restart Home Assistant.

## Configuration

Go to **Settings → Devices & services → Add integration** and search for:

**Small Grow Tent Controller**

Follow the wizard.


## Example Dashboard

This repository includes an example Lovelace dashboard for the
Small Grow Tent Controller integration.

📁 Location:
examples/dashboard.yaml

### Requirements
This dashboard uses the following custom cards (install via HACS):
- layout-card (with grid-layout)
- Mushroom cards
- button-card
- card-mod

### How to use

1. Open Home Assistant
2. Go to **Settings → Dashboards**
3. Add a **YAML dashboard**
4. Copy the contents of `examples/dashboard.yaml`
5. Adjust entity IDs to match your setup

![Dashboard example](images/Screenshot_GTC.png)

## Support

- Issues: https://github.com/ferreirajcsf/small-grow-tent-controller/issues

## Development

Recommended checks before publishing a release:

- `hassfest`
- `ruff` / `flake8`
- `pytest` (if you add tests)

## License

MIT (see `LICENSE`).
