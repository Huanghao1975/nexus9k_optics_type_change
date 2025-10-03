# Changelog

All notable changes to this project are recorded in this file.

## Unreleased

- Add `json` output option for single-interface queries; can be combined with `details`.
  - `python type.py Ethernet1/1/1 json` prints a compact JSON wrapper with a single `type` field.
  - `python type.py Ethernet1/1/1 json details` fetches the device `transceiver details | json`, replaces only the nested `type` field with the calculated value, and prints the resulting JSON exactly.
- Normalize several OSFP SPROM type names to new standardized values:
  - Condition A -> `800G-2FR4-OSFP112`
  - Condition B -> `800G-2DR4-OSFP112`
  - Condition C -> `800G-2VR4-OSFP112`
  - Condition D -> `800G-2SR4-OSFP112`
- When a single-interface query triggers a type change, the `type is` SPROM line shows only the modified type (no `original(modified)` format).
- Fix re.sub replacement to use a callable (lambda) so replacement strings starting with digits don't cause `re.error: invalid group reference`.
- Minor help/README updates describing the `json` option and usage examples.

## 6f3f68d (recent)

- Commit: "Normalize OSFP type names, show modified TYPE only for single-interface, fix regex replacement, update README"
