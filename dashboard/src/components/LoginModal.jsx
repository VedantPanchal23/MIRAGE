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
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/40 backdrop-blur-xs"
    >
      <div className="bg-white border border-slate-200 rounded-xl p-6 w-full max-w-lg shadow-xl relative">
        <button
          onClick={onClose}
          aria-label="Close authentication dialog"
          className="absolute top-4 right-4 text-slate-400 hover:text-slate-700 transition p-1 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500"
        >
          <X className="w-5 h-5" aria-hidden="true" />
        </button>

        <div className="flex items-center space-x-3 mb-4">
          <div className="w-10 h-10 rounded-lg bg-sky-50 border border-sky-200 flex items-center justify-center text-sky-600">
            <KeyRound className="w-5 h-5" aria-hidden="true" />
          </div>
          <div>
            <h2 id="login-dialog-title" className="text-base font-bold text-slate-900">
              Authenticate Session
            </h2>
            <p className="text-xs text-slate-500">Authoritative Bearer JWT verification</p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label
              htmlFor="jwt-token-input"
              className="block text-xs font-medium text-slate-700 mb-1.5"
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
              className="w-full bg-white border border-slate-300 rounded-lg px-3 py-2 text-xs font-mono text-slate-900 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-sky-500/20 focus:border-sky-500 resize-none"
            />
          </div>

          {error && (
            <div
              id="login-error-message"
              role="alert"
              className="flex items-center space-x-2 text-xs text-rose-800 bg-rose-50 border border-rose-200 rounded-lg p-2.5"
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
              className="px-4 py-2 text-xs font-medium text-slate-700 hover:bg-slate-100 bg-white border border-slate-200 rounded-lg transition focus:outline-none focus:ring-2 focus:ring-slate-400 shadow-xs"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="px-4 py-2 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-700 rounded-lg shadow-xs transition focus:outline-none focus:ring-2 focus:ring-sky-400"
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
