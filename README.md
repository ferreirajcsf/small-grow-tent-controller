# Small Grow Tent Controller (Home Assistant Integration)

<!-- ===================== -->
<!-- BADGES (PRIVATE REPO) -->
<!-- Works while the repository is private -->
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Version](https://img.shields.io/badge/version-v0.1.2-blue.svg)](https://github.com/ferreirajcsf/small-grow-tent-controller/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

<!-- ===================== -->
<!-- BADGES (PUBLIC REPO) -->
<!-- Uncomment these and remove the PRIVATE block when you make the repo public -->
<!--
[![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://hacs.xyz/)
[![Latest Release](https://img.shields.io/github/v/release/ferreirajcsf/small-grow-tent-controller)](https://github.com/ferreirajcsf/small-grow-tent-controller/releases)
[![License](https://img.shields.io/github/license/ferreirajcsf/small-grow-tent-controller)](LICENSE)
-->

A Home Assistant custom integration to control and monitor a small grow tent using simple **on/off control logic**.

This integration was created to solve a practical problem: maintaining safe and stable temperatures during winter, where a heater could easily overheat the grow space. The initial focus is therefore on reliable temperature control, with additional functionality added over time as real-world needs arise.

The project has been developed primarily for personal use and real-world testing. It is my first Home Assistant integration and was built while learning Home Assistant, so the feature set is intentionally limited and may evolve as the project matures.

That said, the integration is actively used, functional, and shared for anyone with similar requirements.

> **Status:** early development (pre-1.0). Expect breaking changes until a stable release is tagged.

---

## Features

- UI-based setup via Home Assistant Config Flow
- Simple and predictable on/off control logic
- Entities for:
  - Sensors
  - Switches
  - Numbers
  - Selects
  - Time helpers
- Designed to remain lightweight and easy to understand

---

## Installation

**Private repository note**
>
> This integration is hosted in a private GitHub repository.
> When installing via HACS, the GitHub account used by HACS must:
>
> - Have access to this repository, and
> - Grant the HACS GitHub App permission to access the repository.
>
> Manual installation is recommended for personal or private use.


### Option A — HACS (custom repository)

1. In Home Assistant, open **HACS → Integrations**
2. Open the menu (⋮) → **Custom repositories**
3. Add this repository URL and select **Integration** as the category
4. Install **Small Grow Tent Controller**
5. Restart Home Assistant

### Option B — Manual installation

1. Copy the folder:
1. Copy the folder `custom_components/small_grow_tent_controller/` into:
   `config/custom_components/small_grow_tent_controller/`
2. Restart Home Assistant.

---

## Configuration

1. Go to **Settings → Devices & services**
2. Click **Add integration**
3. Search for **Small Grow Tent Controller**
4. Follow the configuration wizard

---

## Example Dashboard

This repository includes an example Lovelace dashboard for the  
Small Grow Tent Controller integration.

📁 **Location:**  
`examples/dashboard.yaml`

### Requirements

The example dashboard uses the following custom cards (install via HACS):

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

---

## Project goals

- Provide reliable on/off control for grow tent devices
- Prevent overheating during cold seasons
- Keep configuration simple and transparent
- Remain lightweight and easy to extend

---

## Support

- Issue tracker:  
https://github.com/ferreirajcsf/small-grow-tent-controller/issues

---

## Development (optional)

Recommended checks before publishing a release:

- `hassfest`
- `ruff` or `flake8`
- `pytest` (if tests are added)

---

## License

MIT — see `LICENSE`
