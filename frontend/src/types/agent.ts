export type AgentRole = "orchestrator" | "sub_agent";

export type AgentStatus =
  | "queued"
  | "running"
  | "waiting_for_user"
  | "completed"
  | "failed";

export type AgentInfo = {
  id: string;
  name: string;
  role: AgentRole;
  parentId?: string | null;
};