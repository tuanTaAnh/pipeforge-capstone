import type { AgentInfo } from "../types/agent";
import type { AgentNode } from "../types/event";
import type { RunState } from "../types/run";

export function ensureNode(state: RunState, agent: AgentInfo): AgentNode {
  if (!state.nodes[agent.id]) {
    state.nodes[agent.id] = {
      id: agent.id,
      name: agent.name,
      role: agent.role,
      parentId: agent.parentId ?? null,
      status: "queued",
      expanded: true,
      children: [],
      events: [],
      tools: [],
      artifacts: []
    };

    if (agent.parentId) {
      ensureParentPlaceholder(state, agent.parentId);

      const parent = state.nodes[agent.parentId];
      if (!parent.children.includes(agent.id)) {
        parent.children.push(agent.id);
      }
    } else if (!state.rootAgentIds.includes(agent.id)) {
      state.rootAgentIds.push(agent.id);
    }
  }

  return state.nodes[agent.id];
}

function ensureParentPlaceholder(state: RunState, parentId: string) {
  if (!state.nodes[parentId]) {
    state.nodes[parentId] = {
      id: parentId,
      name: parentId,
      role: "orchestrator",
      parentId: null,
      status: "running",
      expanded: true,
      children: [],
      events: [],
      tools: [],
      artifacts: []
    };

    if (!state.rootAgentIds.includes(parentId)) {
      state.rootAgentIds.push(parentId);
    }
  }
}

export function appendActivity(state: RunState, text: string) {
  state.activity.unshift(text);
  state.activity = state.activity.slice(0, 8);
}