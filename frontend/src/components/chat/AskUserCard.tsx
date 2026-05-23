import { useState } from "react";

import type { AskUserQuestion } from "../../types/run";

type Props = {
  question: AskUserQuestion;
  onSubmit: (answer: string) => void;
};

export function AskUserCard({ question, onSubmit }: Props) {
  const [answer, setAnswer] = useState("");

  function submitTypedAnswer() {
    if (!answer.trim()) return;
    onSubmit(answer);
    setAnswer("");
  }

  return (
    <div className="ask-card">
      <h3>Agent needs your decision</h3>
      <p>{question.question}</p>

      <div className="option-list">
        {question.options.map((option) => (
          <button key={option} onClick={() => onSubmit(option)}>
            {option}
          </button>
        ))}
      </div>

      <textarea
        value={answer}
        onChange={(event) => setAnswer(event.target.value)}
        placeholder="Or type your own answer..."
      />
      <button onClick={submitTypedAnswer}>Send answer</button>
    </div>
  );
}