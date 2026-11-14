/**
 * Integrity checks (Phase 5): hidden text, timeline consistency, LaTeX/Typst source findings and the
 * opt-in GitHub claim check. Wording is neutral: these are things a recruiter may notice or ask about.
 */
import { useEffect, useState } from 'react';
import { getIntegrity, verifyGithub } from '../api/client';

const REASON = {
  invisible: 'invisible text mode', transparent: 'fully transparent', tiny: 'under 4 pt', off_page: 'outside the page',
  low_contrast: 'same colour as the background', covered: 'covered by another element', faint: 'very faint',
};
const SEV = { error: 'red', high: 'red', warning: 'amber', medium: 'amber', info: 'muted', low: 'muted' };
const BAR = { experience: 'var(--accent-primary)', education: 'var(--text-muted)', projects: 'var(--accent-warning, #b7791f)' };

function monthLabel(m) { return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][m % 12]} ${Math.floor(m / 12)}`; }

function Timeline({ t }) {
  const ivs = t.intervals.filter(i => i.start !== null && i.end !== null && i.end >= i.start);
  if (!ivs.length) return <p className="ed-muted">No dated entries found.</p>;
  const lo = Math.min(...ivs.map(i => i.start)), hi = Math.max(...ivs.map(i => i.end)) + 1;
  const pct = m => `${((m - lo) / (hi - lo)) * 100}%`;
  return (
    <div className="ig-tl" role="img" aria-label="Timeline of dated entries">
      {ivs.map(i => (
        <div key={i.entry_id} className="ig-tl-row">
          <span className="ig-tl-label" title={i.raw}>{i.label}</span>
          <span className="ig-tl-track">
            <i style={{ left: pct(i.start), width: `calc(${pct(i.end + 1)} - ${pct(i.start)})`, background: BAR[i.section] || 'var(--text-secondary)' }}
               data-part={i.part_time ? 'y' : 'n'} title={`${monthLabel(i.start)} – ${i.present ? 'present' : monthLabel(i.end)}`} />
          </span>
        </div>
      ))}
      <div className="ig-tl-axis"><span>{Math.floor(lo / 12)}</span><span>{Math.floor((hi - 1) / 12)}</span></div>
    </div>
  );
}

export default function IntegrityPanel({ resumeId, jdId = null }) {
  const [rep, setRep] = useState(null);
  const [err, setErr] = useState(null);
  const [consent, setConsent] = useState(false);
  const [gh, setGh] = useState(null);
  const [ghBusy, setGhBusy] = useState(false);
  const [ghErr, setGhErr] = useState(null);

  useEffect(() => {
    let alive = true;
    getIntegrity(resumeId, jdId).then(r => alive && setRep(r)).catch(e => alive && setErr(e.message));
    return () => { alive = false; };
  }, [resumeId, jdId]);

  async function runGithub() {
    setGhBusy(true); setGhErr(null);
    try { setGh(await verifyGithub(resumeId, { consent: true })); } catch (e) { setGhErr(e.message); } finally { setGhBusy(false); }
  }

  if (err) return <div className="card"><p className="ed-error">{err}</p></div>;
  if (!rep) return <div className="card"><p className="ed-muted">Checking for hidden text and timeline issues…</p></div>;
  const { stealth: s, timeline: t, source: src } = rep;

  return (
    <div className="bento-grid integrity">
      <div className="card span-6">
        <div className="card-header"><span className="card-title">Hidden text</span></div>
        {s ? (
          <>
            <p className={s.spans.some(x => x.severity === 'high') ? 'ig-verdict bad' : 'ig-verdict'}>{s.verdict}</p>
            <ul className="ig-list">
              {s.spans.map((x, k) => (
                <li key={k} data-sev={SEV[x.severity]}>
                  <span className="ig-where">Page {x.page + 1}</span>
                  <span className="ig-what">{x.reasons.map(r => REASON[r] || r).join(', ')}</span>
                  <q>{x.text.slice(0, 140)}</q>
                  {x.jd_terms.length > 0 && <span className="ig-chips">{x.jd_terms.map(j => <b key={j}>{j}</b>)}</span>}
                </li>
              ))}
            </ul>
          </>
        ) : src ? (
          <ul className="ig-list">
            {src.findings.length === 0 && <li className="ed-muted">Nothing hidden or risky found in the source.</li>}
            {src.findings.map((f, k) => (
              <li key={k} data-sev={SEV[f.severity]}>
                <span className="ig-where">Line {f.line}</span><span className="ig-what">{f.message}</span>
                {f.text && <q>{f.text}</q>}
              </li>
            ))}
          </ul>
        ) : <p className="ed-muted">The hidden-text check runs on PDF, LaTeX and Typst uploads.</p>}
      </div>

      <div className="card span-6">
        <div className="card-header"><span className="card-title">Timeline</span>
          <span className="badge badge-neutral">{Math.round(t.experience_months / 12 * 10) / 10} yrs dated experience</span></div>
        <Timeline t={t} />
        <ul className="ig-list">
          {t.findings.length === 0 && <li className="ed-muted">Dates are consistent.</li>}
          {t.findings.map((f, k) => <li key={k} data-sev={SEV[f.severity]}><span className="ig-what">{f.message}</span></li>)}
        </ul>
      </div>

      <div className="card span-12">
        <div className="card-header"><span className="card-title">Project claims vs public GitHub</span>
          {gh?.cvi != null && <span className="badge badge-neutral">CVI {gh.cvi}%</span>}</div>
        {!rep.github_enabled ? (
          <p className="ed-muted">Off. This check calls api.github.com, so it is disabled until you set
            RESUMEIQ_GITHUB_VERIFY_ENABLED=true in .env.</p>
        ) : !gh ? (
          <div className="ig-consent">
            <label className="ed-toggle"><input type="checkbox" checked={consent} onChange={e => setConsent(e.target.checked)} />
              Send my GitHub username and repo names to api.github.com. No resume text is sent.</label>
            <button className="btn btn-primary" disabled={!consent || ghBusy} onClick={runGithub}>{ghBusy ? 'Checking…' : 'Check public repos'}</button>
            {ghErr && <p className="ed-error">{ghErr}</p>}
          </div>
        ) : (
          <>
            <p className="ed-muted">{gh.message} "Not found" means not visible in that public repo, not that the claim is false.</p>
            <ul className="ig-list">
              {gh.projects.map(p => (
                <li key={p.entry_id}>
                  <span className="ig-where">{p.title}</span>
                  <span className="ig-what">{p.repo ? <a href={`https://github.com/${p.repo}`} target="_blank" rel="noreferrer">{p.repo}</a> : 'no matching repo'}</span>
                  <span className="ig-chips">
                    {p.found.map(x => <b key={x} data-ok="y">{x}</b>)}
                    {p.not_found.map(x => <b key={x} data-ok="n">{x}</b>)}
                  </span>
                  {p.notes.map((n, k) => <small key={k}>{n}</small>)}
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
