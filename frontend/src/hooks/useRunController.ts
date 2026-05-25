import { useState } from "react";

import { retryRun, startRun, submitAnswer } from "../api/runsApi";
import { createInitialState, initialState } from "../state/initialState";
import { applyEvent, toggleNodeExpanded } from "../state/runReducer";
import type { AgentEvent } from "../types/event";
import type { AnswerSubmission, RunState } from "../types/run";
import { useEventStream } from "./useEventStream";

const DISCONNECTED_MESSAGE = "Event stream disconnected. Reconnecting...";

function appendUniqueError(errors: string[], message: string) {
  if (errors.includes(message)) return errors;
  return [...errors, message];
}

function getSubmissionDisplayText(submission: AnswerSubmission): string {
  return (
    submission.answer ||
    submission.customAnswer ||
    submission.selectedOptionId ||
    "Submitted answer"
  );
}

export function useRunController() {
  const [state, setState] = useState<RunState>(initialState);

  const stream = useEventStream({
    onEvent: (event: AgentEvent) => {
      setState((previous) => applyEvent(previous, event));
    },
    onDisconnected: () => {
      setState((previous) => {
        if (previous.status === "completed" || previous.status === "failed") {
          return {
            ...previous,
            connected: false
          };
        }

        return {
          ...previous,
          connected: false,
          errors: appendUniqueError(previous.errors, DISCONNECTED_MESSAGE)
        };
      });
    }
  });

  function handleResetRun() {
    stream.close();
    setState(createInitialState());
  }

  async function handleStartRun(prompt: string) {
    stream.close();

    const freshState = createInitialState();

    setState({
      ...freshState,
      status: "running",
      chatMessages: [
        ...freshState.chatMessages,
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
        errors: [
          ...previous.errors,
          error instanceof Error ? error.message : String(error)
        ]
      }));
    }
  }

  async function handleSubmitAnswer(submission: AnswerSubmission) {
    if (!state.pendingQuestion || !state.runId) return;

    const questionId = state.pendingQuestion.questionId;

    setState((previous) => ({
      ...previous,
      chatMessages: [
        ...previous.chatMessages,
        {
          id: `user_answer_${Date.now()}`,
          role: "user",
          text: getSubmissionDisplayText(submission)
        }
      ]
    }));

    try {
      await submitAnswer(state.runId, questionId, submission);
    } catch (error) {
      setState((previous) => ({
        ...previous,
        errors: [
          ...previous.errors,
          error instanceof Error ? error.message : String(error)
        ]
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
        errors: [
          ...previous.errors,
          error instanceof Error ? error.message : String(error)
        ]
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
    resetRun: handleResetRun,
    toggleNode: handleToggleNode
  };
}