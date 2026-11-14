/**
 * Optional account: a sign-in / sign-up page and the list of past analyses.
 * Nothing in ResumeX needs an account; signing in only keeps a history of analysed resumes.
 */
import { useEffect, useState } from 'react';
import { signIn, signUp, getHistory, deleteHistory } from '../api/client';

export function AuthPage({ onSignedIn, onSkip }) {
  const [mode, setMode] = useState('login');      // login | signup
  const [form, setForm] = useState({ name: '', email: '', password: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const set = k => e => setForm(f => ({ ...f, [k]: e.target.value }));

  async function submit(e) {
    e.preventDefault();
    setError(null); setBusy(true);
    try {
      const user = mode === 'login'
        ? await signIn(form.email, form.password)
        : await signUp(form.email, form.password, form.name);
      onSignedIn(user);
    } catch (err) {
      setError(err.message);
    } finally { setBusy(false); }
  }

  return (
    <div className="container page">
      <div className="auth-wrap">
        <header className="stage-head">
          <span className="eyebrow">Account · optional</span>
          <h1>{mode === 'login' ? 'Sign in' : 'Create an account'}</h1>
          <p className="lead">You can analyse resumes without an account. Signing in keeps a history of your analyses so you can reopen them later.</p>
        </header>
        <form className="card auth-card" onSubmit={submit}>
          <div className="auth-tabs" role="tablist">
            <button type="button" role="tab" aria-selected={mode === 'login'} onClick={() => { setMode('login'); setError(null); }}>Sign in</button>
            <button type="button" role="tab" aria-selected={mode === 'signup'} onClick={() => { setMode('signup'); setError(null); }}>Sign up</button>
          </div>
          {mode === 'signup' && (
            <label className="auth-field"><span className="field-label">Name <small>optional</small></span>
              <input className="input" value={form.name} onChange={set('name')} autoComplete="name" />
            </label>
          )}
          <label className="auth-field"><span className="field-label">Email</span>
            <input className="input" type="email" required value={form.email} onChange={set('email')} autoComplete="email" />
          </label>
          <label className="auth-field"><span className="field-label">Password</span>
            <input className="input" type="password" required minLength={mode === 'signup' ? 8 : undefined}
                   value={form.password} onChange={set('password')}
                   autoComplete={mode === 'login' ? 'current-password' : 'new-password'} />
            {mode === 'signup' && <small className="ed-muted">At least 8 characters.</small>}
          </label>
          {error && <p className="ed-error" role="alert">{error}</p>}
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? 'Please wait…' : mode === 'login' ? 'Sign in' : 'Create account'}
          </button>
          <button type="button" className="btn btn-ghost" onClick={onSkip}>Continue without an account</button>
        </form>
      </div>
    </div>
  );
}

const fmtScore = v => (v == null ? '—' : Math.round(v));
const fmtDate = s => {
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
};

export function HistoryPage({ user, onOpen, onNew }) {
  const [items, setItems] = useState(null);
  const [error, setError] = useState(null);
  const [opening, setOpening] = useState(null);

  useEffect(() => {
    getHistory().then(r => setItems(r.items || [])).catch(e => setError(e.message));
  }, []);

  async function open(item) {
    setOpening(item.id); setError(null);
    try { await onOpen(item); } catch (e) { setError(e.message); setOpening(null); }
  }
  async function remove(item) {
    if (!window.confirm(`Remove ${item.filename} from your history?`)) return;
    try { await deleteHistory(item.id); setItems(xs => xs.filter(x => x.id !== item.id)); } catch (e) { setError(e.message); }
  }

  return (
    <div className="container page">
      <header className="stage-head">
        <span className="eyebrow">{user.name || user.email}</span>
        <h1>Your analysed resumes</h1>
        <p className="lead">Reopen any past analysis: the report, the editor and the mock interview work as before.</p>
      </header>
      {error && <p className="ed-error" role="alert">{error}</p>}
      {items === null && !error && <p className="ed-muted">Loading…</p>}
      {items?.length === 0 && (
        <div className="card"><p>No analyses yet. Analyse a resume while signed in and it will appear here.</p>
          <button className="btn btn-primary" onClick={onNew}>Analyse a resume</button></div>
      )}
      {items?.length > 0 && (
        <ul className="history-list">
          {items.map(it => (
            <li key={it.id} className="card history-item">
              <div className="history-main">
                <strong>{it.name || it.filename}</strong>
                <span className="ed-muted">{it.filename}{it.role ? ` · ${it.role}` : ''}{it.company ? ` at ${it.company}` : ''} · {fmtDate(it.created_at)}</span>
              </div>
              <dl className="history-scores">
                <div><dt>ATS</dt><dd>{fmtScore(it.ats_score)}</dd></div>
                <div><dt>Readability</dt><dd>{fmtScore(it.readability_score)}</dd></div>
                <div><dt>Job match</dt><dd>{fmtScore(it.match_score)}</dd></div>
              </dl>
              <div className="history-actions">
                <button className="btn btn-primary btn-sm" disabled={!!opening} onClick={() => open(it)}>
                  {opening === it.id ? 'Opening…' : 'Open'}
                </button>
                <button className="btn btn-ghost btn-sm" onClick={() => remove(it)}>Remove</button>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
