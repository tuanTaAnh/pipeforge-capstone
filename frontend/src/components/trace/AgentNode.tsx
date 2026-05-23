import type { AgentNode as AgentNodeType } from "../../types/event";
import type { RunState } from "../../types/run";
import { ToolCallCard } from "./ToolCallCard";

type Props = {
  nodeId: string;
  state: RunState;
  onToggle: (nodeId: string) => void;
};

function statusLabel(status: AgentNodeType["status"]) {
  if (status === "running") return "● running";
  if (status === "waiting_for_user") return "? waiting";
  if (status === "completed") return "✓ completed";
  if (status === "failed") return "✕ failed";
  return "○ queued";
}

export function AgentNode({ nodeId, state, onToggle }: Props) {
  const node = state.nodes[nodeId];
  if (!node) return null;

  const thinkingEvents = node.events.filter((event) => event.type === "agent_thinking");

  return (
    <div className="agent-node">
      <div className="agent-header" onClick={() => onToggle(node.id)}>
        <span className="agent-toggle">{node.expanded ? "▾" : "▸"}</span>
        <span className="agent-name">{node.name}</span>
        <span className={`status status-${node.status}`}>
          {statusLabel(node.status)}
        </span>
      </div>

      {node.expanded && (
        <div className="agent-body">
          {thinkingEvents.map((event) => (
            <div key={event.id} className="event-card thinking">
              <strong>Thinking</strong>
              <p>{String(event.payload.text ?? "")}</p>
            </div>
          ))}

          {node.tools.map((tool) => (
            <ToolCallCard key={tool.toolCallId} tool={tool} />
          ))}

          {node.artifacts.map((artifact) => (
            <div key={artifact.id} className="event-card artifact-mini">
              <strong>Artifact</strong>
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
    </div>
  );
}