"""Dispatcher configuration (env + YAML agents file)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class AgentRef:
    node_id: str
    url: str


@dataclass(frozen=True)
class DispatcherConfig:
    bind_host: str
    bind_port: int
    client_token: str
    agent_token: str
    default_model: str
    agents: tuple[AgentRef, ...]
    health_poll_interval_s: float
    health_staleness_s: float
    agent_status_timeout_s: float
    generate_connect_timeout_s: float
    generate_read_timeout_s: float
    failover_max_attempts: int
    stream_inactivity_timeout_s: float

    @classmethod
    def from_env(cls) -> "DispatcherConfig":
        client_token = os.environ.get("CLIENT_TOKEN")
        agent_token = os.environ.get("AGENT_TOKEN")
        if not client_token:
            raise RuntimeError("CLIENT_TOKEN env var is required")
        if not agent_token:
            raise RuntimeError("AGENT_TOKEN env var is required")
        placeholder = {"changeme", "changeme-client-dev-only", "changeme-agent-dev-only",
                       "placeholder", ""}
        if client_token.lower() in placeholder:
            raise RuntimeError("CLIENT_TOKEN is a placeholder — refuse to start.")
        if agent_token.lower() in placeholder:
            raise RuntimeError("AGENT_TOKEN is a placeholder — refuse to start.")

        agents_env = os.environ.get("AGENTS")
        if agents_env:
            agents = _parse_agents_env(agents_env)
        else:
            agents_file = Path(os.environ.get("AGENTS_FILE", "./agents.yaml"))
            agents = _load_agents_yaml(agents_file)
        if not agents:
            raise RuntimeError("No agents configured (AGENTS env or agents.yaml)")

        return cls(
            bind_host=os.environ.get("LISTEN_HOST")
                      or os.environ.get("DISPATCHER_BIND_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("LISTEN_PORT")
                          or os.environ.get("DISPATCHER_BIND_PORT", "8080")),
            client_token=client_token,
            agent_token=agent_token,
            default_model=os.environ.get("MODEL", "qwen2.5:3b-instruct-q4_K_M"),
            agents=tuple(agents),
            health_poll_interval_s=float(os.environ.get("HEALTH_POLL_INTERVAL_S", "3.0")),
            health_staleness_s=float(os.environ.get("STATUS_FRESHNESS_S")
                                     or os.environ.get("HEALTH_STALENESS_S", "10.0")),
            agent_status_timeout_s=float(os.environ.get("AGENT_STATUS_TIMEOUT_S", "1.5")),
            generate_connect_timeout_s=float(os.environ.get("GENERATE_CONNECT_TIMEOUT_S", "5")),
            generate_read_timeout_s=float(os.environ.get("REQUEST_TIMEOUT_S")
                                          or os.environ.get("GENERATE_READ_TIMEOUT_S", "180")),
            failover_max_attempts=int(os.environ.get("MAX_ROUTING_ATTEMPTS")
                                       or os.environ.get("FAILOVER_MAX_ATTEMPTS", "2")),
            stream_inactivity_timeout_s=float(os.environ.get("STREAM_INACTIVITY_TIMEOUT_S", "60")),
        )


def _parse_agents_env(value: str) -> list[AgentRef]:
    """Parse `AGENTS=url1,url2` into AgentRefs with auto-generated node_ids."""
    out: list[AgentRef] = []
    seen: set[str] = set()
    for i, raw in enumerate(value.split(",")):
        url = raw.strip().rstrip("/")
        if not url:
            continue
        node_id = f"worker-{i + 1:02d}"
        if node_id in seen:
            continue
        seen.add(node_id)
        out.append(AgentRef(node_id=node_id, url=url))
    return out


def _load_agents_yaml(path: Path) -> list[AgentRef]:
    if not path.exists():
        raise RuntimeError(f"Agents file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = data.get("agents") or []
    out: list[AgentRef] = []
    seen: set[str] = set()
    for entry in raw:
        node_id = entry.get("node_id")
        url = entry.get("url")
        if not node_id or not url:
            raise RuntimeError(f"Invalid agent entry (missing node_id or url): {entry}")
        if node_id in seen:
            raise RuntimeError(f"Duplicate node_id in agents file: {node_id}")
        seen.add(node_id)
        out.append(AgentRef(node_id=node_id, url=url.rstrip("/")))
    return out
