#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
    printf 'Usage: %s [IMAGE_TAG]\n' "$0" >&2
    exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
image_tag=${1:-craft-openapi-wrapper:local}

exec docker build --tag "$image_tag" "$repo_dir"
