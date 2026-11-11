#!/bin/sh
# gc decisions work: see help.md. Needs python3.
exec python3 -I "$GC_PACK_DIR/lib/decisions.py" work "$@"
