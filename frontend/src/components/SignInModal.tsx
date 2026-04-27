import { useState } from "react";
import { register, login } from "../api/auth";

interface SignInModalProps {
  open: boolean;
  onClose: () => void;
  onAuthSuccess: () => void;
}

type Mode = "login" | "register";

const DEMO_EMAIL = "demo@road-quality-mvp.dev"; // 04-CONTEXT.md D-05
const DEMO_PASSWORD = "demo1234";                // 04-CONTEXT.md D-05 (rotatable)

export default function SignInModal({ open, onClose, onAuthSuccess }: SignInModalProps) {
  const [mode, setMode] = useState<Mode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      if (mode === "register") {
        await register(email, password);
      } else {
        await login(email, password);
      }
      onAuthSuccess();
      onClose();
    } catch (err: any) {
      setError(err.message || "Authentication failed");
    } finally {
      setLoading(false);
    }
  };

  const handleDemo = async () => {
    setEmail(DEMO_EMAIL);
    setPassword(DEMO_PASSWORD);
    setLoading(true);
    setError(null);
    try {
      await login(DEMO_EMAIL, DEMO_PASSWORD);
      onAuthSuccess();
      onClose();
    } catch (err: any) {
      setError(err.message || "Demo login failed");
    } finally {
      setLoading(false);
    }
  };

  // Backdrop click closes the modal; clicking inside the dialog does not.
  // RESEARCH §6 line 1015-1019 + PATTERNS lines 401-411 (z-[2000] above
  // MapView's z-[1000] and AddressInput's z-50).
  return (
    <div
      className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/50"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl p-6 w-96 max-w-full mx-4"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-bold mb-4">
          {mode === "login" ? "Sign in" : "Create account"}
        </h2>

        <form onSubmit={handleSubmit} className="space-y-3">
          <input
            type="email"
            placeholder="Email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          <input
            type="password"
            placeholder="Password (min 8 chars)"
            required
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full border rounded px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-400"
          />
          {error && <p className="text-red-600 text-sm">{error}</p>}
          <button
            type="submit"
            disabled={loading}
            className="w-full bg-blue-600 text-white rounded py-2 hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "..." : mode === "login" ? "Sign in" : "Create account"}
          </button>
        </form>

        <button
          onClick={handleDemo}
          disabled={loading}
          className="w-full mt-3 bg-gray-100 text-gray-700 rounded py-2 hover:bg-gray-200 disabled:opacity-50"
        >
          Try as demo
        </button>

        <p className="text-sm text-center mt-4">
          {mode === "login" ? (
            <>
              No account?{" "}
              <button
                onClick={() => {
                  setMode("register");
                  setError(null);
                }}
                className="text-blue-600 hover:underline"
              >
                Create one
              </button>
            </>
          ) : (
            <>
              Have an account?{" "}
              <button
                onClick={() => {
                  setMode("login");
                  setError(null);
                }}
                className="text-blue-600 hover:underline"
              >
                Sign in
              </button>
            </>
          )}
        </p>
      </div>
    </div>
  );
}
