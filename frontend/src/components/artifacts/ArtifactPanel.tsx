import { useEffect, useMemo, useState } from "react";
import { getArtifactContent } from "../../api/runsApi";
import type { Artifact } from "../../types/artifact";
import { ArtifactCard } from "./ArtifactCard";

type Props = {
  artifacts: Artifact[];
};

type ArtifactLoadError = {
  artifactId: string;
  message: string;
};

function artifactIcon(type: string) {
  if (type === "sql") return "SQL";
  if (type === "yaml") return "YML";
  if (type === "markdown") return "MD";
  if (type === "json") return "JSON";
  return "TXT";
}

function getFallbackArtifactContent(artifact: Artifact) {
  return artifact.content ?? artifact.contentPreview ?? "";
}

function getDisplayedArtifactContent(
  artifact: Artifact,
  fullContentByArtifactId: Record<string, string>
) {
  return fullContentByArtifactId[artifact.id] ?? getFallbackArtifactContent(artifact);
}

function countLines(content: string) {
  if (!content.trim()) return 0;
  return content.split(/\r\n|\r|\n/).length;
}

function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return String(error);
}

export function ArtifactPanel({ artifacts }: Props) {
  const [selectedArtifactId, setSelectedArtifactId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState("all");
  const [copiedArtifactId, setCopiedArtifactId] = useState<string | null>(null);
  const [fullContentByArtifactId, setFullContentByArtifactId] = useState<Record<string, string>>(
    {}
  );
  const [loadingArtifactId, setLoadingArtifactId] = useState<string | null>(null);
  const [artifactLoadError, setArtifactLoadError] = useState<ArtifactLoadError | null>(null);

  const artifactTypes = useMemo(() => {
    return Array.from(new Set(artifacts.map((artifact) => artifact.type)));
  }, [artifacts]);

  const filteredArtifacts = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();

    return artifacts.filter((artifact) => {
      const matchesType = typeFilter === "all" || artifact.type === typeFilter;
      const matchesQuery =
        normalizedQuery.length === 0 ||
        artifact.filename.toLowerCase().includes(normalizedQuery) ||
        artifact.createdByAgentName.toLowerCase().includes(normalizedQuery) ||
        artifact.type.toLowerCase().includes(normalizedQuery);

      return matchesType && matchesQuery;
    });
  }, [artifacts, query, typeFilter]);

  const selectedArtifact = useMemo(() => {
    if (filteredArtifacts.length === 0) return null;

    return (
      filteredArtifacts.find((artifact) => artifact.id === selectedArtifactId) ??
      filteredArtifacts[0]
    );
  }, [filteredArtifacts, selectedArtifactId]);

  const selectedArtifactContent = selectedArtifact
    ? getDisplayedArtifactContent(selectedArtifact, fullContentByArtifactId)
    : "";

  const selectedArtifactIsLoading =
    selectedArtifact !== null && loadingArtifactId === selectedArtifact.id;

  const selectedArtifactError =
    selectedArtifact !== null && artifactLoadError?.artifactId === selectedArtifact.id
      ? artifactLoadError.message
      : null;

  useEffect(() => {
    const activeArtifactIds = new Set(artifacts.map((artifact) => artifact.id));

    setFullContentByArtifactId((currentContent) => {
      const nextContent: Record<string, string> = {};

      for (const [artifactId, content] of Object.entries(currentContent)) {
        if (activeArtifactIds.has(artifactId)) {
          nextContent[artifactId] = content;
        }
      }

      return nextContent;
    });
  }, [artifacts]);

  useEffect(() => {
    if (filteredArtifacts.length === 0) {
      setSelectedArtifactId(null);
      return;
    }

    const selectedArtifactStillVisible = filteredArtifacts.some(
      (artifact) => artifact.id === selectedArtifactId
    );

    if (!selectedArtifactStillVisible) {
      setSelectedArtifactId(filteredArtifacts[0].id);
    }
  }, [filteredArtifacts, selectedArtifactId]);

  useEffect(() => {
    if (!selectedArtifact) return;

    const alreadyLoaded =
      fullContentByArtifactId[selectedArtifact.id] !== undefined ||
      typeof selectedArtifact.content === "string";

    if (alreadyLoaded) return;

    const controller = new AbortController();

    setLoadingArtifactId(selectedArtifact.id);
    setArtifactLoadError((currentError) =>
      currentError?.artifactId === selectedArtifact.id ? null : currentError
    );

    getArtifactContent(selectedArtifact.runId, selectedArtifact.id, {
      signal: controller.signal
    })
      .then((response) => {
        setFullContentByArtifactId((currentContent) => ({
          ...currentContent,
          [selectedArtifact.id]: response.content ?? ""
        }));
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;

        setArtifactLoadError({
          artifactId: selectedArtifact.id,
          message: getErrorMessage(error)
        });
      })
      .finally(() => {
        if (controller.signal.aborted) return;

        setLoadingArtifactId((currentId) =>
          currentId === selectedArtifact.id ? null : currentId
        );
      });

    return () => {
      controller.abort();
    };
  }, [fullContentByArtifactId, selectedArtifact]);

  async function ensureFullArtifactContent(artifact: Artifact) {
    const cachedContent = fullContentByArtifactId[artifact.id];

    if (cachedContent !== undefined) {
      return cachedContent;
    }

    if (typeof artifact.content === "string") {
      return artifact.content;
    }

    setLoadingArtifactId(artifact.id);
    setArtifactLoadError((currentError) =>
      currentError?.artifactId === artifact.id ? null : currentError
    );

    try {
      const response = await getArtifactContent(artifact.runId, artifact.id);
      const content = response.content ?? "";

      setFullContentByArtifactId((currentContent) => ({
        ...currentContent,
        [artifact.id]: content
      }));

      return content;
    } catch (error) {
      const message = getErrorMessage(error);

      setArtifactLoadError({
        artifactId: artifact.id,
        message
      });

      return getFallbackArtifactContent(artifact);
    } finally {
      setLoadingArtifactId((currentId) => (currentId === artifact.id ? null : currentId));
    }
  }

  async function copyArtifact(artifact: Artifact) {
    const content = await ensureFullArtifactContent(artifact);

    try {
      await navigator.clipboard.writeText(content);
      setCopiedArtifactId(artifact.id);

      window.setTimeout(() => {
        setCopiedArtifactId((currentId) => (currentId === artifact.id ? null : currentId));
      }, 1400);
    } catch (error) {
      console.error("Failed to copy artifact content", error);
    }
  }

  return (
    <section className="panel artifact-panel">
      <div className="panel-header artifact-panel-header">
        <div>
          <span className="section-kicker">Generated package</span>
          <h2>Artifacts</h2>
        </div>

        <span className="count-pill">{artifacts.length} files</span>
      </div>

      {artifacts.length === 0 ? (
        <div className="empty-state artifact-empty">
          <div className="empty-icon">□</div>
          <strong>No artifacts generated yet</strong>
          <p>SQL models, YAML schema files, tests, and documentation will appear here.</p>
        </div>
      ) : (
        <div className="artifact-workspace">
          <aside className="artifact-browser" aria-label="Generated artifact files">
            <div className="artifact-toolbar">
              <label htmlFor="artifact-search">Search generated files</label>
              <input
                id="artifact-search"
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search by filename, type, or agent..."
              />
            </div>

            <div className="artifact-filter-row" aria-label="Filter artifacts by type">
              <button
                type="button"
                className={typeFilter === "all" ? "active" : ""}
                onClick={() => setTypeFilter("all")}
              >
                All
              </button>

              {artifactTypes.map((type) => (
                <button
                  key={type}
                  type="button"
                  className={typeFilter === type ? "active" : ""}
                  onClick={() => setTypeFilter(type)}
                >
                  {type}
                </button>
              ))}
            </div>

            <div className="artifact-list" role="list">
              {filteredArtifacts.length === 0 ? (
                <div className="empty-state compact-empty">
                  <strong>No matching files</strong>
                  <p>Try another filename, type, or creator.</p>
                </div>
              ) : (
                filteredArtifacts.map((artifact) => (
                  <ArtifactCard
                    key={artifact.id}
                    artifact={artifact}
                    selected={selectedArtifact?.id === artifact.id}
                    copied={copiedArtifactId === artifact.id}
                    loading={loadingArtifactId === artifact.id}
                    content={getDisplayedArtifactContent(artifact, fullContentByArtifactId)}
                    onSelect={(nextArtifact) => setSelectedArtifactId(nextArtifact.id)}
                    onCopy={copyArtifact}
                  />
                ))
              )}
            </div>
          </aside>

          <section
            className="artifact-preview-pane"
            aria-label="Artifact preview"
            aria-busy={selectedArtifactIsLoading}
          >
            {selectedArtifact ? (
              <>
                <div className="artifact-preview-header">
                  <div className={`artifact-file-icon artifact-file-${selectedArtifact.type}`}>
                    {artifactIcon(selectedArtifact.type)}
                  </div>

                  <div className="artifact-preview-title">
                    <span className="section-kicker">Preview</span>
                    <h3>{selectedArtifact.filename}</h3>
                    <p>
                      Created by {selectedArtifact.createdByAgentName} ·{" "}
                      {selectedArtifact.type} · {countLines(selectedArtifactContent)} lines
                    </p>
                    {selectedArtifactIsLoading && (
                      <p className="muted-copy">Loading full artifact content...</p>
                    )}
                  </div>

                  <button
                    type="button"
                    onClick={() => copyArtifact(selectedArtifact)}
                    disabled={selectedArtifactIsLoading}
                  >
                    {copiedArtifactId === selectedArtifact.id ? "Copied" : "Copy full content"}
                  </button>
                </div>

                {selectedArtifactError && (
                  <div className="validation-error">
                    Could not load full artifact content. Showing preview only.
                    <br />
                    {selectedArtifactError}
                  </div>
                )}

                <pre className="artifact-preview-code">{selectedArtifactContent}</pre>
              </>
            ) : (
              <div className="empty-state artifact-preview-empty">
                <div className="empty-icon">□</div>
                <strong>Select a file to preview</strong>
                <p>Choose a generated artifact from the list to inspect or copy its content.</p>
              </div>
            )}
          </section>
        </div>
      )}
    </section>
  );
}