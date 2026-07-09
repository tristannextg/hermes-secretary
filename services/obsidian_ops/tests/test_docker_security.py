from __future__ import annotations

from pathlib import Path


def test_compose_does_not_use_forbidden_docker_settings() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    assert "privileged: true" not in compose
    assert "/var/run/docker.sock" not in compose
    assert "127.0.0.1:" in compose
