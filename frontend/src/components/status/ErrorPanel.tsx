type Props = {
  errors: string[];
  canRetry: boolean;
  onRetry: () => void;
};

export function ErrorPanel({ errors, canRetry, onRetry }: Props) {
  if (errors.length === 0) return null;

  return (
    <section className="panel error-panel">
      <div className="panel-header">
        <div>
          <span className="section-kicker">System alerts</span>
          <h2>Errors</h2>
        </div>
      </div>

      <div className="error-list">
        {errors.map((error, index) => (
          <div key={`${error}_${index}`} className="error-card">
            {error}
          </div>
        ))}
      </div>

      {canRetry && (
        <button type="button" className="secondary-button" onClick={onRetry}>
          Retry run
        </button>
      )}
    </section>
  );
}