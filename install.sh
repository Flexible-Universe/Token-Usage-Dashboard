#!/bin/sh
# Token-Usage-Dashboard - lokales Dashboard fuer Claude-Code-Nutzungsdaten
# Copyright (C) 2026 Rolf Warnecke
#
# Dieses Programm ist freie Software: Sie koennen es unter den Bedingungen der
# GNU Affero General Public License, Version 3, weitergeben und/oder aendern.
# Es wird ohne jede Gewaehrleistung bereitgestellt; Einzelheiten in der Datei
# LICENSE oder unter <https://www.gnu.org/licenses/>.
#
# Starter fuer macOS und Linux: sucht ein Python ab 3.11 und uebergibt alle
# Argumente an install.py, das die eigentliche Einrichtung erledigt.
# Hilfe: ./install.sh --help

HIER="$(cd "$(dirname "$0")" && pwd)"

# Too old candidates are remembered so the error can name them; "not found"
# alone sends the user to install a Python they may already have.
GEFUNDEN=""

for kandidat in python3 python3.14 python3.13 python3.12 python3.11 python; do
    if command -v "$kandidat" >/dev/null 2>&1 \
            && "$kandidat" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
        exec "$kandidat" "$HIER/install.py" "$@"
    fi
    if command -v "$kandidat" >/dev/null 2>&1; then
        version="$("$kandidat" --version 2>&1)"
        GEFUNDEN="${GEFUNDEN:+$GEFUNDEN; }$kandidat ${version:-(Version nicht lesbar)}"
    fi
done

echo "Fehler: Python 3.11 oder neuer wurde nicht gefunden." >&2
if [ -n "$GEFUNDEN" ]; then
    echo "  Gefunden: $GEFUNDEN" >&2
fi
echo "  macOS:  brew install python" >&2
echo "  Linux:  ueber die Paketverwaltung, etwa: sudo apt install python3" >&2
exit 1
