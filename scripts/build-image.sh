#!/bin/sh
set -eu

if [ "$#" -gt 1 ]; then
    printf 'Usage: %s [IMAGE_TAG]\n' "$0" >&2
    exit 2
fi

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
repo_dir=$(CDPATH= cd -- "$script_dir/.." && pwd)
image_tag=${1:-craft-openapi-wrapper:local}

# The webhook URL grants deployment access. Read it as data, never source it.
# An exported URL takes precedence over the optional repository-local file.
webhook_url=${PORTAINER_WEBHOOK_URL-}
if [ "${PORTAINER_WEBHOOK_URL+x}" != x ] && [ -f "$repo_dir/.portainer-webhook" ]; then
    webhook_url=$(cat "$repo_dir/.portainer-webhook")
    if [ -z "$webhook_url" ]; then
        printf 'The .portainer-webhook file is empty.\n' >&2
        exit 2
    fi
fi

if [ -n "$webhook_url" ]; then
    # Reject curl-config metacharacters and require the bare stack webhook URL.
    case "$webhook_url" in
        *[[:space:][:cntrl:]]*|*\"*|*\\*|*\?*|*\#*|*@*)
            printf 'Use a bare Portainer stack webhook URL without credentials or query parameters.\n' >&2
            exit 2
            ;;
    esac
    case "$webhook_url" in
        https://*/api/stacks/webhooks/?*|http://*/api/stacks/webhooks/?*) ;;
        *)
            printf 'Expected an HTTP(S) Portainer /api/stacks/webhooks/ URL.\n' >&2
            exit 2
            ;;
    esac
    if ! command -v curl >/dev/null 2>&1; then
        printf 'curl is required when a Portainer webhook is configured.\n' >&2
        exit 2
    fi
fi

docker build --tag "$image_tag" "$repo_dir"

if [ -n "$webhook_url" ]; then
    printf 'Image built. Requesting a Portainer stack update without pulling images...\n'
    # Feed the secret URL through stdin so it is absent from curl's process arguments.
    # -q disables .curlrc; no redirects, retries, response bodies, or raw errors are exposed.
    if ! webhook_status=$(printf 'url = "%s?pullimage=false"\n' "$webhook_url" |
        curl -q --config - --request POST --silent --output /dev/null \
            --write-out '%{http_code}' --connect-timeout 10 --max-time 60 \
            --proto '=http,https' --retry 0 --stderr /dev/null); then
        printf 'Image built, but the Portainer webhook request failed. Check the stack before retrying.\n' >&2
        exit 1
    fi
    case "$webhook_status" in
        2[0-9][0-9])
            printf 'Portainer accepted the update request. Check deployment status, health, and logs in Portainer.\n'
            ;;
        *)
            printf 'Image built, but Portainer did not accept the webhook (HTTP %s).\n' "$webhook_status" >&2
            exit 1
            ;;
    esac
fi
