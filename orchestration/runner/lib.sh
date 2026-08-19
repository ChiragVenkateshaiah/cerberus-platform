# Shared by entrypoint_transform.sh and entrypoint_dbt.sh (sourced, not
# executed directly) -- both scripts are baked into the same image
# already, so a duplicated log() in each was pure drift risk for no
# reason. Not a general-purpose library; just the one helper both
# entrypoints need.

log() { echo "[$(date -u +%FT%TZ)] $*"; }
