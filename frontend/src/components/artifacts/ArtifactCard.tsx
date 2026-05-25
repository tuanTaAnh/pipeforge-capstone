import type { Artifact } from "../../types/artifact";

type Props = {
  artifact: Artifact;
  selected: boolean;
  copied: boolean;
  loading?: boolean;
  content?: string;
  onSelect: (artifact: Artifact) => void;
  onCopy: (artifact: Artifact) => void;
};

function artifactIcon(type: string) {
  if (type === "sql") return "SQL";
  if (type === "yaml") return "YML";
  if (type === "markdown") return "MD";
  if (type === "json") return "JSON";
  return "TXT";
}

function countLines(content: string) {
  if (!content.trim()) return 0;
  return content.split(/\r\n|\r|\n/).length;
}

function getFallbackArtifactContent(artifact: Artifact) {
  return artifact.content ?? artifact.contentPreview ?? "";
}

export function ArtifactCard({
  artifact,
  selected,
  copied,
  loading = false,
  content,
  onSelect,
  onCopy
}: Props) {
  const displayContent = content ?? getFallbackArtifactContent(artifact);
  const lineCount = countLines(displayContent);

  return (
    <article className={selected ? "artifact-list-item selected" : "artifact-list-item"}>
      <button
        type="button"
        className="artifact-list-main"
        onClick={() => onSelect(artifact)}
        aria-pressed={selected}
      >
        <div className={`artifact-file-icon artifact-file-${artifact.type}`}>
          {artifactIcon(artifact.type)}
        </div>

        <div className="artifact-list-copy">
          <strong>{artifact.filename}</strong>
          <span>Created by {artifact.createdByAgentName}</span>

          <div className="artifact-list-meta">
            <em>{artifact.type}</em>
            <em>{loading ? "loading" : `${lineCount} lines`}</em>
          </div>
        </div>
      </button>

      <button
        type="button"
        className="artifact-row-copy"
        onClick={() => onCopy(artifact)}
        disabled={loading}
      >
        {copied ? "Copied" : "Copy"}
      </button>
    </article>
  );
}