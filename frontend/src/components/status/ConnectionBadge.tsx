type Props = {
  connected: boolean;
};

export function ConnectionBadge({ connected }: Props) {
  return (
    <div className={`connection ${connected ? "online" : "offline"}`}>
      {connected ? "stream connected" : "stream offline"}
    </div>
  );
}