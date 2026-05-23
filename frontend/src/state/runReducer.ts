import type { Artifact } from "../types/artifact";
import type { AgentEvent } from "../types/event";
import type { RunState } from "../types/run";
import { appendActivity, ensureNode } from "./traceTree";

function cloneState(state: RunState): RunState {
  return structuredClone(state);
}

export function applyEvent(state: RunState, event: AgentEvent): RunState {
  const next = cloneState(state);
  next.runId = event.runId;
  next.lastSeq = Math.max(next.lastSeq, event.seq);

  const node = ensureNode(next, event.agent);
  node.events.push(event);

  switch (event.type) {
    case "session_started":
      next.status = "running";
      next.connected = true;
      node.status = "running";
      next.chatMessages.push({
        id: event.id,
        role: "assistant",
        text: "Run started. Pipeline Architect is analyzing your request..."
      });
      appendActivity(next, "Pipeline Architect started the run.");
      break;

    case "agent_started":
    case "sub_agent_started":
      node.status = "running";
      appendActivity(next, `${node.name} is running...`);
      break;

    case "agent_thinking":
      appendActivity(next, `${node.name}: ${String(event.payload.text ?? "thinking...")}`);
      break;

    case "tool_started":
      node.tools.push({
        toolCallId: String(event.payload.toolCallId),
        toolName: String(event.payload.toolName),
        status: "running",
        input: event.payload.input
      });
      appendActivity(next, `${node.name} is using ${String(event.payload.toolName)}...`);
      break;

    case "tool_completed": {
      const toolCallId = String(event.payload.toolCallId);
      const tool = node.tools.find((item) => item.toolCallId === toolCallId);

      if (tool) {
        tool.status = "completed";
        tool.output = event.payload.output;
      } else {
        node.tools.push({
          toolCallId,
          toolName: String(event.payload.toolName),
          status: "completed",
          output: event.payload.output
        });
      }

      appendActivity(next, `${node.name} completed ${String(event.payload.toolName)}.`);
      break;
    }

    case "ask_user":
      next.status = "waiting_for_user";
      node.status = "waiting_for_user";
      next.pendingQuestion = {
        questionId: String(event.payload.questionId),
        question: String(event.payload.question),
        options: Array.isArray(event.payload.options)
          ? event.payload.options.map(String)
          : []
      };
      next.chatMessages.push({
        id: event.id,
        role: "assistant",
        text: String(event.payload.question)
      });
      appendActivity(next, "Waiting for user input...");
      break;

    case "ask_user_answered":
      next.pendingQuestion = undefined;
      next.status = "running";
      node.status = "running";
      next.chatMessages.push({
        id: event.id,
        role: "system",
        text: `Answer received: ${String(event.payload.answer)}`
      });
      appendActivity(next, "User answered. Workflow resumed.");
      break;

    case "agent_response":
      next.chatMessages.push({
        id: event.id,
        role: "assistant",
        text: String(event.payload.text ?? "")
      });
      appendActivity(next, `${node.name} responded.`);
      break;

    case "artifact_created": {
      const artifact = event.payload as unknown as Artifact;
      next.artifacts.push(artifact);
      node.artifacts.push(artifact);
      appendActivity(next, `${node.name} created ${artifact.filename}.`);
      break;
    }

    case "sub_agent_completed":
    case "agent_completed":
      node.status = "completed";
      appendActivity(next, `${node.name} completed.`);
      break;

    case "final_message":
      next.chatMessages.push({
        id: event.id,
        role: "assistant",
        text: String(event.payload.text ?? "")
      });
      appendActivity(next, "Final response generated.");
      break;

    case "agent_failed":
    case "error":
      next.status = "failed";
      node.status = "failed";
      next.errors.push(String(event.payload.message ?? "Unknown error"));
      appendActivity(next, `${node.name} failed.`);
      break;

    case "done":
      next.status = "completed";
      next.connected = false;
      appendActivity(next, "Run completed.");
      break;
  }

  return next;
}

export function toggleNodeExpanded(state: RunState, nodeId: string): RunState {
  const next = cloneState(state);

  if (next.nodes[nodeId]) {
    next.nodes[nodeId].expanded = !next.nodes[nodeId].expanded;
  }

  return next;
}