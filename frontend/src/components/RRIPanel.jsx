import { useMemo, useState } from 'react';
import { GRADE_COLOR } from '../lib/diff';

/**
 * Recruiter Readability Index (ATS 2.0).
 * Shows what a recruiter takes in during a first skim vs. what the full resume
 * actually supports, a per-dimension breakdown and A–D grades for every bullet.
 */
const ROLE_LABEL = {
  role_ml_engineer: 'ML / AI Engineer', role_data_engineer: 'Data Engineer', role_software_engineer: 'Software Engineer',
};

function Bar({ value, max }) {
  const pct = max ? Math.round((value / max) * 100) : 0;
  const color = pct >= 75 ? 'var(--accent-success)' : pct >= 50 ? 'var(--accent-warning)' : 'var(--accent-danger)';
  return (
    <div className="progress-bar">
      <div className="fill" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}aa, ${color})` }} />
    </div>
  );
}

export default function RRIPanel({ readability, onLocate }) {
  const [gradeFilter, setGradeFilter] = useState('C+D');
  const r = readability || {};
  const snap = r.snapshot;
  const statements = r.statements || [];

  const dist = useMemo(() => {
    const d = { A: 0, B: 0, C: 0, D: 0 };
    statements.forEach(s => { if (d[s.grade] !== undefined) d[s.grade] += 1; });
    return d;
  }, [statements]);

  const shownStatements = useMemo(() => {
    if (gradeFilter === 'all') return statements;
    if (gradeFilter === 'C+D') return statements.filter(s => s.grade === 'C' || s.grade === 'D');
    return statements.filter(s => s.grade === gradeFilter);
  }, [statements, gradeFilter]);

  if (!readability) return null;
  const total = statements.length || 1;
  const role = r.inferred_role || ROLE_LABEL[r.role_norm_id] || r.role_norm_id;

  const locateStatement = (s) => onLocate && onLocate({
    id: `stmt-${s.id}`, statement_ids: [s.id], line_ids: s.line_ids || [],
  });

  return (
    <div className="bento-grid">
      {/* ── Dimensions ───────────────────────────── */}
      <div className="card span-6">
        <div className="card-header">
          <span className="card-title">Readability (ATS 2.0) — Recruiter Readability Index</span>
          <span className="badge badge-neutral">v{r.rubric_version}</span>
        </div>
        <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.875rem', fontSize: '0.75rem' }}>
          {role && <span className="badge badge-info">Read as: {role}</span>}
          <span className="badge badge-neutral">Confidence: {r.confidence}</span>
          <span className="badge badge-neutral">{r.llm_used ? 'Rules + local LLM labels' : 'Deterministic rules'}</span>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
          {(r.dimensions || []).map(d => (
            <div key={d.dimension}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem', fontSize: '0.8125rem' }}>
                <span style={{ color: 'var(--text-secondary)' }}>{d.dimension}</span>
                <span style={{ fontWeight: 700, color: 'var(--text-heading)' }}>
                  {Number(d.score).toFixed(1)}/{d.max_score}
                </span>
              </div>
              <Bar value={d.score} max={d.max_score} />
              {d.details?.[0] && (
                <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: 3 }}>{d.details[0]}</div>
              )}
            </div>
          ))}
        </div>
        <p style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: '1rem', lineHeight: 1.5 }}>{r.disclosure}</p>
      </div>

      {/* ── 6-second snapshot ───────────────────── */}
      <div className="card span-6">
        <div className="card-header">
          <span className="card-title">6-second snapshot</span>
          {snap && <span className="badge badge-neutral">{Math.round((snap.agreement || 0) * 100)}% agreement</span>}
        </div>
        {snap ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.875rem', fontSize: '0.8125rem' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
              <div style={{ padding: '0.625rem', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: 4 }}>A SKIMMER CONCLUDES</div>
                <div style={{ color: 'var(--text-heading)', fontWeight: 600 }}>{snap.skim_role || 'Unclear role'}</div>
                <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{snap.seniority} level</div>
                <ul style={{ margin: '0.375rem 0 0', paddingLeft: '1rem', color: 'var(--text-secondary)' }}>
                  {(snap.skim_strengths || []).map(s => <li key={s}>{s}</li>)}
                  {!snap.skim_strengths?.length && <li style={{ listStyle: 'none', marginLeft: '-1rem' }}>No clear strengths visible</li>}
                </ul>
              </div>
              <div style={{ padding: '0.625rem', borderRadius: 8, border: '1px solid var(--border-subtle)' }}>
                <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', fontWeight: 700, marginBottom: 4 }}>FULL RESUME SUPPORTS</div>
                <div style={{ color: 'var(--text-heading)', fontWeight: 600 }}>{snap.full_role || '—'}</div>
                <ul style={{ margin: '0.375rem 0 0', paddingLeft: '1rem', color: 'var(--text-secondary)' }}>
                  {(snap.full_strengths || []).map(s => <li key={s}>{s}</li>)}
                </ul>
              </div>
            </div>
            {snap.missed_strengths?.length > 0 && (
              <div style={{ background: 'rgba(251,191,36,0.08)', border: '1px solid rgba(251,191,36,0.3)', borderRadius: 8, padding: '0.625rem' }}>
                <div style={{ fontSize: '0.6875rem', color: '#b7791f', fontWeight: 700, marginBottom: 4 }}>
                  STRONG EVIDENCE A SKIMMER MISSES
                </div>
                <ul style={{ margin: 0, paddingLeft: '1rem', color: 'var(--text-secondary)' }}>
                  {snap.missed_strengths.map(s => <li key={s}>{s}</li>)}
                </ul>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: 6 }}>
                  Move these into the top third of page 1 or the first words of a bullet.
                </div>
              </div>
            )}
            {onLocate && snap.skim_line_ids?.length > 0 && (
              <button className="btn btn-secondary" style={{ alignSelf: 'flex-start', padding: '0.3rem 0.75rem', fontSize: '0.75rem' }}
                onClick={() => onLocate({ id: 'skim', line_ids: snap.skim_line_ids, statement_ids: [] })}>
                Highlight what a skimmer sees
              </button>
            )}
          </div>
        ) : (
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>Snapshot unavailable for this analysis.</p>
        )}
      </div>

      {/* ── Bullet grades ───────────────────────── */}
      <div className="card span-12">
        <div className="card-header">
          <span className="card-title">Bullet grades (action · specific · outcome · metric)</span>
          <div style={{ display: 'flex', gap: '0.25rem' }}>
            {['C+D', 'A', 'B', 'C', 'D', 'all'].map(g => (
              <button key={g} onClick={() => setGradeFilter(g)}
                className={`btn ${gradeFilter === g ? 'btn-primary' : 'btn-secondary'}`}
                style={{ padding: '0.25rem 0.6rem', fontSize: '0.7rem' }}>
                {g === 'all' ? 'All' : g === 'C+D' ? 'Needs work' : `${g} (${dist[g]})`}
              </button>
            ))}
          </div>
        </div>

        <div style={{ display: 'flex', height: 10, borderRadius: 6, overflow: 'hidden', marginBottom: '0.875rem' }}>
          {['A', 'B', 'C', 'D'].map(g => dist[g] > 0 && (
            <div key={g} title={`${g}: ${dist[g]}`} style={{ width: `${(dist[g] / total) * 100}%`, background: GRADE_COLOR[g] }} />
          ))}
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem', maxHeight: 420, overflowY: 'auto' }}>
          {shownStatements.map(s => (
            <div key={s.id} onClick={() => locateStatement(s)}
              style={{ display: 'flex', gap: '0.75rem', alignItems: 'flex-start', padding: '0.5rem 0.625rem', borderRadius: 8,
                border: '1px solid var(--border-subtle)', cursor: onLocate ? 'pointer' : 'default' }}>
              <span style={{ fontWeight: 800, color: GRADE_COLOR[s.grade], minWidth: 18, fontSize: '0.9375rem' }}>{s.grade}</span>
              <div style={{ flex: 1, fontSize: '0.8125rem' }}>
                <div style={{ color: 'var(--text-heading)', lineHeight: 1.45 }}>{s.text}</div>
                <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: 2 }}>
                  {s.section}{s.entry ? ` · ${s.entry}` : ''}
                  {s.missing?.length > 0 && <> · <span style={{ color: '#b7791f' }}>missing: {s.missing.join(', ')}</span></>}
                </div>
                {s.reasons?.length > 0 && s.grade !== 'A' && (
                  <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)', marginTop: 2 }}>{s.reasons.join(' · ')}</div>
                )}
              </div>
              {onLocate && <span style={{ fontSize: '0.75rem', color: 'var(--accent-primary-light)' }}>Edit</span>}
            </div>
          ))}
          {shownStatements.length === 0 && (
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>No bullets with this grade.</p>
          )}
        </div>
      </div>
    </div>
  );
}
