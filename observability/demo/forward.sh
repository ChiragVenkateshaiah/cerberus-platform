#!/usr/bin/env bash
# requires bash >= 4.4
# Port-forward helper for the recorded run (ADR 0022 step 6).
#
#   localhost:9090 -> svc/prometheus-server (monitoring), the agent's web port
#   localhost:4040 -> the newest Running Spark driver pod (spark-jobs)
#
# Both forwards bind 127.0.0.1 only. The 4040 forward re-attaches when the
# driver ends or a new one appears (generator, then the silver job).
# The script waits for the cluster, so start it before or after
# `make exercise`. After teardown it keeps waiting (prints "detached" and
# then waits again); stop it with Ctrl-C, which kills both forwards.
# A forward detaches at once when the driver is gone or replaced, and only
# after two failed API calls in a row otherwise.
# `set -u` without -e or pipefail is deliberate: this is a polling loop
# and a failed kubectl call must not end it.
set -u

PROM_NS=monitoring
PROM_SVC=prometheus-server
PROM_PORT=9090
PROM_SVC_PORT=80
SPARK_NS=spark-jobs
SPARK_LABEL=spark-role=driver
SPARK_PORT=4040
POLL=3
LOG_DIR="${TMPDIR:-/tmp}"

log() { printf '%s  %s\n' "$(date -u +%H:%M:%SZ)" "$*"; }

pids=()
# shellcheck disable=SC2317  # called through the trap
cleanup() {
	trap '' INT TERM
	for p in "${pids[@]}"; do kill "$p" 2>/dev/null; done
	wait 2>/dev/null
	log "stopped"
	exit 0
}
trap cleanup INT TERM

# Each loop runs in a background subshell and tracks only its current
# children, so nothing grows without bound.
fwd_pid=
nap_pid=
# Sleep in the background so a trapped signal interrupts the wait at once.
nap() { sleep "$POLL" & nap_pid=$!; wait "$nap_pid" 2>/dev/null; nap_pid=; }

# shellcheck disable=SC2317  # called through the trap
sub_cleanup() {
	trap '' TERM
	kill ${fwd_pid:+"$fwd_pid"} ${nap_pid:+"$nap_pid"} 2>/dev/null
	exit 0
}

kc() { kubectl --request-timeout=5s "$@" 2>/dev/null; }

prom_present() { kc -n "$PROM_NS" get "svc/$PROM_SVC" -o name >/dev/null; }

forward_prometheus() {
	local waited=0 failed=0 miss
	local errlog="$LOG_DIR/demo-forward-prometheus.log"
	while true; do
		if prom_present; then
			kubectl -n "$PROM_NS" port-forward --address 127.0.0.1 \
				"svc/$PROM_SVC" "$PROM_PORT:$PROM_SVC_PORT" >"$errlog" 2>&1 &
			fwd_pid=$!
			sleep 1
			if kill -0 "$fwd_pid" 2>/dev/null; then
				log "attached  prometheus  http://localhost:$PROM_PORT"
				failed=0
				miss=0
				while kill -0 "$fwd_pid" 2>/dev/null && [ "$miss" -lt 2 ]; do
					nap
					if prom_present; then miss=0; else miss=$((miss + 1)); fi
				done
				kill "$fwd_pid" 2>/dev/null
				log "detached  prometheus"
			elif [ "$failed" -eq 0 ]; then
				log "failed    port $PROM_PORT in use? see: ss -ltnp 'sport = :$PROM_PORT' and $errlog"
				failed=1
			fi
			fwd_pid=
			waited=0
		elif [ "$waited" -eq 0 ]; then
			log "waiting   svc/$PROM_SVC in $PROM_NS (no cluster yet?)"
			waited=1
		fi
		nap
	done
}

# Newest Running driver (sorted by creation time, last item).
driver_pod() {
	kc -n "$SPARK_NS" get pods -l "$SPARK_LABEL" \
		--field-selector=status.phase=Running \
		--sort-by=.metadata.creationTimestamp \
		-o jsonpath='{.items[-1:].metadata.name}'
}

forward_spark() {
	local waited=0 failed=0 miss pod cur next=
	local errlog="$LOG_DIR/demo-forward-spark.log"
	while true; do
		# A newer driver seen by the inner loop attaches without a nap.
		pod="${next:-$(driver_pod)}"
		next=
		if [ -n "$pod" ]; then
			kubectl -n "$SPARK_NS" port-forward --address 127.0.0.1 \
				"pod/$pod" "$SPARK_PORT:$SPARK_PORT" >"$errlog" 2>&1 &
			fwd_pid=$!
			sleep 1
			if kill -0 "$fwd_pid" 2>/dev/null; then
				log "attached  spark driver $pod  http://localhost:$SPARK_PORT"
				failed=0
				miss=0
				while kill -0 "$fwd_pid" 2>/dev/null && [ "$miss" -lt 2 ]; do
					nap
					if cur="$(driver_pod)"; then
						# Definite answer: same driver keeps it; none or a newer one switches now.
						if [ "$cur" = "$pod" ]; then miss=0; else
							next="$cur"
							break
						fi
					else
						miss=$((miss + 1)) # lookup failed (timeout); detach only after two
					fi
				done
				kill "$fwd_pid" 2>/dev/null
				log "detached  spark driver $pod"
			elif [ "$failed" -eq 0 ]; then
				log "failed    port $SPARK_PORT in use? see: ss -ltnp 'sport = :$SPARK_PORT' and $errlog"
				failed=1
			fi
			fwd_pid=
			waited=0
			[ -n "$next" ] && continue
		elif [ "$waited" -eq 0 ]; then
			log "waiting   Running pod $SPARK_LABEL in $SPARK_NS"
			waited=1
		fi
		nap
	done
}

(trap sub_cleanup TERM; forward_prometheus) &
pids+=("$!")
(trap sub_cleanup TERM; forward_spark) &
pids+=("$!")
wait
