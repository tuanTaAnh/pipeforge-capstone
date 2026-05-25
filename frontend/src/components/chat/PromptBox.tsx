type Props = {
  prompt: string;
  disabled: boolean;
  onPromptChange: (prompt: string) => void;
  onStart: () => void;
};

export function PromptBox({ prompt, disabled, onPromptChange, onStart }: Props) {
  const canStart = !disabled && prompt.trim().length > 0;

  return (
    <form
      className="prompt-composer"
      onSubmit={(event) => {
        event.preventDefault();
        if (canStart) onStart();
      }}
    >
      <div className="composer-header">
        <div>
          <span className="section-kicker">New run</span>
          <strong>Describe the analytics product you need</strong>
        </div>
      </div>

      <textarea
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
        disabled={disabled}
        placeholder="Example: Build a trusted monthly revenue dataset from Stripe invoices for a billing dashboard..."
      />

      <div className="composer-footer">
        <span>PipeForge will select a source, profile the data, ask decisions, then generate artifacts.</span>
        <button type="submit" disabled={!canStart}>
          Start run
        </button>
      </div>
    </form>
  );
}