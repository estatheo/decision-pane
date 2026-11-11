#!/bin/sh
# gc decisions withdraw: see help.md. Needs python3.
exec python3 -I "$GC_PACK_DIR/lib/decisions.py" withdraw "$@"
