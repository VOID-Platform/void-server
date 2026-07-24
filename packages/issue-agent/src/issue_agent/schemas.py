from pydantic import BaseModel, Field
from typing import Literal


class ToolCall(BaseModel):
    name: str
    input: str | None = None
    output: str | None = None
    latency_ms: float | None = None
    success: bool
    error: str | None = None


class AgentStep(BaseModel):
    step_type: str
    planner_output: str | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    context: str | None = None
    latency_ms: float | None = None


class ExecutionTrace(BaseModel):
    agent_steps: list[AgentStep] = Field(default_factory=list)
    model: str | None = None
    total_latency_ms: float | None = None
    tokens_used: int | None = None


class EvaluationResult(BaseModel):
    failure_modes: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str = ""
    urgency_tier: Literal["P0", "P1", "P2", "DEFER"] = "P2"
    severity: Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"] = "MEDIUM"


class IncidentSnapshot(BaseModel):
    incident_id: str
    execution_trace: ExecutionTrace
    evaluation: EvaluationResult
    telemetry: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)


class Evidence(BaseModel):
    failure_mode: str
    summary: str
    supporting_trace: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)


class InvestigationTarget(BaseModel):
    file_path: str = ""
    symbol: str = ""
    reason: str = ""


class CodeGraphNode(BaseModel):
    file_path: str
    kind: Literal["file", "class", "function", "symbol"] = "file"
    symbol: str | None = None


class CodeGraphEdge(BaseModel):
    source: str
    target: str
    relation: Literal["imports", "calls", "inherits", "references"]


class CodeGraph(BaseModel):
    nodes: list[CodeGraphNode] = Field(default_factory=list)
    edges: list[CodeGraphEdge] = Field(default_factory=list)


class TimelineEvent(BaseModel):
    event_type: Literal["execution_step", "tool_call", "failure_observable", "evidence", "root_cause"]
    step_index: int | None = None
    description: str
    source: Literal["evaluator", "repository", "trace"] = "trace"
    evidence_refs: list[int] = Field(default_factory=list)


class RepositoryValidation(BaseModel):
    component: str
    status: Literal["confirmed", "suggested", "not_found", "not_searched"]
    found_paths: list[str] = Field(default_factory=list)
    notes: str = ""


class RepositoryFindings(BaseModel):
    validated_components: list[RepositoryValidation] = Field(default_factory=list)
    files_found: list[str] = Field(default_factory=list)
    functions_found: list[str] = Field(default_factory=list)
    symbols_searched: list[str] = Field(default_factory=list)
    missing_context_reason: str = ""


class MissingContext(BaseModel):
    reason: str
    missing_information: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class EngineeringReport(BaseModel):
    summary: str
    root_cause: str
    evidence: list[str] = Field(default_factory=list)
    suspected_components: list[str] = Field(default_factory=list)
    relevant_files: list[str] = Field(default_factory=list)
    relevant_functions: list[str] = Field(default_factory=list)
    suggested_investigation: list[str] = Field(default_factory=list)
    suggested_fix: str
    suggested_tests: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)

    executive_summary: str = ""
    impact: str = ""
    timeline: list[TimelineEvent] = Field(default_factory=list)
    repository_findings: RepositoryFindings = Field(default_factory=RepositoryFindings)
    missing_context: MissingContext | None = None
    evidence_analysis: str = ""
    secondary_effects: list[str] = Field(default_factory=list)
    issue_title: str = ""


class GitHubIssueInput(BaseModel):
    owner: str
    repo: str
    title: str
    body: str