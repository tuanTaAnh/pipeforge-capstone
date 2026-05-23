import type { Artifact } from "../../types/artifact";
import { ArtifactCard } from "./ArtifactCard";

type Props = {
  artifacts: Artifact[];
};

export function ArtifactPanel({ artifacts }: Props) {
  return (
    <section className="artifact-panel">
      <h2>Artifacts</h2>

      {artifacts.length === 0 ? (
        <p className="empty">Generated SQL, YAML, and Markdown files will appear here.</p>
      ) : (
        <div className="artifact-grid">
          {artifacts.map((artifact) => (
            <ArtifactCard key={artifact.id} artifact={artifact} />
          ))}
        </div>
      )}
    </section>
  );
}