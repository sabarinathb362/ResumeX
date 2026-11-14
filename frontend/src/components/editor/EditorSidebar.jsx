/**
 * Sidebar tabs for the editor.
 *   Live fixes  — the selected bullet: rules fixes instantly, AI rewrites streaming in (ResumeEditor renders it)
 *   JD gaps     — every JD requirement with its verdict, anchored to the bullet that evidences it
 *   Strategy    — general recommendations and gap-closing projects
 */
import { useState } from 'react';
import { SEVERITY_COLOR } from '../../lib/diff';

const HAS_BLANK = /\[[^\]]*\]/;
const VERDICT = {
  missing: { label: 'Missing', color: '#b42318' },
  partial: { label: 'Partial', color: '#b7791f' },
  transferable: { label: 'Transferable', color: '#2f6690' },
  met: { label: 'Met', color: '#3d7a3a' },
};

export function SidebarTabs({ tab, onTab, counts, hasJD }) {
  const tabs = [
    { id: 'fix', label: 'Live fixes', n: counts.fix },
    ...(hasJD ? [{ id: 'jd', label: 'JD gaps', n: counts.jd }] : []),
    { id: 'strategy', label: 'Strategy', n: counts.strategy },
  ];
  return (
    <div className="ed-tabs" role="tablist" aria-label="Sidebar">
      {tabs.map(t => (
        <button key={t.id} role="tab" aria-selected={tab === t.id} className={tab === t.id ? 'is-on' : ''} onClick={() => onTab(t.id)}>
          {t.label}{t.n ? <span className="ed-tab-n">{t.n}</span> : null}
        </button>
      ))}
    </div>
  );
}

function shortReq(text) {
  return text.length > 60 ? `${text.slice(0, 57).replace(/\s+\S*$/, '')}…` : text;
}

function AddBulletForm({ requirement, entries, onAdd, onCancel }) {
  const [entryId, setEntryId] = useState(entries[0]?.id || '');
  const [text, setText] = useState(`[What you did] with ${shortReq(requirement)} [where — which project or role], [result — a number if you have one].`);
  const blank = HAS_BLANK.test(text);
  return (
    <div className="ed-draft">
      <label htmlFor="ed-add-entry">Add to</label>
      <select id="ed-add-entry" value={entryId} onChange={e => setEntryId(e.target.value)}>
        {entries.map(e => <option key={e.id} value={e.id}>{e.section} › {e.title || 'Untitled'}</option>)}
      </select>
      <textarea rows={3} value={text} onChange={e => setText(e.target.value)} aria-label="New bullet" />
      {blank && <p className="ed-warn">Replace every [bracketed] part with what you actually did. Only add this if it is true.</p>}
      <div className="ed-row">
        <button className="btn btn-primary btn-sm" disabled={blank || !entryId || !text.trim()} onClick={() => onAdd(entryId, text.trim())}>Add bullet</button>
        <button className="ed-link" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

export function JDGapsTab({ data, error, entries, onLocate, onAlign, onAddBullet, onFindProjects }) {
  const [adding, setAdding] = useState(null);
  if (error) return <p className="ed-error" role="alert">{error}</p>;
  if (!data) return <p className="ed-muted">Loading requirements…</p>;
  return (
    <>
      <div className="ed-jd-head">
        <strong>{Math.round(data.ai_match_percentage)}%</strong> of requirements evidenced
        <span className="ed-muted"> · {data.met} met · {data.partial} partial · {data.missing} missing</span>
      </div>
      {data.requirements.map((r, i) => {
        const v = VERDICT[r.verdict] || VERDICT.missing;
        const anchored = r.statement_ids?.length > 0;
        return (
          <div key={i} className="ed-finding" style={{ borderLeftColor: v.color }}>
            <div className="ed-row">
              <span className="ed-verdict" style={{ color: v.color }}>{v.label}</span>
              <span className="ed-muted">{r.requirement_type}</span>
            </div>
            <div className="ed-finding-title">{r.requirement_text}</div>
            {r.rationale && <p className="ed-muted">{r.rationale}</p>}
            <div className="ed-row ed-actions">
              {anchored && <button className="ed-link" onClick={() => onLocate(r.statement_ids, r.line_ids)}>Show evidence</button>}
              {anchored && r.verdict !== 'met' && (
                <button className="btn btn-secondary btn-sm" onClick={() => onAlign(r.statement_ids[0], r.requirement_text)}>Rewrite toward this</button>
              )}
              {!anchored && r.verdict !== 'met' && adding !== i && (
                <>
                  <button className="btn btn-secondary btn-sm" onClick={() => setAdding(i)}>I have this — add a bullet</button>
                  <button className="ed-link" onClick={() => onFindProjects(r.requirement_text)}>Suggest a project</button>
                </>
              )}
            </div>
            {adding === i && (
              <AddBulletForm requirement={r.requirement_text} entries={entries}
                onAdd={(entryId, text) => { onAddBullet(entryId, text); setAdding(null); }}
                onCancel={() => setAdding(null)} />
            )}
          </div>
        );
      })}
    </>
  );
}

export function StrategyTab({ items, error, projects, onLocate }) {
  if (error) return <p className="ed-error" role="alert">{error}</p>;
  if (!items) return <p className="ed-muted">Loading recommendations…</p>;
  return (
    <>
      {items.length === 0 && <p className="ed-muted">No strategy items for this resume.</p>}
      {items.map(r => (
        <div key={r.id} className="ed-finding" style={{ borderLeftColor: SEVERITY_COLOR[r.severity] || SEVERITY_COLOR.info }}>
          <div className="ed-finding-title">{r.title}</div>
          <p className="ed-muted">{r.why}</p>
          {r.how && <p className="ed-fix">{r.how}</p>}
          {r.statement_ids?.length > 0 && <button className="ed-link" onClick={() => onLocate(r.statement_ids, r.line_ids)}>Show on page</button>}
        </div>
      ))}
      {projects?.projects?.length > 0 && (
        <>
          <h4 className="ed-side-h">Projects that would close your gaps</h4>
          {projects.projects.map(p => (
            <div key={p.id} className="ed-card">
              <div className="ed-row"><strong>{p.title}</strong><span className="ed-muted">{p.difficulty}</span></div>
              <p className="ed-muted">{p.why_recommended}</p>
              <p className="ed-muted">Stack: {p.suggested_stack.join(', ')}</p>
              <p className="ed-text">{p.resume_bullet_template}</p>
            </div>
          ))}
        </>
      )}
    </>
  );
}
