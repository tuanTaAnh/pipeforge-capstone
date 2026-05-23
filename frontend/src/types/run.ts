import type { Artifact } from "./artifact";
import type { AgentEvent, AgentNode } from "./event";
import type { ChatMessage } from "./chat";

export type AskUserQuestion = {
  questionId: string;
  question: string;
  options: string[];
};

export type RunStatus =
  | "idle"
  | "running"
  | "waiting_for_user"
  | "completed"
  | "failed";

export type RunState = {
  runId?: string;
  status: RunStatus;
  connected: boolean;
  lastSeq: number;
  nodes: Record<string, AgentNode>;
  rootAgentIds: string[];
  chatMessages: ChatMessage[];
  artifacts: Artifact[];
  pendingQuestion?: AskUserQuestion;
  activity: string[];
  errors: string[];
};