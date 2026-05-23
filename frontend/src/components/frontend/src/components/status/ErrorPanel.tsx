type Props = {
  errors: string[];
  canRetry: boolean;
  onRetry: () => void;
};

export function ErrorPanel({ errors, canRetry, onRetry }: Props) {
  if (errors.length === 0) return null;

  return (
    <section className="error-panel">
      <h2>Errors</h2>
      {errors.map((error, index) => (
        <div key={`${error}_${index}`} className="error-card">
          {error}
        </div>
      ))}
      {canRetry && <button onClick={onRetry}>Retry</button>}
    </section>
  );
}