# shellcheck shell=bash
# Shared by launch_session.sh and launch_destroy.sh (source it; do not run it).
# The caller defines log, loud and aws_ before it calls any function here.

# Terminates any launch instance directly: instances tagged Stack=dev-launch.
terminate_instances() {
  local ids
  ids="$(aws_ ec2 describe-instances --filters Name=tag:Stack,Values=dev-launch \
    Name=instance-state-name,Values=pending,running,stopping,stopped \
    --query 'Reservations[].Instances[].InstanceId' --output text)" || return 1
  [[ -z "$ids" || "$ids" == "None" ]] && return 0
  # shellcheck disable=SC2086  # a word per instance ID
  aws_ ec2 terminate-instances --instance-ids $ids >/dev/null
}

# A state-lock error leaves the lock behind: print the command, never run it.
lock_hint() {
  grep -q 'Error acquiring the state lock' "$1" 2>/dev/null || return 0
  loud "TERRAFORM STATE LOCK HELD. When no apply runs, free it by hand: terraform -chdir=terraform/envs/dev-launch force-unlock <LOCK_ID> (the ID is in the error above)"
}

# Removes key directories that a killed session left behind. Only real
# directories named exactly like the mktemp template in launch_session.sh
# ($XDG_RUNTIME_DIR/launch-XXXXXX); a symlink is never followed or removed.
# None is fine. Returns 1 (after a loud message) when one could not be removed.
remove_stale_keydirs() {
  local rc=0 d
  [[ -n "${XDG_RUNTIME_DIR:-}" && -d "$XDG_RUNTIME_DIR" ]] || return 0
  for d in "$XDG_RUNTIME_DIR"/launch-??????; do
    [[ "${d##*/}" =~ ^launch-[A-Za-z0-9]{6}$ ]] || continue
    [[ -L "$d" || ! -d "$d" ]] && continue
    loud "LEFTOVER KEY DIRECTORY from an earlier session: removing it"
    # find does not follow symlinks and -type f skips them; rm -rf does not follow them.
    find "$d" -type f -exec shred -u {} + 2>/dev/null || { loud "SHRED FAILED: the files are removed without it"; rc=1; }
    rm -rf "$d"
    if [[ -e "$d" ]]; then
      loud "LEFTOVER KEY DIRECTORY STILL EXISTS: remove it by hand"
      rc=1
    fi
  done
  return "$rc"
}
