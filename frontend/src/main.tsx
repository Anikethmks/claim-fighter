import { StrictMode, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { api, type Me } from "./api";
import Home from "./components/Home";
import CasePage from "./components/CasePage";
import Login from "./components/Login";
import Privacy from "./components/Privacy";
import Admin from "./components/Admin";
import "./styles.css";

// Hash routing keeps deep links working when the backend serves the built files.
function useRoute() {
  const [hash, setHash] = useState(window.location.hash);
  useEffect(() => {
    const onChange = () => {
      setHash(window.location.hash);
      window.scrollTo(0, 0);
    };
    window.addEventListener("hashchange", onChange);
    return () => window.removeEventListener("hashchange", onChange);
  }, []);
  return hash;
}

function useDemoFlag() {
  const [demo, setDemo] = useState(false);
  useEffect(() => {
    fetch("/api/health")
      .then((r) => r.json())
      .then((h) => setDemo(!!h.demo))
      .catch(() => {});
  }, []);
  return demo;
}

function App() {
  const hash = useRoute();
  const demo = useDemoFlag();
  // undefined = still checking, null = signed out
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    api.me().then(setMe).catch(() => setMe(null));
  }, []);

  async function signOut() {
    await api.logout().catch(() => {});
    setMe(null);
    window.location.hash = "#/";
  }

  const caseMatch = hash.match(/^#\/case\/([\w-]+)/);
  let page;
  if (hash === "#/privacy") page = <Privacy />;
  else if (me === undefined) page = <section className="card"><div className="spinner" /></section>;
  else if (caseMatch) page = me ? <CasePage id={caseMatch[1]} /> : <Login onSignedIn={setMe} title="Sign in to see this case" />;
  else if (hash === "#/admin") page = me?.admin ? <Admin /> : <section className="card">Admins only.</section>;
  else page = <Home me={me} onSignedIn={setMe} />;

  return (
    <>
      {demo && (
        <div className="demo-banner" role="status">
          DEMO MODE: results are a fixed sample case, not an analysis of your documents.
        </div>
      )}
      <header className="topbar">
        <a href="#/" className="brand">
          <svg className="brand-mark" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor"
            strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden>
            <path d="M12 3v18M7 21h10M5 7h14M5 7l-3 6a3 3 0 0 0 6 0L5 7zM19 7l-3 6a3 3 0 0 0 6 0l-3-6z" />
          </svg>
          ClaimFighter
        </a>
        {me ? (
          <span className="topbar-user">
            {me.admin && <a href="#/admin">Dashboard</a>}
            <span className="topbar-note">{me.email}</span>
            <button className="btn-link" onClick={signOut}>Sign out</button>
          </span>
        ) : (
          <span className="topbar-note">Health insurance claim help · India</span>
        )}
      </header>
      <main className="container">{page}</main>
      <footer className="footer">
        ClaimFighter gives information and drafting help, not legal advice. Always check the cited sources
        before relying on them. Your documents are deleted automatically after 30 days, or immediately when you delete
        the case. <a href="#/privacy">Privacy</a>
      </footer>
    </>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
