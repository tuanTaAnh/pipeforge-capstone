import { useState } from "react";

import { samplePrompt } from "../../state/initialState";
import type { ChatMessage } from "../../types/chat";
import type { AnswerSubmission, AskUserQuestion, RunStatus } from "../../types/run";
import { AskUserCard } from "./AskUserCard";
import { MessageList } from "./MessageList";
import { PromptBox } from "./PromptBox";

type Props = {
  messages: ChatMessage[];
  status: RunStatus;
  pendingQuestion?: AskUserQuestion;
  showPendingQuestion?: boolean;
  onOpenDecision?: () => void;
  onStartRun: (prompt: string) => void;
  onSubmitAnswer: (submission: AnswerSubmission) => void;
};

function statusLabel(status: RunStatus) {
  if (status === "waiting_for_user") return "decision required";
  if (status === "running") return "agent running";
  if (status === "completed") return "completed";
  if (status === "failed") return "failed";
  return "ready";
}

export function ChatPanel({
  messages,
  status,
  pendingQuestion,
  showPendingQuestion = true,
  onOpenDecision,
  onStartRun,
  onSubmitAnswer
}: Props) {
  const [prompt, setPrompt] = useState(samplePrompt);

  const isRunning = status === "running" || status === "waiting_for_user";
  const shouldShowPromptBox = status !== "waiting_for_user";

  return (
    <section className="panel chat-panel">
      <div className="panel-header">
        <div>
          <span className="section-kicker">Request console</span>
          <h2>Business request</h2>
        </div>

        <span className={`run-pill run-pill-${status}`}>
          {statusLabel(status)}
        </span>
      </div>

      <div className="chat-scroll-region">
        <MessageList messages={messages} />

        {!showPendingQuestion && pendingQuestion && (
          <div className="decision-nudge">
            <div>
              <span className="section-kicker">Action required</span>
              <strong>The workflow is waiting for your business decision.</strong>
              <p>
                PipeForge is paused so you can choose how this data quality issue
                should be handled before artifacts are generated.
              </p>
            </div>

            <button type="button" onClick={onOpenDecision}>
              Open Decision tab
            </button>
          </div>
        )}

        {showPendingQuestion && pendingQuestion && (
          <AskUserCard question={pendingQuestion} onSubmit={onSubmitAnswer} />
        )}
      </div>

      {shouldShowPromptBox && (
        <PromptBox
          prompt={prompt}
          disabled={isRunning}
          onPromptChange={setPrompt}
          onStart={() => onStartRun(prompt)}
        />
      )}
    </section>
  );
}