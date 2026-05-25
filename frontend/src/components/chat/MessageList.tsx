import type { ChatMessage } from "../../types/chat";

type Props = {
  messages: ChatMessage[];
};

function roleLabel(role: ChatMessage["role"]) {
  if (role === "assistant") return "PipeForge";
  if (role === "system") return "System";
  return "You";
}

function roleInitial(role: ChatMessage["role"]) {
  if (role === "assistant") return "AI";
  if (role === "system") return "S";
  return "U";
}

export function MessageList({ messages }: Props) {
  return (
    <div className="message-list">
      {messages.map((message) => (
        <article
          key={message.id}
          className={`message-bubble message-bubble-${message.role}`}
        >
          <div className="message-avatar">{roleInitial(message.role)}</div>

          <div className="message-content">
            <div className="message-meta">
              <strong>{roleLabel(message.role)}</strong>
            </div>
            <p>{message.text}</p>
          </div>
        </article>
      ))}
    </div>
  );
}