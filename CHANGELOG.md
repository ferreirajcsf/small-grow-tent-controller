# Changelog

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
