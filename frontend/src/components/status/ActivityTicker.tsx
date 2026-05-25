type Props = {
  activity: string[];
};

export function ActivityTicker({ activity }: Props) {
  return (
    <section className="panel activity-panel">
      <div className="panel-header">
        <div>
          <span className="section-kicker">Operations</span>
          <h2>Activity</h2>
        </div>
        <span className="count-pill">{activity.length} latest</span>
      </div>

      {activity.length === 0 ? (
        <div className="empty-state compact-empty">
          <strong>No activity yet</strong>
          <p>Run events will be streamed here.</p>
        </div>
      ) : (
        <ol className="activity-feed">
          {activity.map((item, index) => (
            <li key={`${item}_${index}`}>
              <span className="activity-dot" />
              <p>{item}</p>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}