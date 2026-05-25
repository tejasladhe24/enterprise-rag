import { useState } from "react";
import { env } from "./env";

type SearchChunk = {
  id: number;
  document_id: number;
  text: string;
  chunk_index: number;
  token_count: number;
  score?: number | null;
};

async function uploadPart(url: string, blob: Blob) {
  const response = await fetch(url, { method: "PUT", body: blob });
  if (!response.ok) throw new Error(`Part upload failed (${response.status})`);
  const etag = response.headers.get("ETag");
  if (!etag) throw new Error("Missing ETag in part upload response");
  return etag.replaceAll('"', "");
}

async function uploadZip(apiBase: string, file: File) {
  const formData = new FormData();
  formData.append("file", file);
  const response = await fetch(`${apiBase}/api/uploads/zip`, {
    method: "POST",
    body: formData,
  });
  if (!response.ok)
    throw new Error(`Zip upload failed: ${await response.text()}`);
  return response.json() as Promise<{
    files: { filename: string }[];
    skipped: string[];
  }>;
}

async function uploadSingleFile(apiBase: string, file: File) {
  const urlsResponse = await fetch(`${apiBase}/api/uploads/multipart/urls`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      filename: file.name,
      file_size: file.size,
      content_type: file.type || "application/octet-stream",
    }),
  });
  if (!urlsResponse.ok)
    throw new Error(`Init failed: ${await urlsResponse.text()}`);

  const { upload_id, key, part_size, parts } = await urlsResponse.json();
  const completedParts = [];

  for (const { part_number, url } of parts) {
    const start = (part_number - 1) * part_size;
    const end = Math.min(start + part_size, file.size);
    const etag = await uploadPart(url, file.slice(start, end));
    completedParts.push({ part_number, etag });
  }

  const completeResponse = await fetch(
    `${apiBase}/api/uploads/multipart/complete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_id, key, parts: completedParts }),
    },
  );
  if (!completeResponse.ok)
    throw new Error(`Complete failed: ${await completeResponse.text()}`);
  return completeResponse.json() as Promise<{ key: string }>;
}

const base = env.BUN_PUBLIC_API_BASE_URL.replace(/\/$/, "");

export function App() {
  const [uploadStatus, setUploadStatus] = useState("");
  const [searchStatus, setSearchStatus] = useState("");
  const [searchResults, setSearchResults] = useState<SearchChunk[]>([]);
  const [busy, setBusy] = useState<"upload" | "search" | null>(null);

  async function onUpload(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = event.currentTarget;
    const file = (form.elements.namedItem("file") as HTMLInputElement)
      .files?.[0];
    if (!file) {
      setUploadStatus("Choose a file first.");
      return;
    }

    setBusy("upload");
    setUploadStatus("Uploading…");

    try {
      if (file.name.toLowerCase().endsWith(".zip")) {
        const { files, skipped } = await uploadZip(base, file);
        let message = `Uploaded ${files.length} file(s).`;
        if (files.length)
          message += `\nFiles: ${files.map((f) => f.filename).join(", ")}`;
        if (skipped.length) message += `\nSkipped: ${skipped.join(", ")}`;
        setUploadStatus(message);
      } else {
        const result = await uploadSingleFile(base, file);
        setUploadStatus(`Upload complete.\nKey: ${result.key}`);
      }
      form.reset();
    } catch (error) {
      setUploadStatus(
        `Error: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setBusy(null);
    }
  }

  async function onSearch(event: React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = (
      event.currentTarget.elements.namedItem("query") as HTMLInputElement
    ).value.trim();
    if (!query) {
      setSearchStatus("Enter a search query.");
      return;
    }

    setBusy("search");
    setSearchStatus("Searching…");
    setSearchResults([]);

    try {
      const response = await fetch(`${base}/api/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query }),
      });
      if (!response.ok) throw new Error(await response.text());

      const { chunks } = (await response.json()) as { chunks: SearchChunk[] };
      setSearchStatus(`${chunks.length} chunk(s) found.`);
      setSearchResults(chunks);
    } catch (error) {
      setSearchStatus(
        `Error: ${error instanceof Error ? error.message : String(error)}`,
      );
    } finally {
      setBusy(null);
    }
  }

  return (
    <main
      style={{
        maxWidth: "40rem",
        margin: "2rem auto",
        padding: "0 1rem",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <h1>Enterprise RAG</h1>
      <p>Upload documents and search ingested chunks.</p>
      <section style={{ marginBottom: "2rem" }}>
        <h2>Upload</h2>
        <form onSubmit={onUpload}>
          <label htmlFor="file">File</label>
          <br />
          <input
            id="file"
            name="file"
            type="file"
            accept=".zip,.pdf,.doc,.docx,.txt,.md"
            required
            style={{ width: "100%", marginBottom: "1rem" }}
          />
          <button type="submit" disabled={busy === "upload"}>
            {busy === "upload" ? "Uploading…" : "Upload"}
          </button>
        </form>
        {uploadStatus ? (
          <pre style={{ whiteSpace: "pre-wrap" }}>{uploadStatus}</pre>
        ) : null}
      </section>

      <section>
        <h2>Search</h2>
        <form
          onSubmit={onSearch}
          style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}
        >
          <input
            id="query"
            name="query"
            type="text"
            placeholder="e.g. Celery task queue"
            required
            style={{ flex: 1, padding: "0.4rem" }}
          />
          <button type="submit" disabled={busy === "search"}>
            {busy === "search" ? "Searching…" : "Search"}
          </button>
        </form>
        {searchStatus ? <p>{searchStatus}</p> : null}
        {searchResults.map((chunk) => (
          <article
            key={chunk.id}
            style={{
              border: "1px solid #ccc",
              padding: "0.75rem",
              marginTop: "0.75rem",
            }}
          >
            <div
              style={{
                fontSize: "0.85rem",
                color: "#666",
                marginBottom: "0.5rem",
              }}
            >
              doc {chunk.document_id} · chunk #{chunk.chunk_index} ·{" "}
              {chunk.token_count} tokens
              {chunk.score != null
                ? ` · score ${Number(chunk.score).toFixed(4)}`
                : ""}
            </div>
            <p style={{ margin: 0, whiteSpace: "pre-wrap" }}>{chunk.text}</p>
          </article>
        ))}
      </section>
    </main>
  );
}

export default App;
