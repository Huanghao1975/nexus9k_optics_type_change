# nexus9k_optics_type_change
This repository contains a small Python utility that runs inside the Nexus NX-OS Python environment to read transceiver SPROM information and present a modified "Type" value for Nexus 9000 OSFP transceivers.
The script was developed to help normalize and present a consistent, operationally-friendly transceiver TYPE string when the SPROM reports legacy or ambiguous values. It reads the SPROM for a given interface (or for many interfaces via `status`), applies a small set of rules, and prints the adjusted output.
## What's changed (recent updates)
- Rename mapping: the script now maps several original SPROM types to new, standardized strings:
	- Condition A -> `800G-2FR4-OSFP112`
	- Condition B -> `800G-2DR4-OSFP112`
	- Condition C -> `800G-2VR4-OSFP112`
	- Condition D -> `800G-2SR4-OSFP112`
- Single-interface display behavior: when querying one port, if a rule triggers the TYPE change, the SPROM output's `type is` line now shows only the modified TYPE (for example `type is 800G-2DR4-OSFP112`) instead of the previous `original(modified)` format.
- Regex replacement robustness: when replacing the `type is` value the code now uses a callable replacement to avoid accidental interpretation of replacement text as regex group references (fixes re.error when replacement begins with a digit).
- Minor syntax/indentation fixes to ensure the script parses cleanly and runs inside NX-OS Python.
## How it works (summary)
- The main functions are:
	- `_get_transceiver_data(interface)` — runs `show interface <intf> transceiver sprom` and parses a few fields (type, host/media lane counts, connector, original output lines).
	- `_determine_modified_type_from_parsed_data(data)` — applies the mapping rules above and returns `(original_sprom_type, final_calculated_type)`.
	- `process_single_interface_sprom(interface, include_details=False)` — fetches SPROM, determines the modified type, replaces the `type is` line and optionally appends `transceiver details` output.
	- `process_status_command()` — runs `show interface status | json`, queries canonical SPROM interfaces concurrently and prints a formatted table with modified types.
## Usage
Run inside a Nexus NX-OS device Python environment (the script imports `cli`):
Single interface SPROM (print modified SPROM output):
```bash
python type.py Ethernet1/1/1
```
Single interface SPROM plus details (lane info):
```bash
python type.py Ethernet1/1/1 details
```
Show status table (concurrently queries SPROM for relevant ports):
```bash
python type.py status
```
Notes:
- The script must run on the switch; `from cli import cli` is used to call NX-OS CLI commands.
- The `status` command collects SPROM data concurrently for parent/first-sub ports. Running many concurrent CLI calls may be unstable in some guest shells — reduce concurrency if needed.
## Rules implemented
- Condition A (LC connector):
	- original SPROM type is `OSFP-2x400G-FR4` or `OSFP-800G-DR8-2`
	- host_lane_count == `8`
	- media_lane_count == `8`
	- connector_type == `0x07 (LC)`
	- becomes `800G-2FR4-OSFP112`
- Condition B (MPO connectors):
	- original SPROM type is `OSFP-800G-DR8` or `OSFP-2x400G-DR4`
	- connector_type in (`0x27 (MPO 2x12)`, `0x0c (MPO)`)
	- host_lane_count == `8`
	- media_lane_count == `8`
	- becomes `800G-2DR4-OSFP112`
- Condition C (MPO connectors):
	- original SPROM type is `OSFP-800G-VR8` or `OSFP-2x400G-VR4`
	- connector_type in (`0x27 (MPO 2x12)`, `0x0c (MPO)`)
	- host_lane_count == `8`
	- media_lane_count == `8`
	- becomes `800G-2VR4-OSFP112`
- Condition D (MPO connectors):
	- original SPROM type is `OSFP-800G-SR8` or `OSFP-2x400G-SR4`
	- connector_type in (`0x27 (MPO 2x12)`, `0x0c (MPO)`)
	- host_lane_count == `8`
	- media_lane_count == `8`
	- becomes `800G-2SR4-OSFP112`
## Troubleshooting
- If you see `Error: Could not import 'cli' module` when running locally, run the script on the switch's Python environment (or use a wrapper that provides a `cli()` stub for local testing).
- If `re.error: invalid group reference` appears, upgrade to the latest script version which uses a callable replacement (this repository's `type.py` contains the fix).
---
# nexus9k_optics_type_change
