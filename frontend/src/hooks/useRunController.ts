import { useState } from "react";

import { retryRun, startRun, submitAnswer } from "../api/runsApi";
import { initialState } from "../state/initialState";
import { applyEvent, toggleNodeExpanded } from "../state/runReducer";
import type { AgentEvent } from "../types/event";
import type { RunState } from "../types/run";
import { useEventStream } from "./useEventStream";

export function useRunController() {
  const [state, setState] = useState<RunState>(initialState);

  const stream = useEventStream({
    onEvent: (event: AgentEvent) => {
      setState((previous) => applyEvent(previous, event));
    },
    onDisconnected: () => {
      setState((previous) => ({
        ...previous,
        connected: false,
        errors: [...previous.errors, "Event stream disconnected. Reconnecting..."]
      }));
    }
  });

  async function handleStartRun(prompt: string) {
    stream.close();

    setState({
      ...initialState,
      status: "running",
      chatMessages: [
        ...initialState.chatMessages,
        {
          id: `user_${Date.now()}`,
          role: "user",
          text: prompt
        },
        {
          id: `system_${Date.now()}`,
          role: "system",
          text: "Starting PipeForge run..."
        }
      ]
    });

    try {
      const data = await startRun(prompt);
      stream.connect(data.runId, 0);
    } catch (error) {
      setState((previous) => ({
        ...previous,
        status: "failed",
        errors: [...previous.errors, error instanceof Error ? error.message : String(error)]
      }));
    }
  }

  async function handleSubmitAnswer(answer: string) {
    if (!state.pendingQuestion || !state.runId) return;

    const questionId = state.pendingQuestion.questionId;

    setState((previous) => ({
      ...previous,
      chatMessages: [
        ...previous.chatMessages,
        {
          id: `user_answer_${Date.now()}`,
          role: "user",
          text: answer
        }
      ]
    }));

    try {
      await submitAnswer(state.runId, questionId, answer);
    } catch (error) {
      setState((previous) => ({
        ...previous,
        errors: [...previous.errors, error instanceof Error ? error.message : String(error)]
      }));
    }
  }

  async function handleRetry(agentId?: string) {
    if (!state.runId) return;

    try {
      await retryRun(state.runId, agentId);
    } catch (error) {
      setState((previous) => ({
        ...previous,
        errors: [...previous.errors, error instanceof Error ? error.message : String(error)]
      }));
    }
  }

  function handleToggleNode(nodeId: string) {
    setState((previous) => toggleNodeExpanded(previous, nodeId));
  }

  return {
    state,
    startRun: handleStartRun,
    submitAnswer: handleSubmitAnswer,
    retry: handleRetry,
    toggleNode: handleToggleNode
  };
}