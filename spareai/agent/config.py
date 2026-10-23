"""Agent configuration loaded from environment variables."""
from __future__ import annotations

import os
import socket
from dataclasses import dataclass


@dataclass(frozen=True)
class AgentConfig:
    node_id: str
    bind_host: str
    bind_port: int
    agent_token: str
    ollama_url: str
    default_model: str
    model_state_ttl_s: float
    overload_high_pct: float
    overload_low_pct: float
    overload_sample_interval_s: float
    ollama_connect_timeout_s: float
    ollama_read_timeout_s: float

    @classmethod
    def from_env(cls) -> "AgentConfig":
        token = os.environ.get("AGENT_TOKEN")
        if not token:
            raise RuntimeError("AGENT_TOKEN env var is required")
        if token.lower() in {"changeme", "changeme-agent-dev-only", "placeholder", ""}:
            raise RuntimeError(
                "AGENT_TOKEN is set to a placeholder value — refuse to start. "
                "Set a real token in the environment."
            )
        return cls(
            node_id=os.environ.get("NODE_ID")
                    or os.environ.get("AGENT_NODE_ID")
                    or socket.gethostname(),
            bind_host=os.environ.get("LISTEN_HOST")
                      or os.environ.get("AGENT_BIND_HOST", "0.0.0.0"),
            bind_port=int(os.environ.get("LISTEN_PORT")
                          or os.environ.get("AGENT_BIND_PORT", "8081")),
            agent_token=token,
            ollama_url=(os.environ.get("OLLAMA_BASE_URL")
                        or os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")).rstrip("/"),
            default_model=os.environ.get("MODEL", "qwen2.5:3b-instruct-q4_K_M"),
            model_state_ttl_s=float(os.environ.get("STATUS_CACHE_TTL_S")
                                    or os.environ.get("MODEL_STATE_TTL_S", "2.0")),
            overload_high_pct=float(os.environ.get("OVERLOAD_HIGH_PCT", "0.70")),
            overload_low_pct=float(os.environ.get("OVERLOAD_LOW_PCT", "0.50")),
            overload_sample_interval_s=float(os.environ.get("OVERLOAD_SAMPLE_INTERVAL_S", "2.0")),
            ollama_connect_timeout_s=float(os.environ.get("OLLAMA_CONNECT_TIMEOUT_S", "5")),
            ollama_read_timeout_s=float(os.environ.get("REQUEST_TIMEOUT_S")
                                        or os.environ.get("OLLAMA_READ_TIMEOUT_S", "180")),
        )
