import type { Artifact } from "../../types/artifact";

type Props = {
  artifact: Artifact;
};

export function ArtifactCard({ artifact }: Props) {
  return (
    <div className="artifact-card">
      <div className="artifact-header">
        <strong>{artifact.filename}</strong>
        <span>{artifact.type}</span>
      </div>

      <small>Created by {artifact.createdByAgentName}</small>

      <pre>{artifact.contentPreview}</pre>

      <button onClick={() => navigator.clipboard.writeText(artifact.contentPreview)}>
        Copy preview
      </button>
    </div>
  );
}