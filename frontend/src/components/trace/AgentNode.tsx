import type { AgentNode as AgentNodeType } from "../../types/event";
import type { RunState } from "../../types/run";
import { ToolCallCard } from "./ToolCallCard";

type Props = {
  nodeId: string;
  state: RunState;
  onToggle: (nodeId: string) => void;
};

function statusLabel(status: AgentNodeType["status"]) {
  if (status === "running") return "Running";
  if (status === "waiting_for_user") return "Waiting";
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  return "Queued";
}

function agentTypeLabel(role: AgentNodeType["role"]) {
  return role === "orchestrator" ? "Orchestrator" : "Specialist agent";
}

export function AgentNode({ nodeId, state, onToggle }: Props) {
  const node = state.nodes[nodeId];
  if (!node) return null;

  const thinkingEvents = node.events.filter((event) => event.type === "agent_thinking");
  const eventCount = node.events.length;

  return (
    <article className={`agent-node-card agent-node-${node.status}`}>
      <button
        type="button"
        className="agent-node-header"
        onClick={() => onToggle(node.id)}
      >
        <span className="agent-toggle">{node.expanded ? "▾" : "▸"}</span>

        <span className="agent-title-group">
          <strong>{node.name}</strong>
          <small>
            {agentTypeLabel(node.role)} · {eventCount} events · {node.tools.length} tools
          </small>
        </span>

        <span className={`agent-status agent-status-${node.status}`}>
          {statusLabel(node.status)}
        </span>
      </button>

      {node.expanded && (
        <div className="agent-node-body">
          {thinkingEvents.map((event) => (
            <div key={event.id} className="trace-event thinking-event">
              <span>Thinking</span>
              <p>{String(event.payload.text ?? "")}</p>
            </div>
          ))}

          {node.tools.map((tool) => (
            <ToolCallCard key={tool.toolCallId} tool={tool} />
          ))}

          {node.artifacts.map((artifact) => (
            <div key={artifact.id} className="trace-event artifact-event">
              <span>Artifact created</span>
              <p>{artifact.filename}</p>
            </div>
          ))}

          {node.children.map((childId) => (
            <AgentNode
              key={childId}
              nodeId={childId}
              state={state}
              onToggle={onToggle}
            />
          ))}
        </div>
      )}
    </article>
  );
}