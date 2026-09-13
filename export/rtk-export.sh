#!/bin/bash
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
#
# rtk-export.sh — Exportiert die Ersparnis-Statistik des rtk-Proxys fuer das
# KI-Dashboard.
#
# rtk ("Rust Token Killer") ist ein Proxy, der Token-Ersparnisse pro Tag
# mitschreibt (Befehl: rtk gain). Anders als ccusage braucht dieses Skript
# nur einen einzigen Lauf: es gibt kein rollierendes Wochenfenster und
# nichts, das archiviert werden muesste, was nicht ohnehin in derselben
# Monatsdatei steht.

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="${RTK_DATA_DIR:-$HOME/Library/Application Support/Claude-Code-Usage}"
LOG_DIR="$DATA_DIR/logs"
TARGET_DIR="$DATA_DIR/rtk"

mkdir -p "$LOG_DIR" "$TARGET_DIR"
LOG="$LOG_DIR/rtk.log"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

# --- rtk finden ---------------------------------------------------------------
# Der Name 'rtk' kollidiert mit 'reachingforthejack/rtk' (Rust Type Kit). Eine
# Verwechslung faellt ohne Pruefung erst im Dashboard als leerer Reiter auf.
find_rtk() {
    if [[ -n "${RTK_BIN:-}" && -x "$RTK_BIN" ]]; then
        printf '%s' "$RTK_BIN"; return 0
    fi
    local c
    for c in /opt/homebrew/bin/rtk /usr/local/bin/rtk; do
        [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
    done
    command -v rtk 2>/dev/null && return 0
    return 1
}

log "--- Start"

RTK="$(find_rtk)" || {
    log "ABBRUCH: rtk nicht gefunden. RTK_BIN setzen. rtk/ unveraendert"
    echo "rtk nicht gefunden. Setze RTK_BIN auf den Pfad der Binary." >&2
    exit 1
}

# Nur pruefen, dass ueberhaupt JSON zurueckkommt -- ohne --all traegt die
# Ausgabe nur 'summary', ein Schluessel 'daily' ist hier nicht zu erwarten.
PROBE="$("$RTK" gain --format json 2>>"$LOG")" || {
    log "ABBRUCH: rtk nicht gefunden oder liefert kein JSON ($RTK). rtk/ unveraendert"
    echo "rtk liefert kein JSON: $RTK" >&2
    exit 1
}
if ! printf '%s' "$PROBE" | python3 -c 'import json,sys; json.load(sys.stdin)' 2>>"$LOG"; then
    log "ABBRUCH: rtk nicht gefunden oder liefert kein JSON ($RTK). rtk/ unveraendert"
    echo "rtk liefert kein JSON: $RTK" >&2
    exit 1
fi

GAIN_TMP="$(mktemp "$TARGET_DIR/gain.XXXXXX")"
trap 'rm -f "$GAIN_TMP"' EXIT

if ! "$RTK" gain --all --format json >"$GAIN_TMP" 2>>"$LOG"; then
    log "ABBRUCH: 'rtk gain --all --format json' schlug fehl. rtk/ unveraendert"
    echo "'rtk gain --all --format json' schlug fehl." >&2
    exit 1
fi

if ! python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); sys.exit(0 if isinstance(d, dict) and isinstance(d.get("daily"), list) else 1)' "$GAIN_TMP" 2>>"$LOG"; then
    log "ABBRUCH: Ausgabe ist kein gueltiges JSON oder hat keinen Schluessel 'daily'. rtk/ unveraendert"
    echo "Ausgabe von 'rtk gain --all --format json' ist kein gueltiges JSON oder hat keinen Schluessel 'daily'." >&2
    exit 1
fi

rc=0
BILANZ="$(python3 "$SELF_DIR/rtk-merge.py" "$GAIN_TMP" "$TARGET_DIR" 2>>"$LOG")" || rc=$?
if [[ $rc -ne 0 ]]; then
    log "ABBRUCH: rtk-merge.py endete mit Exitcode $rc. rtk/ unveraendert"
    exit 1
fi

log "OK   $BILANZ"
log "--- Ende"
