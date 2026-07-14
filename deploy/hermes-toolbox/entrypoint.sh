#!/bin/sh
# Loopback bridge to the guarded vault API on the host, then hand over
# to whatever command the hermes backend wants to run.
(socat TCP-LISTEN:8766,bind=127.0.0.1,fork,reuseaddr TCP:host.docker.internal:8766 >/dev/null 2>&1 &)
exec "$@"
