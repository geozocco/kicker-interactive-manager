#!/bin/bash

set -euo pipefail

PLUGIN_NAME="kicker-interactive-manager"
ARCHIVE_URL="${ARCHIVE_URL:-https://github.com/geozocco/kicker-interactive-manager/archive/refs/heads/main.zip}"
INSTALL_ROOT="${INSTALL_ROOT:-$HOME/.codex/marketplaces/$PLUGIN_NAME}"
NO_LAUNCH="${NO_LAUNCH:-0}"
TEMP_PARENT="${TMPDIR:-/tmp}"
TEMP_ROOT="$(/usr/bin/mktemp -d "${TEMP_PARENT%/}/$PLUGIN_NAME.XXXXXX")"
ARCHIVE_PATH="$TEMP_ROOT/marketplace.zip"
EXTRACT_ROOT="$TEMP_ROOT/extracted"
BACKUP_PATH=""

cleanup() {
    if [[ -n "${TEMP_ROOT:-}" && -d "$TEMP_ROOT" ]]; then
        /bin/rm -rf "$TEMP_ROOT"
    fi
}
trap cleanup EXIT

echo "Lade das kicker Interactive Marketplace herunter ..."
/bin/mkdir -p "$EXTRACT_ROOT"
/usr/bin/curl --fail --location --silent --show-error "$ARCHIVE_URL" --output "$ARCHIVE_PATH"
/usr/bin/ditto -x -k "$ARCHIVE_PATH" "$EXTRACT_ROOT"

SOURCE_ROOT=""
SOURCE_COUNT=0
for CANDIDATE in "$EXTRACT_ROOT"/*; do
    [[ -d "$CANDIDATE" ]] || continue
    [[ -f "$CANDIDATE/.agents/plugins/marketplace.json" ]] || continue
    SOURCE_ROOT="$CANDIDATE"
    SOURCE_COUNT=$((SOURCE_COUNT + 1))
done

if [[ "$SOURCE_COUNT" -ne 1 ]]; then
    echo "Das heruntergeladene Archiv enthaelt kein eindeutiges Codex-Marketplace." >&2
    exit 1
fi

SOURCE_MARKETPLACE="$SOURCE_ROOT/.agents/plugins/marketplace.json"
SOURCE_PLUGIN_MANIFEST="$SOURCE_ROOT/plugins/$PLUGIN_NAME/.codex-plugin/plugin.json"
if [[ ! -f "$SOURCE_PLUGIN_MANIFEST" ]]; then
    echo "Das Plugin-Manifest fehlt im heruntergeladenen Marketplace." >&2
    exit 1
fi

/usr/bin/plutil -convert xml1 -o /dev/null "$SOURCE_MARKETPLACE"
/usr/bin/plutil -convert xml1 -o /dev/null "$SOURCE_PLUGIN_MANIFEST"
MARKETPLACE_NAME="$(/usr/bin/plutil -extract name raw -o - "$SOURCE_MARKETPLACE")"
MARKETPLACE_PLUGIN="$(/usr/bin/plutil -extract plugins.0.name raw -o - "$SOURCE_MARKETPLACE")"
if [[ "$MARKETPLACE_NAME" != "$PLUGIN_NAME" || "$MARKETPLACE_PLUGIN" != "$PLUGIN_NAME" ]]; then
    echo "Das Marketplace enthaelt nicht das erwartete Plugin." >&2
    exit 1
fi

INSTALL_PARENT="$(/usr/bin/dirname "$INSTALL_ROOT")"
INSTALL_NAME="$(/usr/bin/basename "$INSTALL_ROOT")"
/bin/mkdir -p "$INSTALL_PARENT"
INSTALL_PARENT="$(cd "$INSTALL_PARENT" && pwd -P)"
INSTALL_ROOT="$INSTALL_PARENT/$INSTALL_NAME"

if [[ -e "$INSTALL_ROOT" ]]; then
    BACKUP_PATH="$INSTALL_ROOT.backup-$(/bin/date +%Y%m%d%H%M%S)"
    if [[ -e "$BACKUP_PATH" ]]; then
        BACKUP_PATH="$BACKUP_PATH-$$"
    fi
    /bin/mv "$INSTALL_ROOT" "$BACKUP_PATH"
fi

if ! /bin/mv "$SOURCE_ROOT" "$INSTALL_ROOT"; then
    if [[ -n "$BACKUP_PATH" && ! -e "$INSTALL_ROOT" ]]; then
        /bin/mv "$BACKUP_PATH" "$INSTALL_ROOT"
    fi
    exit 1
fi

MARKETPLACE_PATH="$INSTALL_ROOT/.agents/plugins/marketplace.json"
ENCODED_MARKETPLACE_PATH="$(
    /usr/bin/osascript -l JavaScript \
        -e 'function run(argv) { return encodeURIComponent(argv[0]); }' \
        "$MARKETPLACE_PATH"
)"
INSTALL_LINK="codex://plugins/$PLUGIN_NAME?marketplacePath=$ENCODED_MARKETPLACE_PATH"

echo
echo "Marketplace installiert: $INSTALL_ROOT"
if [[ -n "$BACKUP_PATH" ]]; then
    echo "Vorherige Version gesichert: $BACKUP_PATH"
fi

if [[ "$NO_LAUNCH" == "1" ]]; then
    echo "Codex-Link: $INSTALL_LINK"
else
    echo "Oeffne jetzt den Installationsdialog in Codex ..."
    if /usr/bin/open "$INSTALL_LINK"; then
        echo "In Codex bitte auf 'Plugin installieren' klicken."
    else
        echo "Codex konnte nicht automatisch geoeffnet werden." >&2
        echo "Diesen Link lokal auf diesem Mac oeffnen:"
        echo "$INSTALL_LINK"
    fi
fi
