#!/bin/bash
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
#
# ccusage-export.sh — Exportiert ccusage-Daten fuer das KI-Dashboard.
#
#   ccusage-export.sh daily     laufenden + vorigen Monat neu schreiben
#   ccusage-export.sh weekly    Blocks und Sessions archivieren (PFLICHT, s.u.)
#   ccusage-export.sh monthly   abgeschlossenen Vormonat einfrieren
#
# Blocks und Sessions stammen aus den JSONL-Dateien unter ~/.claude, deren
# Verlauf nur rund 31 Tage zurueckreicht. Faellt der Wochenlauf laenger als
# einen Monat aus, ist der Zeitraum unwiederbringlich verloren. Tages- und
# Projektdaten lassen sich dagegen jederzeit neu erzeugen.
#
# NUR macOS. Die Datumsarithmetik benutzt die BSD-Form von date
# (date -v1d -v-1m). Auf Linux bricht das Skript in der ersten Datumszeile
# ab. Bewusst nicht portiert: der Nachbau waere ohne Linux-Rechner nicht
# pruefbar, und ein ungepruefter Nachbau ist schlechter als eine ehrliche
# Beschraenkung.

set -euo pipefail

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="${CCUSAGE_DATA_DIR:-$HOME/Library/Application Support/Claude-Code-Usage}"
LOG_DIR="$DATA_DIR/logs"
LOOKBACK_DAYS="${CCUSAGE_LOOKBACK_DAYS:-14}"   # Ueberlappung: ein verpasster Lauf heilt sich selbst

# --- ccusage finden -----------------------------------------------------------
# launchd startet mit PATH=/usr/bin:/bin:/usr/sbin:/sbin, nvm ist dort unsichtbar.
find_ccusage() {
    if [[ -n "${CCUSAGE_BIN:-}" && -x "$CCUSAGE_BIN" ]]; then
        printf '%s' "$CCUSAGE_BIN"; return 0
    fi
    local c
    for c in "$HOME"/.nvm/versions/node/*/bin/ccusage; do
        [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
    done
    for c in /opt/homebrew/bin/ccusage /usr/local/bin/ccusage; do
        [[ -x "$c" ]] && { printf '%s' "$c"; return 0; }
    done
    command -v ccusage 2>/dev/null && return 0
    return 1
}

MODE="${1:-}"
case "$MODE" in
    daily|weekly|monthly) ;;
    *) echo "Aufruf: $(basename "$0") {daily|weekly|monthly}" >&2; exit 2 ;;
esac

mkdir -p "$DATA_DIR"/{projects,blocks,sessions,logs}
LOG="$LOG_DIR/$MODE.log"

log() { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >>"$LOG"; }

CCUSAGE="$(find_ccusage)" || {
    log "FEHLER: ccusage nicht gefunden. CCUSAGE_BIN setzen."
    echo "ccusage nicht gefunden. Setze CCUSAGE_BIN auf den Pfad der Binary." >&2
    exit 1
}

# ccusage traegt den Shebang '#!/usr/bin/env node'. launchd startet ohne den
# nvm-Pfad, node waere sonst unsichtbar. node liegt im selben bin-Verzeichnis.
PATH="$(dirname "$CCUSAGE"):$PATH"
export PATH

# --- Atomar schreiben, nur nach Pruefung -------------------------------------
# Zwei Gefahren werden abgefangen:
#   1. Abgebrochener/leerer Lauf darf eine gute Datei nicht ueberschreiben.
#   2. RUECKSCHRITT: ein Export, der weniger enthaelt als die vorhandene Datei,
#      wuerde Daten loeschen. Er wird verworfen.
#      Bewusst zulassen: CCUSAGE_ALLOW_SHRINK=1
#
# Wie ein Rueckschritt zu bewerten ist, haengt vom Lauf ab. Erster Parameter:
#
#   strict  Rueckschritt ist ein Fehler. Fuer den laufenden Monat, der nur
#           wachsen kann; schrumpft er, stimmt etwas nicht.
#   merge   Der Export wird ueber die bestehende Datei gelegt statt sie zu
#           ersetzen. Fuer das rollierende Wochenfenster, dessen Anfang bei
#           jedem Lauf weiterwandert und sonst den herausgefallenen Tag
#           mitnaehme. Die Datei kann so nur wachsen.
#   freeze  Rueckschritt bedeutet: das Archiv ist vollstaendiger als das, was
#           ccusage heute noch hergibt. Die Datei bleibt stehen, der Lauf gilt
#           als erfolgreich. Fuer abgeschlossene Vormonate.
export_json() {
    local policy="$1"; shift
    local target="$1"; shift
    local tmp; tmp="$(mktemp "${target}.XXXXXX")"
    local merged=""
    trap 'rm -f "$tmp" "$merged"' RETURN
    local label; label="$(basename "$(dirname "$target")")/$(basename "$target")"

    if ! "$CCUSAGE" "$@" >"$tmp" 2>>"$LOG"; then
        log "FEHLER: 'ccusage $*' schlug fehl -> $label unveraendert"
        return 1
    fi

    if [[ "$policy" == merge ]]; then
        merged="$(mktemp "${target}.XXXXXX")"
        local bilanz
        if ! bilanz="$(python3 "$SELF_DIR/ccusage-merge.py" "$tmp" "$target" "$merged" 2>>"$LOG")"; then
            log "ABBRUCH: Zusammenfuehren fehlgeschlagen -> $label unveraendert"
            return 1
        fi
        log "MERGE $label  ($bilanz)"
        mv "$merged" "$tmp"
        merged=""
    fi

    local verdict rc=0
    verdict="$(python3 "$SELF_DIR/ccusage-check.py" "$tmp" "$target" 2>>"$LOG")" || rc=$?
    if [[ $rc -eq 3 && "$policy" == freeze ]]; then
        log "EINGEFROREN: $label unveraendert, das Archiv ist vollstaendiger"
        return 0
    fi
    if [[ $rc -ne 0 ]]; then
        log "ABBRUCH: $label unveraendert"
        return 1
    fi

    local bytes; bytes="$(wc -c <"$tmp" | tr -d ' ')"
    mv "$tmp" "$target"
    log "OK   $label  ${bytes} Bytes  ($verdict)  [$*]"
}

# --- Datumsbausteine (BSD date) -----------------------------------------------
CUR_MONTH="$(date +%Y-%m)"                       # 2026-09
PREV_MONTH="$(date -v1d -v-1m +%Y-%m)"           # 2026-08
PREV_FIRST="$PREV_MONTH-01"
PREV_LAST="$(date -v1d -v-1d +%Y-%m-%d)"         # letzter Tag des Vormonats
SINCE_LOOKBACK="$(date -v-${LOOKBACK_DAYS}d +%Y-%m-%d)"
ISO_WEEK="$(date +%G-W%V)"                       # 2026-W36
compact() { printf '%s' "${1//-/}"; }            # 2026-09-01 -> 20260901

log "--- Start ($MODE), ccusage=$CCUSAGE"
rc=0

case "$MODE" in

daily)
    # Laufender Monat. Zusaetzlich der Vormonat, damit Aktivitaet nach
    # Mitternacht am Monatsersten nicht in der eingefrorenen Datei fehlt.
    export_json strict "$DATA_DIR/$CUR_MONTH.json" \
        daily --json --by-agent -s "$CUR_MONTH-01" || rc=1
    export_json strict "$DATA_DIR/projects/$CUR_MONTH.json" \
        claude daily --json -i -s "$(compact "$CUR_MONTH-01")" || rc=1

    if [[ "$(date +%d)" -le 03 ]]; then
        export_json freeze "$DATA_DIR/$PREV_MONTH.json" \
            daily --json --by-agent -s "$PREV_FIRST" -u "$PREV_LAST" || rc=1
        export_json freeze "$DATA_DIR/projects/$PREV_MONTH.json" \
            claude daily --json -i -s "$(compact "$PREV_FIRST")" -u "$(compact "$PREV_LAST")" || rc=1
    fi
    ;;

weekly)
    # Rollierendes Fenster mit Ueberlappung. Beim Einlesen ueber blocks[].id
    # bzw. sessionId deduplizieren, spaeterer Export gewinnt.
    export_json merge "$DATA_DIR/blocks/$ISO_WEEK.json" \
        blocks --json -s "$(compact "$SINCE_LOOKBACK")" || rc=1
    export_json merge "$DATA_DIR/sessions/$ISO_WEEK.json" \
        claude session --json -s "$(compact "$SINCE_LOOKBACK")" || rc=1
    ;;

monthly)
    export_json freeze "$DATA_DIR/$PREV_MONTH.json" \
        daily --json --by-agent -s "$PREV_FIRST" -u "$PREV_LAST" || rc=1
    export_json freeze "$DATA_DIR/projects/$PREV_MONTH.json" \
        claude daily --json -i -s "$(compact "$PREV_FIRST")" -u "$(compact "$PREV_LAST")" || rc=1
    ;;
esac

# Log auf die letzten 2000 Zeilen kuerzen
if [[ -f "$LOG" ]] && [[ "$(wc -l <"$LOG")" -gt 2000 ]]; then
    tail -n 2000 "$LOG" >"$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

log "--- Ende ($MODE), Status $rc"
exit $rc
