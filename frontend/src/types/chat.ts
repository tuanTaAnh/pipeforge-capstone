export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | "system";
  text: string;
};