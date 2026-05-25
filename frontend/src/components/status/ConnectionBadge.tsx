type Props = {
  connected: boolean;
};

export function ConnectionBadge({ connected }: Props) {
  return (
    <div className={`connection-badge ${connected ? "connected" : "disconnected"}`}>
      <span className="connection-dot" />
      {connected ? "Stream connected" : "Stream offline"}
    </div>
  );
}