# Changelog
All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.9] – 2026-02-20
### Fixed
- Fixed an issue where devices disabled in the integration options
  (Light, Exhaust Fan, Circulation Fan, Heater, Humidifier, Dehumidifier)
  could still be actively controlled by the integration.
- Device enable/disable options are now fully respected by the controller logic,
  not just hidden from the UI.

### Changed
- Improved option handling to correctly distinguish between:
  - options that are not set, and
  - options explicitly set to `False`.
- Prevented fallback to initial configuration values when a device is disabled.

---

## [0.1.3]
### Added
- Per-device enable/disable toggles in the config flow, allowing users to omit devices they do not have.

### Changed
- Device-specific tuning controls are now hidden when the corresponding device is disabled:
  - Heater hold and max-run number entities
  - Exhaust fan hold number entity
  - Humidifier hold number entity
  - Dehumidifier hold number entity
- Light schedule (Light On/Off) time entities are hidden when light control is disabled.

---

## [0.1.2]
### Added
- Initial public release.
