type Props = {
  prompt: string;
  disabled: boolean;
  onPromptChange: (prompt: string) => void;
  onStart: () => void;
};

export function PromptBox({ prompt, disabled, onPromptChange, onStart }: Props) {
  return (
    <div className="prompt-box">
      <textarea
        value={prompt}
        onChange={(event) => onPromptChange(event.target.value)}
        disabled={disabled}
      />
      <button onClick={onStart} disabled={disabled}>
        Start run
      </button>
    </div>
  );
}