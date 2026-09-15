#!/bin/bash
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
#
# Richtet die Anwendung frisch ein: Datenverzeichnis, Exportskripte,
# config.toml und auf Wunsch die vier launchd-Jobs.
#
# Das Repository ist die Quelle der Exportskripte, das Datenverzeichnis ihr
# Einsatzort. Die launchd-Jobs rufen die Kopien unter <daten>/bin auf, nicht
# die Dateien im Repository: ein Arbeitsstand mitten im Umbau soll den
# naechtlichen Export nicht mitreissen.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DATA_DIR="$HOME/Library/Application Support/Claude-Code-Usage"
LABEL_PREFIX=""
WITH_LAUNCHAGENTS=0
FORCE=0
DRY_RUN=0
DEMO_MODE=0

SKRIPTE=(ccusage-export.sh rtk-export.sh ccusage-check.py ccusage-merge.py rtk-merge.py)
JOBS=(ccusage-daily ccusage-weekly ccusage-monthly rtk-daily)
UNTERVERZEICHNISSE=(bin logs projects sessions blocks rtk)

# Gesammelte Hinweise. Sie erscheinen am Ende noch einmal, damit ein
# uebersprungener Schritt nicht in der laufenden Ausgabe untergeht.
HINWEISE=()

hinweis() { HINWEISE+=("$1"); printf '  Hinweis: %s\n' "$1"; }
schritt() { printf '\n== %s\n' "$1"; }
tat()     { printf '  %s\n' "$1"; }
wuerde()  { printf '  [Trockenlauf] %s\n' "$1"; }

fehler() {
    printf 'Fehler: %s\n' "$1" >&2
    exit "${2:-1}"
}

hilfe() {
    cat <<'ENDE'
install.sh - richtet das Token-Usage-Dashboard ein.

Aufruf:
  ./install.sh [Optionen]

Optionen:
  --with-launchagents   Richtet zusaetzlich die vier launchd-Jobs ein, die
                        den Export nachts anstossen. Nur auf macOS.
  --label-prefix NAME   Praefix der Job-Labels, etwa com.beispiel. Nur
                        zusammen mit --with-launchagents. Vorgabe: com.<Benutzer>
  --data-dir PFAD       Datenverzeichnis. Vorgabe:
                        ~/Library/Application Support/Claude-Code-Usage
  --force               Ueberschreibt abweichende Skripte unter <daten>/bin
                        mit dem Stand des Repositories.
  --dry-run             Zeigt nur, was geschehen wuerde. Aendert nichts.
  --demo                Aktiviert den Demo-Modus und erzeugt Beispieldaten.
                        Sinnvoll, wenn weder ccusage noch rtk installiert ist.
  -h, --help            Diese Hilfe.

Ohne --with-launchagents greift das Skript nicht in launchd ein.

Beispiele:
  ./install.sh
  ./install.sh --demo
  ./install.sh --with-launchagents --label-prefix com.beispiel
  ./install.sh --with-launchagents --dry-run
ENDE
}

# --- Optionen -------------------------------------------------------------

while [ $# -gt 0 ]; do
    case "$1" in
        --with-launchagents) WITH_LAUNCHAGENTS=1 ;;
        --force)             FORCE=1 ;;
        --dry-run)           DRY_RUN=1 ;;
        --demo)              DEMO_MODE=1 ;;
        -h|--help)           hilfe; exit 0 ;;
        --label-prefix)
            [ $# -ge 2 ] || fehler "--label-prefix braucht einen Wert."
            LABEL_PREFIX="$2"; shift ;;
        --data-dir)
            [ $# -ge 2 ] || fehler "--data-dir braucht einen Wert."
            DATA_DIR="$2"; shift ;;
        *)
            printf 'Unbekannte Option: %s\n\n' "$1" >&2
            hilfe >&2
            exit 1 ;;
    esac
    shift
done

if [ -n "$LABEL_PREFIX" ] && [ "$WITH_LAUNCHAGENTS" -eq 0 ]; then
    fehler "--label-prefix wirkt nur zusammen mit --with-launchagents."
fi
[ -n "$LABEL_PREFIX" ] || LABEL_PREFIX="com.$(id -un)"

# ~ expandieren, ohne eval: der Wert kommt von der Befehlszeile.
case "$DATA_DIR" in
    "~") DATA_DIR="$HOME" ;;
    "~/"*) DATA_DIR="$HOME/${DATA_DIR#\~/}" ;;
esac

printf 'Token-Usage-Dashboard einrichten\n'
printf '  Repository:        %s\n' "$REPO_DIR"
printf '  Datenverzeichnis:  %s\n' "$DATA_DIR"
if [ "$WITH_LAUNCHAGENTS" -eq 1 ]; then
    printf '  launchd-Jobs:      ja, Praefix %s\n' "$LABEL_PREFIX"
else
    printf '  launchd-Jobs:      nein (--with-launchagents nicht gesetzt)\n'
fi
[ "$DRY_RUN" -eq 1 ] && printf '  Trockenlauf:       es wird nichts geaendert\n'

# --- Voraussetzungen ------------------------------------------------------

schritt "Voraussetzungen"

command -v python3 >/dev/null 2>&1 || fehler "python3 fehlt."
PY_VERSION="$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' \
    || fehler "python3 $PY_VERSION ist zu alt, gebraucht wird 3.11 oder neuer."
tat "python3 $PY_VERSION"

if [ "$(uname -s)" != "Darwin" ]; then
    hinweis "Die Exportkette laeuft nur auf macOS. Die Skripte werden trotzdem abgelegt, lassen sich hier aber nicht ausfuehren."
fi

LIVE_WERKZEUGE=0
for werkzeug in ccusage rtk; do
    if command -v "$werkzeug" >/dev/null 2>&1; then
        tat "$werkzeug gefunden: $(command -v "$werkzeug")"
        LIVE_WERKZEUGE=$((LIVE_WERKZEUGE + 1))
    else
        hinweis "$werkzeug ist nicht im Pfad. Das Dashboard laeuft trotzdem, es zeigt dann nur, was schon im Datenverzeichnis liegt."
    fi
done

if [ "$LIVE_WERKZEUGE" -eq 0 ]; then
    printf '\n  Fuer Live-Daten muss mindestens eines der Programme ccusage oder RTK installiert sein.\n'
    if [ "$DEMO_MODE" -eq 1 ]; then
        tat "Demo-Modus aktiviert (--demo)."
    else
        while true; do
            printf '  [a] Installation abbrechen  [d] Demo-Modus aktivieren: '
            if ! IFS= read -r antwort; then
                fehler "Keine Auswahl moeglich. Installation abgebrochen; fuer den Demo-Modus erneut mit --demo aufrufen." 2
            fi
            case "$antwort" in
                a|A) fehler "Installation auf Wunsch abgebrochen." 2 ;;
                d|D) DEMO_MODE=1; tat "Demo-Modus aktiviert."; break ;;
                *) printf '  Bitte a oder d eingeben.\n' ;;
            esac
        done
    fi
fi

if [ "$DEMO_MODE" -eq 1 ] && [ "$WITH_LAUNCHAGENTS" -eq 1 ]; then
    hinweis "launchd-Jobs werden im Demo-Modus uebersprungen, weil Demo-Daten keine Live-Exporte brauchen."
    WITH_LAUNCHAGENTS=0
fi

if [ "$WITH_LAUNCHAGENTS" -eq 1 ] && [ "$(uname -s)" != "Darwin" ]; then
    fehler "--with-launchagents gibt es nur auf macOS; hier laeuft $(uname -s)." 2
fi

if [ "$DEMO_MODE" -eq 1 ]; then
    for vorhandene_datendatei in "$DATA_DIR"/*.json \
            "$DATA_DIR"/projects/*.json "$DATA_DIR"/sessions/*.json \
            "$DATA_DIR"/blocks/*.json "$DATA_DIR"/rtk/*.json; do
        if [ -f "$vorhandene_datendatei" ]; then
            fehler "Demo-Modus abgebrochen: In $DATA_DIR liegen bereits Datendateien. Bitte ein leeres --data-dir verwenden."
        fi
    done
fi

# Ein cloud-synchronisierter Ablageort ist der Fehler, der sich spaeter als
# Rechtefehler des launchd-Prozesses tarnt und wie ein Programmfehler aussieht.
for pfad in "$REPO_DIR" "$DATA_DIR"; do
    case "$pfad" in
        "$HOME/Documents"/*|"$HOME/Desktop"/*|*"/Library/Mobile Documents/"*|*"/Dropbox/"*)
            hinweis "$pfad liegt in einem synchronisierten oder TCC-geschuetzten Ordner. Der naechtliche Export bricht dort mit einem Rechtefehler ab."
            ;;
    esac
done

# --- Datenverzeichnis -----------------------------------------------------

schritt "Datenverzeichnis"

for unter in "" "${UNTERVERZEICHNISSE[@]}"; do
    ziel="$DATA_DIR${unter:+/$unter}"
    if [ -d "$ziel" ]; then
        tat "vorhanden: ${unter:-.}"
    elif [ "$DRY_RUN" -eq 1 ]; then
        wuerde "anlegen: $ziel"
    else
        mkdir -p "$ziel"
        tat "angelegt: $ziel"
    fi
done

if [ "$DEMO_MODE" -eq 1 ]; then
    schritt "Demo-Daten"
    if [ "$DRY_RUN" -eq 1 ]; then
        wuerde "Demo-Daten erzeugen: $DATA_DIR"
    else
        python3 "$REPO_DIR/tools/make-sample-data.py" --out "$DATA_DIR" >/dev/null
        tat "Demo-Daten erzeugt: $DATA_DIR"
    fi
fi

# --- Exportskripte --------------------------------------------------------

schritt "Exportskripte nach $DATA_DIR/bin"

for name in "${SKRIPTE[@]}"; do
    quelle="$REPO_DIR/export/$name"
    ziel="$DATA_DIR/bin/$name"
    [ -f "$quelle" ] || fehler "$quelle fehlt. Ist das Repository vollstaendig?"

    if [ ! -f "$ziel" ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            wuerde "kopieren: $name"
        else
            cp "$quelle" "$ziel"
            chmod +x "$ziel"
            tat "kopiert: $name"
        fi
    elif cmp -s "$quelle" "$ziel"; then
        tat "unveraendert: $name"
    elif [ "$FORCE" -eq 1 ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            wuerde "ueberschreiben: $name"
        else
            cp "$quelle" "$ziel"
            chmod +x "$ziel"
            tat "ueberschrieben: $name"
        fi
    else
        hinweis "$name unter bin/ weicht vom Repository ab und bleibt stehen. Mit --force ueberschreiben, oder die Abweichung ansehen: diff \"$quelle\" \"$ziel\""
    fi
done

# --- config.toml ----------------------------------------------------------

schritt "config.toml"

CONFIG="$REPO_DIR/config.toml"
VORLAGE="$REPO_DIR/config.example.toml"

if [ -f "$CONFIG" ]; then
    tat "vorhanden, bleibt unveraendert: $CONFIG"
    aktuell="$(python3 - "$CONFIG" <<'ENDE'
import sys, tomllib
with open(sys.argv[1], "rb") as datei:
    print(tomllib.load(datei).get("data", {}).get("directory", ""))
ENDE
)"
    if [ "$aktuell" != "$DATA_DIR" ]; then
        hinweis "In der config.toml steht directory = \"$aktuell\", eingerichtet wurde aber $DATA_DIR. Eines von beiden anpassen."
    fi
elif [ ! -f "$VORLAGE" ]; then
    fehler "$VORLAGE fehlt. Ist das Repository vollstaendig?"
elif [ "$DRY_RUN" -eq 1 ]; then
    wuerde "anlegen aus config.example.toml mit directory = \"$DATA_DIR\""
else
    python3 - "$VORLAGE" "$CONFIG" "$DATA_DIR" <<'ENDE'
import sys
vorlage, ziel, verzeichnis = sys.argv[1:4]
text = open(vorlage, encoding="utf-8").read()
zeilen = []
ersetzt = False
for zeile in text.splitlines(keepends=True):
    if not ersetzt and zeile.lstrip().startswith("directory"):
        vorspann = zeile[: len(zeile) - len(zeile.lstrip())]
        zeilen.append(f'{vorspann}directory = "{verzeichnis}"\n')
        ersetzt = True
    else:
        zeilen.append(zeile)
if not ersetzt:
    raise SystemExit("config.example.toml enthaelt keine directory-Zeile.")
open(ziel, "w", encoding="utf-8").write("".join(zeilen))
ENDE
    tat "angelegt mit directory = \"$DATA_DIR\""
fi

# --- launchd --------------------------------------------------------------

if [ "$WITH_LAUNCHAGENTS" -eq 1 ]; then
    schritt "launchd-Jobs"

    AGENTS_DIR="$HOME/Library/LaunchAgents"
    if [ ! -d "$AGENTS_DIR" ]; then
        if [ "$DRY_RUN" -eq 1 ]; then
            wuerde "anlegen: $AGENTS_DIR"
        else
            mkdir -p "$AGENTS_DIR"
            tat "angelegt: $AGENTS_DIR"
        fi
    fi

    for job in "${JOBS[@]}"; do
        vorlage="$REPO_DIR/export/launchd/$job.plist.template"
        [ -f "$vorlage" ] || fehler "$vorlage fehlt. Ist das Repository vollstaendig?"
        label="$LABEL_PREFIX.$job"
        ziel="$AGENTS_DIR/$label.plist"

        # Ein geladener Job haelt die alte Fassung fest; erst entladen,
        # dann schreiben, dann laden.
        if launchctl list "$label" >/dev/null 2>&1; then
            if [ "$DRY_RUN" -eq 1 ]; then
                wuerde "entladen: $label (laeuft bereits)"
            else
                launchctl unload "$ziel" 2>/dev/null || true
                tat "entladen: $label"
            fi
        fi

        if [ "$DRY_RUN" -eq 1 ]; then
            wuerde "schreiben: $ziel"
            wuerde "  Skripte:  $DATA_DIR/bin"
            wuerde "  Daten:    $DATA_DIR"
            wuerde "  Label:    $label"
            wuerde "laden: $label"
        else
            sed -e "s|__SCRIPT_DIR__|$DATA_DIR/bin|g" \
                -e "s|__DATA_DIR__|$DATA_DIR|g" \
                -e "s|__LABEL_PREFIX__|$LABEL_PREFIX|g" \
                "$vorlage" > "$ziel"
            launchctl load "$ziel"
            tat "eingerichtet und geladen: $label"
        fi
    done
else
    schritt "launchd-Jobs"
    tat "uebersprungen. Mit --with-launchagents einrichten."
fi

# --- Abschluss ------------------------------------------------------------

schritt "Ergebnis"

if [ "${#HINWEISE[@]}" -gt 0 ]; then
    printf '  %d Hinweis(e):\n' "${#HINWEISE[@]}"
    for eintrag in "${HINWEISE[@]}"; do
        printf '   - %s\n' "$eintrag"
    done
else
    tat "keine Hinweise."
fi

if [ "$DRY_RUN" -eq 1 ]; then
    printf '\nTrockenlauf beendet, es wurde nichts geaendert.\n'
else
    printf '\nFertig. Starten mit:\n  cd %s && python3 app.py\n' "$REPO_DIR"
fi
