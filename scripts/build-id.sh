#!/bin/sh
# Fingerprint public build inputs only. No credentials, Git history, or timestamps.
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd -- "$script_dir/.."
case "${1:-wrapper}" in
    wrapper) target=wrapper ;;
    space|documents|daily) target=$1 ;;
    *) printf 'Usage: build-id.sh [wrapper|space|documents|daily] [--stamp]\n' >&2; exit 2 ;;
esac
[ "$#" -le 2 ] && { [ "$#" -lt 2 ] || [ "$2" = --stamp ]; } || exit 2
[ "$target" != wrapper ] || [ "$#" -lt 2 ] || exit 2

if command -v sha256sum >/dev/null 2>&1; then
    checksum() { sha256sum "$@" | cut -d ' ' -f1; }
elif command -v shasum >/dev/null 2>&1; then
    checksum() { shasum -a 256 "$@" | cut -d ' ' -f1; }
else
    printf 'Install sha256sum or shasum to identify builds.\n' >&2
    exit 1
fi

if [ "$target" = wrapper ]; then
    release=$(sed -n 's/^version = "\([0-9][0-9.]*\)"$/\1/p' pyproject.toml)
    # File names and hashes make the result independent of checkout location.
    files=$(printf '%s\n' .dockerignore Dockerfile pyproject.toml uv.lock
        find src -type f -name '*.py' | LC_ALL=C sort)
    manifest=$(printf '%s\n' "$files" | while IFS= read -r file; do
        [ -f "$file" ] || exit 1
        digest=$(checksum "$file")
        [ -n "$digest" ] || exit 1
        printf '%s %s\n' "$file" "$digest"
    done)
    digest=$(printf '%s\n' "$manifest" | checksum)
else
    source="integrations/openwebui/craft_${target}_tool.py"
    release=$(sed -n 's/^version: \([0-9][0-9.]*\)$/\1/p' "$source")
    digest=$(checksum "$source")
fi
[ -n "$release" ] && [ "${#digest}" = 64 ] || exit 1
build_id="$release-dev.$(printf '%s' "$digest" | cut -c1-12)"
if [ "${2:-}" = --stamp ]; then
    sed "s/^version: $release\$/version: $build_id/" "$source"
else
    printf '%s\n' "$build_id"
fi
