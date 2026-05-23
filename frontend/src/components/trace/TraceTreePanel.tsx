import type { RunState } from "../../types/run";
import { AgentNode } from "./AgentNode";

type Props = {
  state: RunState;
  onToggleNode: (nodeId: string) => void;
};

export function TraceTreePanel({ state, onToggleNode }: Props) {
  return (
    <section className="trace-panel">
      <h2>Agent Trace</h2>

      <div className="trace-tree">
        {state.rootAgentIds.length === 0 ? (
          <p className="empty">Trace will appear here as events arrive.</p>
        ) : (
          state.rootAgentIds.map((nodeId) => (
            <AgentNode
              key={nodeId}
              nodeId={nodeId}
              state={state}
              onToggle={onToggleNode}
            />
          ))
        )}
      </div>
    </section>
  );
}