# Changelog

## 0.1.13
- Fix default circulation fan entity id (switch.circulationgrowtent).
- Update example dashboard to use the corrected circulation fan entity id.

## 0.1.12
- Add optional exhaust safety override to prevent the exhaust fan from being forced OFF above user-defined temperature/humidity thresholds.
- Add a global "Return All Devices to Auto" button to reset all device override modes back to Auto.

## 0.1.11
- Add per-device override mode selectors (Auto / On / Off) for light, circulation, exhaust, heater, humidifier, and dehumidifier.
- Forced modes override controller logic and restore after Home Assistant restarts.

## 0.1.10
- Remove forced always-on exhaust behavior in Mid/Late Flower stages; exhaust is now controlled normally across all stages.

## 0.1.3
- Add per-device enable/disable toggles in the config flow (so you can omit devices you don't have).
- Hide device-specific tuning controls when the corresponding device is disabled:
  - Heater hold/max-run numbers
  - Exhaust hold number
  - Humidifier hold number
  - Dehumidifier hold number
- Hide light schedule (Light On/Off) time entities when light control is disabled.

## 0.1.2
- Previous release.
