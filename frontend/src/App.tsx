import "./App.css";

import { ArtifactPanel } from "./components/artifacts/ArtifactPanel";
import { ChatPanel } from "./components/chat/ChatPanel";
import { ActivityTicker } from "./components/status/ActivityTicker";
import { ConnectionBadge } from "./components/status/ConnectionBadge";
import { ErrorPanel } from "./components/status/ErrorPanel";
import { TraceTreePanel } from "./components/trace/TraceTreePanel";
import { useRunController } from "./hooks/useRunController";

function App() {
  const controller = useRunController();
  const { state } = controller;

  return (
    <div className="app">
      <header>
        <div>
          <h1>PipeForge</h1>
          <p>Transparent AI Data Product Builder</p>
        </div>
        <ConnectionBadge connected={state.connected} />
      </header>

      <main>
        <ChatPanel
          messages={state.chatMessages}
          status={state.status}
          pendingQuestion={state.pendingQuestion}
          onStartRun={controller.startRun}
          onSubmitAnswer={controller.submitAnswer}
        />

        <TraceTreePanel state={state} onToggleNode={controller.toggleNode} />
      </main>

      <ActivityTicker activity={state.activity} />

      <ArtifactPanel artifacts={state.artifacts} />

      <ErrorPanel
        errors={state.errors}
        canRetry={state.status === "failed"}
        onRetry={() => controller.retry()}
      />
    </div>
  );
}

export default App;