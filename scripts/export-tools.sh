#!/bin/sh
# Export identifiable tool sources for manual installation; leave tracked files unchanged.
set -eu
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
[ "$#" -eq 0 ] || { printf 'Usage: export-tools.sh\n' >&2; exit 2; }
output="$script_dir/../build/openwebui"
mkdir -p -- "$output"
for adapter in space documents daily; do
    source="$output/craft_${adapter}_tool.py"
    "$script_dir/build-id.sh" "$adapter" --stamp > "$source"
    printf '%s: %s\n' "$source" "$("$script_dir/build-id.sh" "$adapter")"
done
