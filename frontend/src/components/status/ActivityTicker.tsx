type Props = {
  activity: string[];
};

export function ActivityTicker({ activity }: Props) {
  return (
    <section className="activity-panel">
      <h2>Activity Ticker</h2>
      {activity.length === 0 ? (
        <p className="empty">No activity yet.</p>
      ) : (
        <ul>
          {activity.map((item, index) => (
            <li key={`${item}_${index}`}>{item}</li>
          ))}
        </ul>
      )}
    </section>
  );
}