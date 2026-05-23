import type { ChatMessage } from "../../types/chat";

type Props = {
  messages: ChatMessage[];
};

export function MessageList({ messages }: Props) {
  return (
    <div className="messages">
      {messages.map((message) => (
        <div key={message.id} className={`message ${message.role}`}>
          <strong>{message.role}</strong>
          <p>{message.text}</p>
        </div>
      ))}
    </div>
  );
}