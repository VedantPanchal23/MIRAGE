import React, { useState } from "react";
import { KeyRound, X, AlertCircle } from "lucide-react";

/**
 * Accessible Authentication Dialog allowing operators to provide a JWT access token
 * or 1-click bootstrap an authoritative demonstration session.
 *
 * In-memory token management: Tokens are kept strictly in React state and never
 * written to localStorage (Security & Access §3.2).
 */
export function LoginModal({ isOpen, onClose, onLogin }) {
  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState(null);

  if (!isOpen) return null;

  const handleSubmit = (e) => {
    e.preventDefault();
    setError(null);

    if (!tokenInput.trim()) {
      setError("Please provide a valid JWT access token.");
      return;
    }

    try {
      onLogin(tokenInput.trim());
      setTokenInput("");
      onClose();
    } catch (err) {
      setError(err.message || "Failed to authenticate token.");
    }
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="login-dialog-title"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/80 backdrop-blur-sm"
    >
      <div className="bg-slate-900 border border-slate-800 rounded-xl p-6 w-full max-w-lg shadow-2xl relative">
        <button
          onClick={onClose}
          aria-label="Close authentication dialog"
          className="absolute top-4 right-4 text-slate-400 hover:text-white transition p-1 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
        >
          <X className="w-5 h-5" aria-hidden="true" />
        </button>

        <div className="flex items-center space-x-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-sky-500/10 border border-sky-500/30 flex items-center justify-center text-sky-400">
            <KeyRound className="w-5 h-5" aria-hidden="true" />
          </div>
          <div>
            <h2 id="login-dialog-title" className="text-base font-bold text-white">
              Authenticate Session
            </h2>
            <p className="text-xs text-slate-400">Authoritative Bearer JWT verification</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="jwt-token-input"
              className="block text-xs font-medium text-slate-300 mb-1.5"
            >
              JWT Access Token
            </label>
            <textarea
              id="jwt-token-input"
              rows={3}
              value={tokenInput}
              onChange={(e) => setTokenInput(e.target.value)}
              placeholder="Paste Bearer JWT token..."
              aria-describedby={error ? "login-error-message" : undefined}
              className="w-full bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 text-xs font-mono text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-transparent resize-none"
            />
          </div>

          {error && (
            <div
              id="login-error-message"
              role="alert"
              className="flex items-center space-x-2 text-xs text-rose-400 bg-rose-950/50 border border-rose-900/60 rounded-lg p-2.5"
            >
              <AlertCircle className="w-4 h-4 flex-shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          <div className="text-[11px] text-slate-500 leading-relaxed">
            Tokens are stored in memory only (never localStorage). Backend cryptographic verification
            is enforced on every API request.
          </div>

          <div className="flex justify-end space-x-3 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="px-4 py-2 text-xs font-medium text-slate-400 hover:text-white bg-slate-800/80 hover:bg-slate-800 rounded-lg transition focus:outline-none focus:ring-2 focus:ring-slate-600"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-500 rounded-lg shadow-sm transition focus:outline-none focus:ring-2 focus:ring-sky-400"
            >
              Authenticate
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default LoginModal;
