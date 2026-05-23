import type { AgentInfo, AgentStatus } from "./agent";
import type { Artifact } from "./artifact";

export type EventType =
  | "session_started"
  | "agent_started"
  | "agent_thinking"
  | "tool_started"
  | "tool_completed"
  | "sub_agent_started"
  | "sub_agent_completed"
  | "agent_response"
  | "ask_user"
  | "ask_user_answered"
  | "artifact_created"
  | "final_message"
  | "agent_completed"
  | "agent_failed"
  | "error"
  | "done";

export type AgentEvent = {
  id: string;
  seq: number;
  runId: string;
  type: EventType;
  timestamp: string;
  agent: AgentInfo;
  payload: Record<string, unknown>;
};

export type ToolCall = {
  toolCallId: string;
  toolName: string;
  status: "running" | "completed" | "failed";
  input?: unknown;
  output?: unknown;
};

export type AgentNode = {
  id: string;
  name: string;
  role: "orchestrator" | "sub_agent";
  parentId?: string | null;
  status: AgentStatus;
  expanded: boolean;
  children: string[];
  events: AgentEvent[];
  tools: ToolCall[];
  artifacts: Artifact[];
};