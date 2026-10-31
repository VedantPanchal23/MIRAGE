import React, { useState, useEffect } from "react";
import {
  BookOpen,
  UploadCloud,
  Trash2,
  Search,
  CheckCircle,
  FileText,
  Layers,
  Database,
  ShieldCheck,
  AlertCircle,
} from "lucide-react";
import { api } from "../api";
import { useAuth } from "../context/AuthContext";

export function KnowledgeBaseView() {
  const { tenantId } = useAuth();
  const [documents, setDocuments] = useState([]);
  const [loading, setLoading] = useState(true);

  // New Document Upload State
  const [filename, setFilename] = useState("");
  const [content, setContent] = useState("");
  const [collectionName, setCollectionName] = useState("default_kb");
  const [isUploading, setIsUploading] = useState(false);
  const [uploadSuccess, setUploadSuccess] = useState(null);
  const [uploadError, setUploadError] = useState(null);

  // Search Tester State
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState([]);
  const [isSearching, setIsSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [hasSearched, setHasSearched] = useState(false);

  const loadDocuments = async () => {
    try {
      const res = await api.getKBDocuments();
      if (res && Array.isArray(res.documents) && res.documents.length > 0) {
        setDocuments(res.documents);
      } else {
        setDocuments([]);
      }
    } catch {
      setDocuments([]);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadDocuments();
  }, [tenantId]);

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!filename.trim() || !content.trim()) {
      setUploadError("Filename and document content are required.");
      return;
    }

    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);

    const chunkCount = Math.max(1, Math.ceil(content.trim().length / 500));
    const sizeBytes = new Blob([content.trim()]).size;
    const formattedSize = sizeBytes > 1024 ? `${(sizeBytes / 1024).toFixed(1)} KB` : `${sizeBytes} B`;

    try {
      await api.uploadKBDocument(filename.trim(), content.trim(), collectionName);
      setUploadSuccess(`Document "${filename}" ingested (${formattedSize}, ~${chunkCount} chunks) and indexed to Qdrant collection "${collectionName}".`);
      setFilename("");
      setContent("");
      await loadDocuments();
    } catch (err) {
      setUploadError(err.message || "Failed to ingest document into vector store.");
    } finally {
      setIsUploading(false);
    }
  };

  const handleDelete = async (docId) => {
    try {
      await api.deleteKBDocument(docId);
      setDocuments((prev) => prev.filter((d) => d.document_id !== docId));
    } catch (err) {
      setUploadError(err.message || `Failed to delete document ${docId}`);
    }
  };

  const handleSearch = async (e) => {
    e.preventDefault();
    if (!searchQuery.trim()) return;
    setIsSearching(true);
    setSearchError(null);
    setHasSearched(true);

    try {
      const res = await api.searchKB(searchQuery.trim(), collectionName);
      setSearchResults(res.results || []);
    } catch (err) {
      setSearchError(err.message || "Vector search query failed.");
      setSearchResults([]);
    } finally {
      setIsSearching(false);
    }
  };

  return (
    <div className="space-y-8 pb-12">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-apple-text">
          Knowledge Base (Gate 2 RAG)
        </h1>
        <p className="text-apple-secondary text-sm mt-1">
          Context Assurance & Provenance: Ingest authoritative ground-truth documents into Qdrant vector store with PostgreSQL Row-Level Security isolation.
        </p>
      </div>

      {/* Vector Store KPI Status Bar */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div className="bg-apple-surface rounded-2xl p-4 border border-apple-border shadow-apple-card flex items-center space-x-3">
          <div className="p-2.5 rounded-xl bg-apple-blue/10 text-apple-blue">
            <Database className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-apple-secondary">Indexed Documents</div>
            <div className="text-xl font-bold text-apple-text mt-0.5">{documents.length}</div>
          </div>
        </div>

        <div className="bg-apple-surface rounded-2xl p-4 border border-apple-border shadow-apple-card flex items-center space-x-3">
          <div className="p-2.5 rounded-xl bg-apple-green/10 text-apple-green">
            <Layers className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-apple-secondary">Vector Chunks in Qdrant</div>
            <div className="text-xl font-bold text-apple-text mt-0.5">
              {documents.reduce((acc, d) => acc + (d.chunks_count || 1), 0)}
            </div>
          </div>
        </div>

        <div className="bg-apple-surface rounded-2xl p-4 border border-apple-border shadow-apple-card flex items-center space-x-3">
          <div className="p-2.5 rounded-xl bg-apple-purple/10 text-apple-purple">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs text-apple-secondary">Poisoning Defense</div>
            <div className="text-xl font-bold text-apple-text mt-0.5">Fail-Closed</div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left Column: Ingest New Document Form */}
        <div className="lg:col-span-5 space-y-4">
          <div className="bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card">
            <div className="flex items-center space-x-2 pb-3 mb-4 border-b border-apple-border">
              <UploadCloud className="w-4 h-4 text-apple-blue" />
              <h3 className="font-semibold text-sm text-apple-text">Ingest Authoritative Document</h3>
            </div>

            <form onSubmit={handleUpload} className="space-y-3">
              <div>
                <label className="block text-xs font-semibold text-apple-text mb-1">
                  Document Filename
                </label>
                <input
                  type="text"
                  value={filename}
                  onChange={(e) => setFilename(e.target.value)}
                  placeholder="e.g. Clinical_Guidelines_2026.md"
                  className="w-full text-xs p-2.5 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-apple-text mb-1">
                  Target Qdrant Collection
                </label>
                <input
                  type="text"
                  value={collectionName}
                  onChange={(e) => setCollectionName(e.target.value)}
                  placeholder="default_kb"
                  className="w-full text-xs p-2.5 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-mono"
                />
              </div>

              <div>
                <label className="block text-xs font-semibold text-apple-text mb-1">
                  Plaintext / Markdown Content
                </label>
                <textarea
                  rows={5}
                  value={content}
                  onChange={(e) => setContent(e.target.value)}
                  placeholder="Paste ground-truth reference policies, documentation, or contracts..."
                  className="w-full text-xs p-2.5 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-mono resize-none"
                />
                {content.trim().length > 0 && (
                  <div className="flex items-center justify-between text-[11px] text-apple-secondary mt-1 px-1 font-mono">
                    <span>
                      Size: {new Blob([content.trim()]).size > 1024 ? `${(new Blob([content.trim()]).size / 1024).toFixed(1)} KB` : `${new Blob([content.trim()]).size} B`}
                    </span>
                    <span>
                      Est. Chunks: ~{Math.max(1, Math.ceil(content.trim().length / 500))} (500 char window)
                    </span>
                  </div>
                )}
              </div>

              {uploadSuccess && (
                <div className="p-3 rounded-xl bg-apple-green/10 border border-apple-green/20 text-xs text-apple-green flex items-center space-x-2">
                  <CheckCircle className="w-4 h-4 shrink-0" />
                  <span>{uploadSuccess}</span>
                </div>
              )}

              {uploadError && (
                <div className="p-3 rounded-xl bg-apple-red/10 border border-apple-red/20 text-xs text-apple-red flex items-center space-x-2">
                  <AlertCircle className="w-4 h-4 shrink-0" />
                  <span>{uploadError}</span>
                </div>
              )}

              <button
                type="submit"
                disabled={isUploading}
                className="w-full py-2.5 rounded-xl bg-apple-blue hover:bg-apple-blueHover text-white text-xs font-semibold shadow-apple-sm transition disabled:opacity-50"
              >
                {isUploading ? "Chunking & Vectorizing in Qdrant..." : "Index Ground-Truth Document"}
              </button>
            </form>
          </div>

          {/* Semantic Search Sandbox */}
          <div className="bg-apple-surface rounded-3xl p-6 border border-apple-border shadow-apple-card space-y-3">
            <div className="flex items-center space-x-2 pb-3 border-b border-apple-border">
              <Search className="w-4 h-4 text-apple-blue" />
              <h3 className="font-semibold text-sm text-apple-text">Vector Search Tester</h3>
            </div>

            <form onSubmit={handleSearch} className="flex space-x-2">
              <input
                type="text"
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                placeholder="Search semantic chunks..."
                className="w-full text-xs p-2 rounded-xl bg-apple-subtle border border-apple-border focus:outline-none focus:border-apple-blue font-sans"
              />
              <button
                type="submit"
                disabled={isSearching}
                className="px-3.5 py-2 bg-apple-text hover:bg-black text-white text-xs font-medium rounded-xl transition"
              >
                Query
              </button>
            </form>

            {searchError && (
              <p className="text-xs text-apple-red px-1 mt-1">{searchError}</p>
            )}

            {hasSearched && !isSearching && searchResults.length === 0 && !searchError && (
              <p className="text-xs text-apple-secondary px-1 mt-2 text-center py-2">
                No matching evidence chunks found in tenant vector space.
              </p>
            )}

            {searchResults.length > 0 && (
              <div className="space-y-2 pt-2">
                {searchResults.map((res, i) => (
                  <div
                    key={i}
                    className="p-3 rounded-xl bg-apple-subtle/50 border border-apple-border text-xs space-y-1"
                  >
                    <div className="flex items-center justify-between text-[10px] font-mono text-apple-secondary">
                      <span>{res.source_doc}</span>
                      <span className="font-bold text-apple-green">
                        {(res.similarity * 100).toFixed(0)}% match
                      </span>
                    </div>
                    <p className="text-apple-text text-[11px] leading-relaxed">
                      "{res.snippet}"
                    </p>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Indexed Documents List */}
        <div className="lg:col-span-7 space-y-3">
          <div className="flex items-center justify-between px-1">
            <span className="text-xs font-semibold text-apple-secondary uppercase tracking-wider">
              Tenant Documents ({documents.length})
            </span>
            <span className="text-xs font-mono text-apple-secondary">RLS Enforced</span>
          </div>

          {documents.length === 0 ? (
            <div className="bg-apple-surface rounded-2xl p-8 border border-apple-border text-center">
              <Database className="w-8 h-8 text-apple-secondary mx-auto mb-2 opacity-60" />
              <h4 className="text-sm font-semibold text-apple-text">No Documents Indexed</h4>
              <p className="text-xs text-apple-secondary mt-1 max-w-sm mx-auto">
                Ingest policies, guides, or specifications on the left to ground your AI agents and prevent Gate 2 context poisoning.
              </p>
            </div>
          ) : (
            <div className="space-y-2.5">
              {documents.map((doc) => (
                <div
                  key={doc.document_id}
                  className="p-4 rounded-2xl bg-apple-surface border border-apple-border shadow-apple-sm flex items-center justify-between hover:shadow-apple-card transition group"
                >
                  <div className="flex items-start space-x-3">
                    <div className="p-2.5 rounded-xl bg-apple-subtle text-apple-secondary group-hover:text-apple-blue group-hover:bg-apple-blue/10 transition">
                      <FileText className="w-4 h-4" />
                    </div>
                    <div>
                      <h4 className="text-xs sm:text-sm font-semibold text-apple-text">
                        {doc.filename}
                      </h4>
                      <div className="flex items-center space-x-2 text-[11px] text-apple-secondary mt-1 font-mono">
                        <span>{doc.chunks_count} chunks</span>
                        <span>•</span>
                        <span>{new Date(doc.upload_timestamp).toLocaleDateString()}</span>
                        <span>•</span>
                        <span className="text-apple-green font-medium">INDEXED</span>
                      </div>
                    </div>
                  </div>

                  <button
                    type="button"
                    onClick={() => handleDelete(doc.document_id)}
                    title="Purge document chunks from Qdrant and PostgreSQL"
                    className="p-2 rounded-xl text-apple-muted hover:text-apple-red hover:bg-apple-red/10 transition"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
