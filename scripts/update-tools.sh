#!/bin/sh
# Update existing Open WebUI tools from this checkout. No Python runtime required.
set -eu
umask 077

fail() {
    printf 'Tool update error: %s\n' "$1" >&2
    if [ -n "${mutation_id:-}" ]; then
        printf '%s: update may have been applied; inspect the tool before retrying.\n' "$mutation_id" >&2
    fi
    exit 1
}

if [ "${1:-}" = --help ] || [ "${1:-}" = -h ]; then
    printf '%s\n' 'Usage: scripts/update-tools.sh --list | --tool ADAPTER=TOOL_ID ... [--dry-run | --apply]' \
        'Adapters: space, documents, daily. Preview is the default.' \
        'Credentials: .openwebui-tools.env; exported OWUI_* values override the file.'
    exit 0
fi
for command in curl jq; do
    command -v "$command" >/dev/null 2>&1 || fail "Install $command first."
done
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd -- "$script_dir/.."
tmp=$(mktemp -d "${TMPDIR:-/tmp}/craft-tools.XXXXXX")
trap 'rm -rf "$tmp"' 0
trap 'exit 130' INT
trap 'exit 143' HUP TERM
: > "$tmp/selections"
mode=preview
list=false
explicit_mode=
while [ "$#" -gt 0 ]; do
    case "$1" in
        --list) list=true ;;
        --apply|--dry-run)
            [ -z "$explicit_mode" ] || [ "$explicit_mode" = "$1" ] || fail 'Choose --apply or --dry-run.'
            explicit_mode=$1
            [ "$1" != --apply ] || mode=apply ;;
        --tool)
            [ "$#" -ge 2 ] || fail '--tool requires ADAPTER=TOOL_ID.'
            shift
            case "$1" in *=*) ;; *) fail 'Use --tool ADAPTER=TOOL_ID.' ;; esac
            adapter=${1%%=*}
            id=${1#*=}
            case "$adapter" in space|documents|daily) ;; *) fail 'Unknown adapter.' ;; esac
            case "$id" in ''|*[!a-z0-9_]*|[0-9]*) fail 'Tool IDs must be lowercase identifiers.' ;; esac
            if cut -f2 "$tmp/selections" | grep -Fxq "$id"; then fail 'Duplicate target tool ID.'; fi
            printf '%s\t%s\n' "$adapter" "$id" >> "$tmp/selections" ;;
        *) fail 'Unknown argument; use --help.' ;;
    esac
    shift
done
if [ "$list" = true ]; then
    [ ! -s "$tmp/selections" ] && [ "$mode" != apply ] || fail '--list cannot update tools.'
else
    [ -s "$tmp/selections" ] || fail 'Select --list or --tool ADAPTER=TOOL_ID.'
fi

# Read data, never source/eval the credential file. Simple quoted values are supported.
file_url= file_token= file_timeout=60
if [ -f .openwebui-tools.env ]; then
    while IFS= read -r line || [ -n "$line" ]; do
        line=$(printf '%s\n' "$line" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
        case "$line" in ''|\#*) continue ;; *=*) ;; *) fail 'Invalid credential-file line.' ;; esac
        key=$(printf '%s\n' "${line%%=*}" | sed 's/[[:space:]]*$//')
        value=$(printf '%s\n' "${line#*=}" | sed 's/^[[:space:]]*//')
        case "$value" in
            \"*\") value=${value#\"}; value=${value%\"} ;;
            \'*\') value=${value#\'}; value=${value%\'} ;;
        esac
        case "$key" in
            OWUI_URL) file_url=$value ;;
            OWUI_API_TOKEN) file_token=$value ;;
            OWUI_TIMEOUT_SECONDS) file_timeout=$value ;;
            *) fail 'Unknown credential-file setting.' ;;
        esac
    done < .openwebui-tools.env
fi
OWUI_URL=${OWUI_URL-$file_url}
OWUI_API_TOKEN=${OWUI_API_TOKEN-$file_token}
OWUI_TIMEOUT_SECONDS=${OWUI_TIMEOUT_SECONDS-$file_timeout}
case "$OWUI_URL" in http://?*|https://?*) ;; *) fail 'Configure OWUI_URL in .openwebui-tools.env.' ;; esac
case "$OWUI_URL" in *\?*|*\#*|*@*|*\\*) fail 'OWUI_URL must have no credentials, query, or fragment.' ;; esac
if printf '%s' "$OWUI_URL" | LC_ALL=C grep -q '[[:space:][:cntrl:]]'; then fail 'Invalid OWUI_URL.'; fi
[ -n "$OWUI_API_TOKEN" ] || fail 'Configure OWUI_API_TOKEN in .openwebui-tools.env.'
if printf '%s' "$OWUI_API_TOKEN" | LC_ALL=C grep -q '[^!-~]'; then fail 'Invalid OWUI_API_TOKEN.'; fi
printf '%s' "$OWUI_TIMEOUT_SECONDS" | jq -eRs 'tonumber | . > 0 and . < 1e308' >/dev/null 2>&1 \
    || fail 'OWUI_TIMEOUT_SECONDS must be positive and finite.'
export OWUI_API_TOKEN
# JSON escaping creates curl config safely; the token never enters process arguments.
jq -nr '"header = " + ("Authorization: Bearer " + env.OWUI_API_TOKEN | @json)' > "$tmp/auth"
base=${OWUI_URL%/}/api/v1/tools

request() {
    method=$1 path=$2 output=$3
    set -- -q --config "$tmp/auth" --silent --stderr /dev/null \
        --connect-timeout 10 --max-time "$OWUI_TIMEOUT_SECONDS" --retry 0 \
        --proto '=http,https' --max-filesize 8388608 --request "$method" \
        --output "$output" --write-out '%{http_code}'
    if [ "$method" = POST ]; then
        set -- "$@" --header 'Content-Type: application/json' --data-binary "@$tmp/$id.payload"
    fi
    status=$(curl "$@" "$base$path") || fail 'Open WebUI request failed.'
    [ "$status" = 200 ] || fail "Open WebUI returned HTTP $status."
    jq empty "$output" >/dev/null 2>&1 || fail 'Open WebUI returned invalid JSON.'
}
read_tool() {
    request GET "/id/$id" "$1"
    jq -e --arg id "$id" '
        .id == $id and .write_access == true and (.content | type) == "string"
        and (.name | type) == "string" and (.meta | type) == "object"
        and (.access_grants | type) == "array"
    ' "$1" >/dev/null 2>&1 || fail "$id: source unavailable or lacking write access."
}
if [ "$list" = true ]; then
    request GET / "$tmp/list"
    jq '[.[] | {id,name}]' "$tmp/list" 2>/dev/null || fail 'Invalid tool listing.'
    exit 0
fi

# Preflight all selected tools before writing any. Capture the local source for each request.
while IFS="$(printf '\t')" read -r adapter id; do
    source="integrations/openwebui/craft_${adapter}_tool.py"
    read_tool "$tmp/$id.before"
    jq --rawfile content "$source" '{id,name,content:$content,meta}' "$tmp/$id.before" \
        > "$tmp/$id.payload" 2>/dev/null || fail 'Cannot read local tool source.'
done < "$tmp/selections"
while IFS="$(printf '\t')" read -r adapter id; do
    if jq -e --slurpfile planned "$tmp/$id.payload" '.content == $planned[0].content' \
        "$tmp/$id.before" >/dev/null; then
        printf '%s: unchanged\n' "$id"
        continue
    fi
    if [ "$mode" = preview ]; then
        printf '%s: would update\n' "$id"
        continue
    fi
    read_tool "$tmp/$id.current"
    jq -S . "$tmp/$id.before" > "$tmp/before"
    jq -S . "$tmp/$id.current" > "$tmp/current"
    cmp -s "$tmp/before" "$tmp/current" || fail "$id: changed since preflight; preview again."
    # No access_grants or Valves in the payload: preserve the installed configuration.
    mutation_id=$id
    request POST "/id/$id/update" "$tmp/result"
    read_tool "$tmp/$id.after"
    jq -e --slurpfile planned "$tmp/$id.payload" --slurpfile old "$tmp/$id.before" '
        .content == $planned[0].content and .name == $old[0].name
        and (.access_grants | sort) == ($old[0].access_grants | sort)
        and .meta.description == $old[0].meta.description and .meta.i18n == $old[0].meta.i18n
    ' "$tmp/$id.after" >/dev/null || fail "$id: saved source or metadata did not match."
    mutation_id=
    printf '%s: updated and verified\n' "$id"
done < "$tmp/selections"
[ "$mode" = apply ] || printf '%s\n' 'Preview only; use --apply to save.'
