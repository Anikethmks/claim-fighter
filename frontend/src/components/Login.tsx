import { useState } from "react";
import { api, type Me } from "../api";

/** Email one-time-code sign-in. */
export default function Login({ onSignedIn, title = "Sign in to continue" }: {
  onSignedIn: (me: Me) => void; title?: string;
}) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card login">
      <h2>{title}</h2>
      {!sent ? (
        <form onSubmit={(e) => { e.preventDefault(); run(async () => { await api.requestCode(email); setSent(true); }); }}>
          <p className="muted">We'll email you a 6-digit code. No password needed; your cases stay private to your account.</p>
          <label className="field"><span>Email</span>
            <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
          </label>
          {error && <div className="alert alert-error" role="alert">{error}</div>}
          <button className="btn btn-primary" disabled={busy || !email}>{busy ? "Sending…" : "Email me a code"}</button>
        </form>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); run(async () => onSignedIn(await api.verifyCode(email, code))); }}>
          <p className="muted">Enter the code sent to <strong>{email}</strong>. It expires in 10 minutes.</p>
          <label className="field"><span>Code</span>
            <input inputMode="numeric" autoComplete="one-time-code" maxLength={6} required value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} />
          </label>
          {error && <div className="alert alert-error" role="alert">{error}</div>}
          <div className="row">
            <button className="btn btn-primary" disabled={busy || code.length !== 6}>{busy ? "Checking…" : "Sign in"}</button>
            <button type="button" className="btn-link" onClick={() => { setSent(false); setCode(""); }}>Use a different email</button>
          </div>
        </form>
      )}
    </section>
  );
}
