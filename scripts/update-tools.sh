#!/bin/sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd -- "$script_dir/.."

exec uv run --locked python -m scripts.update_openwebui_tools "$@"
