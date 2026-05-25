import { useState } from "react";

import type { AnswerSubmission, AskUserQuestion } from "../../types/run";

type Props = {
  question: AskUserQuestion;
  onSubmit: (submission: AnswerSubmission) => void;
};

export function AskUserCard({ question, onSubmit }: Props) {
  const [customAnswer, setCustomAnswer] = useState("");

  const recommendedOption = question.options.find(
    (option) => option.id === question.recommendedOptionId
  );

  function submitTypedAnswer() {
    const value = customAnswer.trim();
    if (!value) return;

    onSubmit({
      answer: value,
      customAnswer: value
    });

    setCustomAnswer("");
  }

  function submitOption(optionId: string, label: string) {
    onSubmit({
      answer: label,
      selectedOptionId: optionId
    });
  }

  return (
    <article className="decision-card">
      <div className="decision-card-header">
        <div>
          <span className="section-kicker">Human-in-the-loop decision</span>
          <h3>Agent needs your business rule</h3>
        </div>
        <span className={`priority-pill priority-${question.priority}`}>
          {question.priority === "must_answer" ? "Must answer" : "Optional review"}
        </span>
      </div>

      {question.issueSummary && (
        <div className="decision-context">
          <span>Detected issue</span>
          <p>{question.issueSummary}</p>
        </div>
      )}

      <div className="decision-question">
        <span>Question</span>
        <p>{question.question}</p>
      </div>

      {recommendedOption && (
        <div className="recommended-decision">
          <span>Recommended option</span>
          <strong>{recommendedOption.label}</strong>
          {question.recommendationReason && (
            <p>{question.recommendationReason}</p>
          )}
        </div>
      )}

      {question.validationError && (
        <div className="validation-error">{question.validationError}</div>
      )}

      <div className="decision-options">
        {question.options.map((option) => (
          <button
            type="button"
            key={option.id}
            onClick={() => submitOption(option.id, option.label)}
            className={
              option.id === question.recommendedOptionId
                ? "decision-option decision-option-recommended"
                : "decision-option"
            }
          >
            <span>{option.label}</span>

            {option.implementation && (
              <small>{option.implementation}</small>
            )}

            {option.resolved_rule && (
              <code>{option.resolved_rule}</code>
            )}
          </button>
        ))}
      </div>

      {question.allowCustomAnswer && (
        <div className="custom-decision">
          <label htmlFor="custom-business-rule">Custom handling rule</label>
          <textarea
            id="custom-business-rule"
            value={customAnswer}
            onChange={(event) => setCustomAnswer(event.target.value)}
            placeholder="Type your own handling rule..."
          />
          <button type="button" onClick={submitTypedAnswer}>
            Send custom answer
          </button>
        </div>
      )}
    </article>
  );
}