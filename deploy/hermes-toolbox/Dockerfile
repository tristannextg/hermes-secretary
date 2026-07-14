# Toolbox image for hermes-agent's Docker terminal backend.
# The agent gets root INSIDE this container (extended rights within,
# nothing outside); the container is persistent across sessions.
#
# The entrypoint starts a loopback forwarder so the obsidian-ops API is
# reachable at http://127.0.0.1:8766 inside the container (same address
# as on the host): 127.0.0.1:8766 -> host.docker.internal:8766. Requires
# the container to run with --add-host=host.docker.internal:host-gateway
# and obsidian-ops published on the docker bridge gateway IP.
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
       curl jq git ca-certificates ripgrep socat \
    && rm -rf /var/lib/apt/lists/*

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /workspace
ENTRYPOINT ["/entrypoint.sh"]
CMD ["sleep", "infinity"]
