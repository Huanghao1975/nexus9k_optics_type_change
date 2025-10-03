import re
import sys
import time # Import the time module
import json # Import the json module
from concurrent.futures import ThreadPoolExecutor, as_completed # For concurrent execution

# Global debug mode flag
DEBUG_MODE = False

# Import the NX-OS CLI module for executing CLI commands
# Note: This module is only available in the Python environment of a Nexus NX-OS device.
try:
    from cli import cli
except ImportError:
    print("Error: Could not import 'cli' module. This script must be run in the Python environment of a Nexus NX-OS device.", file=sys.stderr)
    sys.exit(1)

def debug_print(message):
    """Prints a debug message if DEBUG_MODE is enabled."""
    if DEBUG_MODE:
        print(f"DEBUG: {message}")

def display_help():
    """Displays the usage information for the script."""
    print("\n--- Script Usage Information ---")
    print("This script collects and modifies transceiver SPROM information on a Nexus 9300 switch.")
    print("It can optionally append 'transceiver details' output.")
    print("\nUsage:")
    print("  python your_script.py [-D] <interface_name> [details]")
    print("  python your_script.py [-D] status")
    print("  or (if alias 'type-check' is configured):")
    print("  type-check [-D] <interface_name> [details]")
    print("  type-check [-D] status")
    print("\nArguments:")
    print("  -D               : Optional. Enable debug output for detailed execution information.")
    print("  <interface_name> : Required. The full name of the Ethernet interface (e.g., Ethernet1/57/1).")
    print("                     When using 'status' command, only 'Ethernet' interfaces are processed.")
    print("  [details]        : Optional. If provided, the script will also append the 'transceiver details' output for the interface.")
    print("  status           : If provided, the script will show 'show interface status' output with modified transceiver types for all 'Ethernet' ports,")
    print("                     ignoring 'xcvrAbsent' ports for SPROM queries. SPROM queries for parent ports (Ethernet1/X) or first sub-ports (Ethernet1/X/1) are done concurrently.")
    print("\nExamples:")
    print("  python your_script.py Ethernet1/57/1")
    print("  python your_script.py -D Ethernet1/57/1 details")
    print("  python your_script.py status")
    print("  type-check -D status")
    print("\n--- End of Usage Information ---\n")
    sys.exit(0)

def _get_sprom_query_interface(interface_name):
    """
    Determines the canonical interface name to query SPROM for.
    For Ethernet1/X/Y, returns Ethernet1/X/1.
    For Ethernet1/X, returns Ethernet1/X.
    For other interfaces, returns the original name.
    """
    # Case 1: Ethernet1/X/Y -> Ethernet1/X/1
    match_breakout_subport = re.match(r'^(Ethernet\d+/\d+)/(\d+)$', interface_name)
    if match_breakout_subport:
        return f"{match_breakout_subport.group(1)}/1" # Returns Ethernet1/1/1 from Ethernet1/1/2

    # Case 2: Ethernet1/X -> Ethernet1/X (no change)
    match_main_port = re.match(r'^(Ethernet\d+/\d+)$', interface_name)
    if match_main_port:
        return match_main_port.group(1) # Returns Ethernet1/1 from Ethernet1/1
        
    return interface_name # For mgmt0, loopback, etc.

# --- Core Logic for Transceiver Type Modification ---
def _get_transceiver_data(interface_name_var):
    """
    Collects raw transceiver SPROM data for an interface.
    Returns a dictionary of parsed values or None if command fails or transceiver not present.
    """
    command = f"show interface {interface_name_var} transceiver sprom"
    try:
        debug_print(f"Calling cli('{command}') at {time.time()}")
        start_time = time.time()
        output = cli(command)
        end_time = time.time()
        debug_print(f"cli('{command}') finished in {end_time - start_time:.4f} seconds.")

        # Check if transceiver is present. If not, output might be short or say "transceiver not present"
        if "transceiver is not present" in output.lower() or not output.strip():
            return None # No transceiver, or empty output
        
        parsed_data = {
            "transceiver_type": "",
            "host_lane_count": "",
            "connector_type": "",
            "media_lane_count": "",
            "part_number": "",
            "original_output_lines": output.splitlines(),
            "type_line_index": -1
        }

        for i, line in enumerate(parsed_data["original_output_lines"]):
            if "type is" in line:
                parsed_data["transceiver_type"] = line.split("type is")[1].strip()
                parsed_data["type_line_index"] = i
            elif "host lane count is" in line:
                # Extract the numeric part, ignoring units
                parsed_data["host_lane_count"] = line.split("host lane count is")[1].strip().split()[0]
            elif "media lane count is" in line:
                # Extract the numeric part, ignoring units
                parsed_data["media_lane_count"] = line.split("media lane count is")[1].strip().split()[0]
            elif "Connector" in line and ":" in line:
                match = re.search(r'Connector\s+:\s+(.*)', line)
                if match:
                    parsed_data["connector_type"] = match.group(1).strip()
            elif line.strip().startswith("part number is"): 
                parsed_data["part_number"] = line.split("part number is")[1].strip()
        return parsed_data
    except Exception as e:
        print(f"ERROR: cli('{command}') failed: {e}", file=sys.stderr) # Added error logging for cli() calls
        return None # Return None if SPROM command fails or no transceiver

def _determine_modified_type_from_parsed_data(data):
    """
    Determines the modified transceiver type based on already parsed data and defined conditions.
    Returns a tuple (original_sprom_type, final_calculated_type_value).
    If no transceiver data is provided, returns ("--", "--").
    """
    if not data:
        return ("--", "--") # Indicate no transceiver or SPROM data

    original_sprom_type = data["transceiver_type"] # This is the type directly from SPROM
    
    # Now, determine what the *modified* type would be based on conditions
    final_calculated_type = None

    # Condition 1: type is OSFP-2x400G-FR4 OR OSFP-800G-DR8-2, AND host lane count is 8, AND media lane count is 8, AND Connector is 0x07 (LC)
    if (original_sprom_type in ("OSFP-2x400G-FR4", "OSFP-800G-DR8-2") and
        data["host_lane_count"] == "8" and
        data["media_lane_count"] == "8" and
        data["connector_type"] == "0x07 (LC)"):
        final_calculated_type = "800G-2FR4-OSFP112"
    
    # Condition 2: type is OSFP-800G-DR8 OR OSFP-2x400G-DR4, AND (Connector is 0x27 (MPO 2x12) OR Connector is 0x0c (MPO)), host 8, media 8
    elif (original_sprom_type in ("OSFP-800G-DR8", "OSFP-2x400G-DR4") and
        (data["connector_type"] == "0x27 (MPO 2x12)" or data["connector_type"] == "0x0c (MPO)") and
        data["host_lane_count"] == "8" and
        data["media_lane_count"] == "8"):
      final_calculated_type = "800G-2DR4-OSFP112"

    # Condition 3: type is OSFP-800G-VR8 OR OSFP-2x400G-VR4, AND (Connector is 0x27 (MPO 2x12) OR Connector is 0x0c (MPO)), host 8, media 8
    elif (original_sprom_type in ("OSFP-800G-VR8", "OSFP-2x400G-VR4") and
        (data["connector_type"] == "0x27 (MPO 2x12)" or data["connector_type"] == "0x0c (MPO)") and
        data["host_lane_count"] == "8" and
        data["media_lane_count"] == "8"):
      final_calculated_type = "800G-2VR4-OSFP112"

    # Condition 4: type is OSFP-800G-SR8 OR OSFP-2x400G-SR4, Connector is 0x27 (MPO 2x12) OR Connector is 0x0c (MPO)), host 8, media 8
    elif (original_sprom_type in ("OSFP-800G-SR8", "OSFP-2x400G-SR4") and
        (data["connector_type"] == "0x27 (MPO 2x12)" or data["connector_type"] == "0x0c (MPO)") and
        data["host_lane_count"] == "8" and
        data["media_lane_count"] == "8"):
      final_calculated_type = "800G-2SR4-OSFP112"
    
    # If no condition met, the final calculated type is the original SPROM type
    return (original_sprom_type, final_calculated_type if final_calculated_type else original_sprom_type)

def process_single_interface_sprom(interface_name_var, include_details=False):
    """
    Executes CLI commands directly on a Nexus 9300 switch to collect transceiver SPROM information,
    and modifies the 'type' field based on specific conditions.
    Optionally, appends 'transceiver details' output if include_details is True.

    Args:
        interface_name_var (str): Interface name (e.g., Ethernet1/57/1).
        include_details (bool): If True, also collect and append 'transceiver details' output.

    Returns:
        str: The modified transceiver SPROM output, optionally with details,
             or an error message.
    """
    data = _get_transceiver_data(interface_name_var)
    if not data:
        return f"Error: Could not retrieve SPROM data for {interface_name_var} or transceiver not present."
    
    # Get original SPROM type and the final calculated type value
    original_sprom_type, final_calculated_type_value = _determine_modified_type_from_parsed_data(data)
    
    # Determine the type string to display in the SPROM output
    final_type_for_sprom_display = final_calculated_type_value # By default, show the new type

    # If the type was actually modified, show only the modified type (not original(modified))
    if final_calculated_type_value != original_sprom_type:
        # Display only the calculated (modified) type as requested
        final_type_for_sprom_display = f"{final_calculated_type_value}"
        debug_print(f"Type modified from '{original_sprom_type}' to '{final_calculated_type_value}' based on conditions.")
    else:
        debug_print(f"No conditions met to modify type. Current type: '{original_sprom_type}'.")


    original_output_lines = data["original_output_lines"]
    type_line_index = data["type_line_index"]
    modified_output_lines = list(original_output_lines) # Make a mutable copy
    
    # Apply modification to the "type is" line in the raw SPROM output
    if type_line_index != -1:
        old_type_string_full_line = original_output_lines[type_line_index]
        # Use regex to ensure only the value after "type is" is replaced, preserving leading spaces
        # Use a callable replacement to avoid accidental backreference parsing
        new_type_string_full_line = re.sub(r'(type is\s+).*', lambda m: m.group(1) + final_type_for_sprom_display, old_type_string_full_line)
        modified_output_lines[type_line_index] = new_type_string_full_line
    else:
        print("Warning: 'type is' line not found for replacement, even though type was extracted.")

    # If include_details is True, fetch and append the 'details' output
    if include_details:
        details_command = f"show interface {interface_name_var} transceiver details | begin \"Lane Number:\""
        print(f"\nExecuting additional command: {details_command}") # This print is always shown as it's a direct action
        try:
            debug_print(f"Calling cli('{details_command}') at {time.time()}")
            start_time = time.time()
            details_output = cli(details_command)
            end_time = time.time()
            debug_print(f"cli('{details_command}') finished in {end_time - start_time:.4f} seconds.")

            modified_output_lines.append("\n--- Transceiver Details (Lane Information) ---")
            modified_output_lines.append(details_output)
            print("Additional 'details' output collected.") # This print is always shown as it's a direct action
        except Exception as details_e:
            print(f"ERROR: cli('{details_command}') failed: {details_e}", file=sys.stderr) # Added error logging
            modified_output_lines.append(f"\nError collecting transceiver details: {details_e}")
            print(f"Error collecting transceiver details: {details_e}")

    return "\n".join(modified_output_lines)

def process_status_command():
    """
    Collects 'show interface status | json' output,
    then collects SPROM data for relevant parent interfaces (Ethernet1/X) or first sub-ports (Ethernet1/X/1),
    modifies transceiver types based on rules,
    and prints the modified status output in text format.
    """
    status_cli_command = "show interface status | json"
    print(f"Executing command: {status_cli_command}") # This print is always shown as it's a direct action
    try:
        debug_print(f"Calling cli('{status_cli_command}') at {time.time()}")
        start_time = time.time()
        status_output_json_str = cli(status_cli_command)
        end_time = time.time()
        debug_print(f"cli('{status_cli_command}') finished in {end_time - start_time:.4f} seconds.")

        # --- Parse JSON output ---
        try:
            json_data = json.loads(status_output_json_str)
            interfaces_data = json_data.get("TABLE_interface", {}).get("ROW_interface", [])
        except json.JSONDecodeError as e:
            print(f"ERROR: Failed to decode JSON from 'show interface status | json': {e}", file=sys.stderr)
            print(f"Raw JSON output: {status_output_json_str[:500]}...", file=sys.stderr) # Print first 500 chars for context
            return

        if not interfaces_data:
            print("No interface data found in 'show interface status | json' output.")
            return

        # --- Define standard header and column widths for text output ---
        # These widths are based on typical 'show interface status' output and desired modified type lengths
        # Each width includes one trailing space for separation
        HEADER_COLS = ["Port", "Name", "Status", "Vlan", "Duplex", "Speed", "Type"]
        COL_WIDTHS = {
            "Port": 15,       # e.g., Eth1/64/2 (max Eth1/64/100)
            "Name": 19,       # Often empty, but can be longer. Default to 19 for alignment.
            "Status": 9,      # Truncate to 9 chars
            "Vlan": 9,        # routed, 1, 100, etc.
            "Duplex": 7,      # full, auto
            "Speed": 8,       # 400G, auto
            "Type": 25        # Modified to accommodate max length of OSFP112-800G-2DR4 (20 chars) + padding
        }
        
        # Generate formatted header and separator
        # Add 1 to each width for the space between columns
        formatted_header_parts = [
            "Port".ljust(COL_WIDTHS["Port"]),
            "Name".ljust(COL_WIDTHS["Name"]),
            "Status".ljust(COL_WIDTHS["Status"]),
            "Vlan".ljust(COL_WIDTHS["Vlan"]),
            "Duplex".ljust(COL_WIDTHS["Duplex"]),
            "Speed".ljust(COL_WIDTHS["Speed"]),
            "Type".ljust(COL_WIDTHS["Type"])
        ]
        formatted_header = " ".join(formatted_header_parts) # Join with a single space

        separator_line_parts = [
            "-" * COL_WIDTHS["Port"],
            "-" * COL_WIDTHS["Name"],
            "-" * COL_WIDTHS["Status"],
            "-" * COL_WIDTHS["Vlan"],
            "-" * COL_WIDTHS["Duplex"],
            "-" * COL_WIDTHS["Speed"],
            "-" * COL_WIDTHS["Type"]
        ]
        separator_line = " ".join(separator_line_parts) # Join with a single space


        # --- Phase 1: Parse all data and identify parent/base ports to query SPROM for ---
        processed_interfaces = [] 
        sprom_query_interfaces = set() # Stores Ethernet1/X or Ethernet1/X/1 for SPROM queries

        for intf_row in interfaces_data:
            interface_name = intf_row.get("interface", "")
            original_state = intf_row.get("state", "") # This is the "Status" column value from JSON
            original_type_from_json = intf_row.get("type", "") # This is the "Type" column value from JSON

            # Store all relevant info for later reconstruction
            processed_interfaces.append({
                "interface": interface_name,
                "state": original_state,
                "vlan": intf_row.get("vlan", ""),
                "duplex": intf_row.get("duplex", ""),
                "speed": intf_row.get("speed", ""),
                "original_type": original_type_from_json # Keep original type from JSON
            })

            # Decide if we need to query SPROM for this interface's canonical SPROM query interface
            # Only query for Ethernet interfaces (starting with "Ethernet") AND if state is NOT "xcvrAbsent"
            if interface_name.startswith("Ethernet") and original_state.lower() != "xcvrabsent":
                canonical_sprom_intf = _get_sprom_query_interface(interface_name) # Get the canonical interface for SPROM query
                sprom_query_interfaces.add(canonical_sprom_intf)
                # debug_print(f"Identified canonical SPROM interface '{canonical_sprom_intf}' for query (from interface '{interface_name}', state: '{original_state}')")
            # else:
                # debug_print(f"Skipping SPROM query for interface '{interface_name}' (state: '{original_state}')")
        
        # --- Phase 2: Collect SPROM data for identified canonical interfaces concurrently ---
        sprom_data_cache = {}
        MAX_CONCURRENT_QUERIES = 10 # User defined maximum concurrency

        debug_print(f"\nCanonical SPROM query interfaces identified: {sorted(list(sprom_query_interfaces))}")
        debug_print(f"Starting CONCURRENT SPROM data collection for {len(sprom_query_interfaces)} interfaces with max {MAX_CONCURRENT_QUERIES} workers...")
        sprom_collection_start_time = time.time()

        # WARNING: Using ThreadPoolExecutor with cli() might lead to instability in Guest Shell.
        # Test thoroughly. Consider reducing max_workers if issues occur.
        with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_QUERIES) as executor:
            future_to_port = {executor.submit(_get_transceiver_data, port): port for port in sprom_query_interfaces}
            for future in as_completed(future_to_port):
                port = future_to_port[future]
                try:
                    data = future.result()
                    sprom_data_cache[port] = data
                except Exception as exc:
                    print(f"ERROR: {port} generated an exception during SPROM data collection: {exc}", file=sys.stderr)
        
        sprom_collection_end_time = time.time()
        debug_print(f"CONCURRENT SPROM data collection for all relevant interfaces finished in {sprom_collection_end_time - sprom_collection_start_time:.4f} seconds.")
        
        # --- Phase 3: Reconstruct the output with modified types ---
        modified_status_output_lines = []
        modified_status_output_lines.append(formatted_header)
        modified_status_output_lines.append(separator_line)

        for intf_data in processed_interfaces:
            interface_name = intf_data["interface"]
            original_state = intf_data["state"]
            original_type_from_json = intf_data["original_type"] # Type string from the status table JSON

            final_type_for_display = original_type_from_json # Default to original type from JSON status table

            # Only apply modification logic for Ethernet interfaces where transceiver is not absent
            if interface_name.startswith("Ethernet") and original_state.lower() != "xcvrabsent":
                canonical_sprom_intf = _get_sprom_query_interface(interface_name) # Get the canonical SPROM query interface
                cached_data = sprom_data_cache.get(canonical_sprom_intf) # Look up using canonical interface
                
                # _determine_modified_type_from_parsed_data returns (original_sprom_type, final_calculated_type_value)
                original_sprom_type, final_calculated_type_value = _determine_modified_type_from_parsed_data(cached_data)
                
                # If the type was actually modified, display only the modified value
                if final_calculated_type_value != original_sprom_type:
                    final_type_for_display = final_calculated_type_value # MODIFIED: Only show the modified type
                else:
                    final_type_for_display = original_sprom_type
            elif original_state.lower() == "xcvrabsent":
                final_type_for_display = "--" # Display "--" for xcvrAbsent state
            
            # --- Apply output formatting for Port and Status columns ---
            display_interface_name = interface_name.replace("Ethernet", "Eth")
            
            # Truncate display_state to COL_WIDTHS["Status"] characters
            display_state = original_state.replace("xcvrAbsent", "xcvrAbsen") # First replace for consistent string
            display_state = display_state[:COL_WIDTHS["Status"]] # Then truncate

            # Construct the output line parts
            line_parts = []
            line_parts.append(display_interface_name.ljust(COL_WIDTHS["Port"]))
            line_parts.append("".ljust(COL_WIDTHS["Name"])) # Name is often empty, or not available in status json
            line_parts.append(display_state.ljust(COL_WIDTHS["Status"])) # Use truncated display_state
            line_parts.append(intf_data["vlan"].ljust(COL_WIDTHS["Vlan"]))
            line_parts.append(intf_data["duplex"].ljust(COL_WIDTHS["Duplex"]))
            line_parts.append(intf_data["speed"].ljust(COL_WIDTHS["Speed"]))
            line_parts.append(final_type_for_display.ljust(COL_WIDTHS["Type"]))
            
            # Join with a single space between each part
            modified_status_output_lines.append(" ".join(line_parts))
                
        print("\n--- Modified Interface Status ---")
        print("\n".join(modified_status_output_lines))

    except Exception as e:
        print(f"ERROR: processing 'show interface status | json' command: {e}", file=sys.stderr)


if __name__ == "__main__":
    # Check for help arguments first
    if len(sys.argv) > 1 and sys.argv[1] in ("?", "-h", "--help"):
        display_help()

    # Check for debug flag and remove it from argv for further processing
    if "-D" in sys.argv:
        DEBUG_MODE = True
        sys.argv.remove("-D")

    # Define variables to store the interface name and details flag
    interface_to_check = ""
    include_details_flag = False
    is_status_command = False

    # Check for command-line arguments
    if len(sys.argv) < 2: # No command-line arguments provided (after removing -D)
        print("Error: Missing required argument <interface_name> or 'status'.")
        display_help() # Display help and exit
    
    if sys.argv[1].lower() == "status":
        is_status_command = True
        if len(sys.argv) > 2: # "status" command should not have more arguments
            print("Error: 'status' command does not accept additional arguments.")
            display_help()
    else: # Single interface mode
        interface_to_check = sys.argv[1]
        if len(sys.argv) > 2:
            if sys.argv[2].lower() == "details":
                include_details_flag = True
            else: # Unknown argument
                print(f"Error: Unknown argument '{sys.argv[2]}'. Did you mean 'details'?")
                display_help()
        elif len(sys.argv) > 3: # Too many arguments for single interface
            print("Error: Too many arguments for single interface lookup.")
            display_help()

    if is_status_command:
        process_status_command()
    else:
        # Call the function and print the result, passing the interface name and details flag
        result = process_single_interface_sprom(interface_to_check, include_details_flag)
        print("\n--- Collected and Modified Transceiver Information ---")
        print(result)