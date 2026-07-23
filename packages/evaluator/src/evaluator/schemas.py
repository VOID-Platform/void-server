from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    name: str
    input: str | None = None
    output: str | None = None
    latency_ms: float | None = None
    success: bool = True
    error: str | None = None
    retry_count: int = 0


class LLMResponse(BaseModel):
    model: str | None = None
    response: str | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class AgentStep(BaseModel):
    step_number: int
    tool_calls: list[ToolCall] = []
    llm_response: LLMResponse | None = None
    state: dict | None = None
    retrieved_docs: list[str] = []


class TelemetrySummary(BaseModel):
    total_latency_ms: float | None = None
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    tool_call_count: int | None = None
    failed_tool_calls: int | None = None
    retry_count: int | None = None


class EvaluationContext(BaseModel):
    incident_id: str
    fingerprint: str
    title: str
    severity: str
    labels: list[str]
    occurrence: int
    trace_id: str
    execution_id: str
    first_scene: str
    last_scene: str
    agent_steps: list[AgentStep] = []
    telemetry: TelemetrySummary | None = None


class Urgency(BaseModel):
    tier: Literal["P0", "P1", "P2", "DEFER"]
    page_now: bool
    status: Literal["ACTIVE", "TERMINATED"]
    reasoning: str = Field(
        description="One to two sentences justifying the tier assignment",
    )


FAILURE_MODES = Literal[
    "HALLUCINATION",
    "SILENT_CONTEXT_OVERFLOW",
    "STALE_CONTEXT",
    "REASONING_DRIFT",
    "TOOL_CALL_ANOMALY",
    "HANDOFF_FAILURE",
    "TOKEN_BUDGET_SILENT_FAILURE",
    "LOOPING",
    "NONE_DETECTED",
]


class Evaluation(BaseModel):
    summary: str = Field(description="Brief incident summary")
    classification: Literal[
        "REAL_INCIDENT",
        "FALSE_POSITIVE",
        "INSUFFICIENT_EVIDENCE",
    ]
    recoverability: Literal[
        "RECOVERABLE",
        "NON_RECOVERABLE",
        "UNKNOWN",
    ]
    confidence: float = Field(ge=0.0, le=1.0)
    failure_modes: list[FAILURE_MODES] = Field(
        default_factory=lambda: ["NONE_DETECTED"],
        description="Detected failure modes from trace analysis",
    )
    suspected_root_cause: str = Field(
        default="",
        description="What the model suspects caused the incident",
    )
    suspected_components: list[str] = Field(
        default_factory=list,
        description="Components involved (tool names, model, memory, etc.)",
    )
    reasoning: list[str]
    recommendations: list[str]
    urgency: Urgency


class EvaluationMetadata(BaseModel):
    prompt_version: str
    model_version: str
    model_temperature: float
    evaluated_at: datetime


class PromptMetadata(BaseModel):
    prompt_version: str
    prompt: str
    temperature: float


class FullEvaluation(BaseModel):
    evaluation: Evaluation
    metadata: EvaluationMetadata
