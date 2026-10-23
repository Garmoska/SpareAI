"""Pydantic schemas shared between Agent and Dispatcher."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

ModelState = Literal["HOT", "COLD", "UNKNOWN"]
AgentState = Literal["READY", "OVERLOAD"]


class ModelInfo(BaseModel):
    state: ModelState


class ModelEntry(BaseModel):
    name: str
    size_bytes: Optional[int] = None
    state: ModelState
    modified_at: Optional[str] = None


class ModelsResponse(BaseModel):
    models: list[ModelEntry]


class AgentStatus(BaseModel):
    node_id: str
    state: AgentState
    available: bool
    cpu_cores: int
    load_avg_1m: float
    cpu_usage_pct: float
    memory_usage_pct: float
    models: dict[str, ModelInfo]
    in_flight_requests: int
    last_heartbeat: datetime
    version: str = "0.1.0"


class GenerateOptions(BaseModel):
    temperature: Optional[float] = None
    num_predict: Optional[int] = None
    top_p: Optional[float] = None
    top_k: Optional[int] = None
    seed: Optional[int] = None


class GenerateRequest(BaseModel):
    request_id: str
    model: str
    prompt: str = Field(min_length=1)
    options: Optional[GenerateOptions] = None
    keep_alive: Optional[int | str] = None


class ChatRequest(BaseModel):
    model: Optional[str] = None  # default to Dispatcher's configured MODEL
    prompt: str = Field(min_length=1)
    options: Optional[GenerateOptions] = None


class ErrorPayload(BaseModel):
    error: str
    detail: Optional[str] = None


# ---- SSE event payloads (documentary only; serialized as JSON) ----

class SSERouting(BaseModel):
    request_id: str
    node_id: str
    model: str
    model_state_at_routing: ModelState
    attempt: int


class SSEToken(BaseModel):
    request_id: str
    chunk: str
    ts_mono_ms: int


class SSEDone(BaseModel):
    request_id: str
    total_duration: Optional[int] = None  # ns, from Ollama
    load_duration: Optional[int] = None
    prompt_eval_count: Optional[int] = None
    prompt_eval_duration: Optional[int] = None
    eval_count: Optional[int] = None
    eval_duration: Optional[int] = None
    agent_ttft_ms: Optional[int] = None


class SSEMetrics(BaseModel):
    request_id: str
    dispatcher_ttft_ms: Optional[int] = None
    e2e_latency_ms: int
    selected_node: str
    failover_attempts: list[str] = []


class SSEError(BaseModel):
    request_id: str
    where: Literal["pre_stream", "mid_stream"]
    code: str
    detail: Optional[str] = None
