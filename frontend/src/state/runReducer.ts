import type { Artifact } from "../types/artifact";
import type { AgentEvent } from "../types/event";
import type { AskUserOption, AskUserQuestion, RunState } from "../types/run";
import { appendActivity, ensureNode } from "./traceTree";

function cloneState(state: RunState): RunState {
  return structuredClone(state);
}

function parseAskUserQuestion(payload: Record<string, unknown>): AskUserQuestion {
  console.log("[PF DEBUG][runReducer][raw ask_user payload]", payload);

  const rawOptions = Array.isArray(payload.options) ? payload.options : [];

  const options: AskUserOption[] = rawOptions.map((item) => {
    if (typeof item === "string") {
      return {
        id: item,
        label: item
      };
    }

    const option = item as Record<string, unknown>;

    return {
      id: String(option.id ?? option.label ?? ""),
      label: String(option.label ?? option.id ?? ""),
      resolved_rule:
        option.resolved_rule === null || option.resolved_rule === undefined
          ? null
          : String(option.resolved_rule),
      implementation:
        option.implementation === null || option.implementation === undefined
          ? null
          : String(option.implementation)
    };
  });

  console.log("[PF DEBUG][runReducer][parsed options]", options);

  const parsedQuestion: AskUserQuestion = {
    questionId: String(payload.questionId),
    question: String(payload.question),
    options,
    issueSummary:
      payload.issueSummary === null || payload.issueSummary === undefined
        ? null
        : String(payload.issueSummary),
    priority:
      payload.priority === "optional_review" ? "optional_review" : "must_answer",
    recommendedOptionId:
      payload.recommendedOptionId === null || payload.recommendedOptionId === undefined
        ? null
        : String(payload.recommendedOptionId),
    recommendationReason:
      payload.recommendationReason === null || payload.recommendationReason === undefined
        ? null
        : String(payload.recommendationReason),
    allowCustomAnswer: Boolean(payload.allowCustomAnswer ?? true),
    validationError:
      payload.validationError === null || payload.validationError === undefined
        ? null
        : String(payload.validationError)
  };

  console.log("[PF DEBUG][runReducer][parsed question]", parsedQuestion);

  return parsedQuestion;
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

    case "ask_user": {
      next.status = "waiting_for_user";
      node.status = "waiting_for_user";
      next.pendingQuestion = parseAskUserQuestion(event.payload);

      next.chatMessages.push({
        id: event.id,
        role: "assistant",
        text: String(event.payload.question)
      });

      appendActivity(next, "Waiting for user input...");
      break;
    }

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