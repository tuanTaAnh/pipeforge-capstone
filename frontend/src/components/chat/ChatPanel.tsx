import { useState } from "react";

import { samplePrompt } from "../../state/initialState";
import type { ChatMessage } from "../../types/chat";
import type { AskUserQuestion, RunStatus } from "../../types/run";
import { AskUserCard } from "./AskUserCard";
import { MessageList } from "./MessageList";
import { PromptBox } from "./PromptBox";

type Props = {
  messages: ChatMessage[];
  status: RunStatus;
  pendingQuestion?: AskUserQuestion;
  onStartRun: (prompt: string) => void;
  onSubmitAnswer: (answer: string) => void;
};

export function ChatPanel({
  messages,
  status,
  pendingQuestion,
  onStartRun,
  onSubmitAnswer
}: Props) {
  const [prompt, setPrompt] = useState(samplePrompt);

  const isRunning = status === "running" || status === "waiting_for_user";

  return (
    <section className="chat-panel">
      <h2>Chat</h2>

      <MessageList messages={messages} />

      {pendingQuestion && (
        <AskUserCard question={pendingQuestion} onSubmit={onSubmitAnswer} />
      )}

      <PromptBox
        prompt={prompt}
        disabled={isRunning}
        onPromptChange={setPrompt}
        onStart={() => onStartRun(prompt)}
      />
    </section>
  );
}