import { useMemo, useState } from 'react';
import { SEVERITY_COLOR, SEVERITY_RANK } from '../lib/diff';

/**
 * Unified, evidence-anchored findings (ATS + Readability + quality checks).
 * Every item is specific to this resume, says why it matters, what to do,
 * and can jump straight to the exact lines in the editor.
 */
const TABS = [
  { id: 'top', label: 'Fix first' },
  { id: 'all', label: 'All' },
  { id: 'rri', label: 'Readability' },
  { id: 'ats', label: 'ATS' },
];

const SOURCE_LABEL = { rri: 'Readability', ats: 'ATS', quality: 'Quality', contact: 'Contact' };
const ACTION_LABEL = {
  rewrite: 'Rewrite', edit: 'Edit', reorder: 'Reorder', remove: 'Remove', add: 'Add', format: 'Format',
};

export default function InsightsPanel({ insights = [], onLocate }) {
  const [tab, setTab] = useState('top');
  const [open, setOpen] = useState(null);

  const sorted = useMemo(
    () => [...insights].sort((a, b) =>
      (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) || (b.points || 0) - (a.points || 0)),
    [insights],
  );

  const shown = useMemo(() => {
    if (tab === 'top') return sorted.filter(f => f.severity !== 'info').slice(0, 5);
    if (tab === 'rri') return sorted.filter(f => f.source === 'rri');
    if (tab === 'ats') return sorted.filter(f => f.source === 'ats' || f.source === 'contact' || f.source === 'quality');
    return sorted;
  }, [sorted, tab]);

  const counts = useMemo(() => {
    const c = { critical: 0, high: 0, medium: 0, low: 0 };
    insights.forEach(f => { if (c[f.severity] !== undefined) c[f.severity] += 1; });
    return c;
  }, [insights]);

  if (!insights.length) {
    return (
      <div>
        <div className="card-header"><span className="card-title">Priority Fixes</span></div>
        <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
          No findings were stored for this analysis. Re-run the analysis to generate evidence-linked insights.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div className="card-header">
        <span className="card-title">Priority Fixes</span>
        <div style={{ display: 'flex', gap: '0.375rem' }}>
          {['critical', 'high', 'medium'].map(s => counts[s] > 0 && (
            <span key={s} className="badge" style={{ background: `${SEVERITY_COLOR[s]}22`, color: SEVERITY_COLOR[s] }}>
              {counts[s]} {s}
            </span>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', gap: '0.25rem', marginBottom: '0.875rem', flexWrap: 'wrap' }}>
        {TABS.map(t => (
          <button key={t.id} onClick={() => setTab(t.id)}
            className={`btn ${tab === t.id ? 'btn-primary' : 'btn-secondary'}`}
            style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem' }}>
            {t.label}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', maxHeight: 560, overflowY: 'auto', paddingRight: 4 }}>
        {shown.length === 0 && (
          <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>Nothing in this category.</p>
        )}
        {shown.map((f, i) => {
          const color = SEVERITY_COLOR[f.severity] || SEVERITY_COLOR.medium;
          const isOpen = open === f.id || (open === null && tab === 'top' && i === 0);
          const canLocate = (f.line_ids?.length || f.statement_ids?.length) && onLocate;
          return (
            <div key={f.id} style={{
              borderLeft: `3px solid ${color}`, borderRadius: 10, background: 'var(--bg-elevated, rgba(31,36,24,0.03))',
              border: '1px solid var(--border-subtle)', borderLeftWidth: 3, borderLeftColor: color, padding: '0.75rem 0.875rem',
            }}>
              <div onClick={() => setOpen(isOpen ? '' : f.id)}
                style={{ display: 'flex', gap: '0.625rem', alignItems: 'flex-start', cursor: 'pointer' }}>
                <span style={{ fontSize: '0.625rem', fontWeight: 700, textTransform: 'uppercase', color, minWidth: 54, marginTop: 3 }}>
                  {f.severity}
                </span>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '0.875rem', fontWeight: 600, color: 'var(--text-heading)', lineHeight: 1.4 }}>{f.title}</div>
                  <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginTop: 2 }}>
                    {SOURCE_LABEL[f.source] || f.source}{f.dimension ? ` · ${f.dimension}` : ''}
                    {f.action ? ` · ${ACTION_LABEL[f.action] || f.action}` : ''}
                  </div>
                </div>
                {f.points > 0 && (
                  <span className="badge badge-success" title={`Estimated ${f.source === 'rri' ? 'RRI' : 'ATS'} points recoverable by this fix (computed from the rubric, not guessed)`}>
                    +{Number(f.points).toFixed(f.points < 1 ? 1 : 0)} {f.source === 'rri' ? 'RRI' : 'ATS'}
                  </span>
                )}
                <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>{isOpen ? '▴' : '▾'}</span>
              </div>

              {isOpen && (
                <div style={{ marginTop: '0.625rem', paddingLeft: 64, display: 'flex', flexDirection: 'column', gap: '0.5rem', fontSize: '0.8125rem' }}>
                  {f.detail && <p style={{ color: 'var(--text-secondary)', lineHeight: 1.55, margin: 0 }}>{f.detail}</p>}
                  {f.fix && (
                    <p style={{ margin: 0, lineHeight: 1.55 }}>
                      <strong style={{ color: 'var(--text-heading)' }}>Do this: </strong>
                      <span style={{ color: 'var(--text-secondary)' }}>{f.fix}</span>
                    </p>
                  )}
                  {f.suggestion && (
                    <div style={{ background: 'rgba(52,211,153,0.08)', border: '1px solid rgba(52,211,153,0.25)', borderRadius: 8, padding: '0.5rem 0.625rem' }}>
                      <div style={{ fontSize: '0.6875rem', color: '#3d7a3a', fontWeight: 700, marginBottom: 2 }}>
                        SUGGESTED (built only from facts already in your resume)
                      </div>
                      <div style={{ color: 'var(--text-heading)', lineHeight: 1.5 }}>{f.suggestion}</div>
                    </div>
                  )}
                  {f.norm_ref && (
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                      Role norm: <code>{f.norm_ref}</code>
                    </div>
                  )}
                  {canLocate ? (
                    <div>
                      <button className="btn btn-secondary" style={{ padding: '0.3rem 0.75rem', fontSize: '0.75rem' }}
                        onClick={() => onLocate(f)}>
                        Show in resume
                      </button>
                    </div>
                  ) : null}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
