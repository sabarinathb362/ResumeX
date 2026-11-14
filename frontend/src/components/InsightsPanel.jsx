/**
 * Fixes: every finding from the ATS rules, the readability review and the contact checks, in one
 * list ordered by what it is worth. Each row says what is wrong in this resume and what to do about
 * it without needing to be opened; opening it adds the reasoning, a grounded suggestion when one can
 * be built, and a jump to the exact lines in the editor.
 */
import { useMemo, useState } from 'react';
import { SEVERITY_RANK } from '../lib/diff';

const GROUPS = [
  { id: 'now', label: 'Fix before sending', hint: 'These can get a resume rejected or misread.', match: s => s === 'critical' || s === 'high' },
  { id: 'next', label: 'Worth improving', hint: 'Each one makes the resume more convincing.', match: s => s === 'medium' },
  { id: 'polish', label: 'Polish', hint: 'Small gains, once the rest is done.', match: s => s === 'low' || s === 'info' },
];
const FILTERS = [
  { id: 'all', label: 'All', match: () => true },
  { id: 'content', label: 'Content', match: f => f.source === 'rri' },
  { id: 'parsing', label: 'Parsing & format', match: f => f.source === 'ats' },
  { id: 'contact', label: 'Contact details', match: f => f.source === 'contact' || /contact/i.test(f.dimension || '') },
];
const SEV_LABEL = { critical: 'Critical', high: 'High', medium: 'Medium', low: 'Low', info: 'Note' };
const SOURCE = { rri: 'Readability', ats: 'ATS', quality: 'Quality', contact: 'Contact' };
const ACTION = { rewrite: 'Rewrite', edit: 'Edit', reorder: 'Reorder', remove: 'Remove', add: 'Add', format: 'Format' };
const HAS_BLANK = /\[[^\]]*\]/;

const points = f => (f.points > 0 ? `+${Number(f.points).toFixed(f.points < 1 ? 1 : 0)}` : null);

function Fix({ f, n, open, onToggle, onLocate }) {
  const canLocate = (f.line_ids?.length || f.statement_ids?.length) && onLocate;
  const where = f.line_ids?.length > 1 ? `${f.line_ids.length} lines` : f.line_ids?.length === 1 ? '1 line' : null;
  return (
    <li className="fx-item" data-sev={f.severity} data-open={open ? 'y' : 'n'}>
      <button type="button" className="fx-row" onClick={onToggle} aria-expanded={open}>
        <span className="fx-n">{String(n).padStart(2, '0')}</span>
        <span className="fx-main">
          <span className="fx-title">{f.title}</span>
          {f.fix && <span className="fx-do">{f.fix}</span>}
        </span>
        <span className="fx-side">
          <span className="fx-sev">{SEV_LABEL[f.severity] || f.severity}</span>
          {points(f) && <span className="fx-pts" title="Points this fix can recover, computed from the rubric">{points(f)} {f.source === 'rri' ? 'readability' : 'ATS'}</span>}
        </span>
      </button>
      {open && (
        <div className="fx-body">
          {f.detail && <p>{f.detail}</p>}
          {f.suggestion && (
            <div className="fx-sugg">
              <span>{HAS_BLANK.test(f.suggestion) ? 'Your bullet with the gaps marked. Fill each [ ] with a real detail.' : 'Suggested wording, using only what your resume already says'}</span>
              <p>{f.suggestion}</p>
            </div>
          )}
          <div className="fx-foot">
            <span>{[SOURCE[f.source] || f.source, f.dimension, ACTION[f.action] || f.action, where].filter(Boolean).join(' · ')}</span>
            {canLocate ? <button type="button" className="btn btn-secondary btn-sm" onClick={() => onLocate(f)}>Show in editor</button> : null}
          </div>
        </div>
      )}
    </li>
  );
}

export default function InsightsPanel({ insights = [], onLocate }) {
  const [filter, setFilter] = useState('all');
  const [open, setOpen] = useState(undefined);        // undefined = first item open by default

  const sorted = useMemo(
    () => [...insights].sort((a, b) =>
      (SEVERITY_RANK[b.severity] ?? 0) - (SEVERITY_RANK[a.severity] ?? 0) || (b.points || 0) - (a.points || 0)),
    [insights],
  );
  const active = FILTERS.find(x => x.id === filter) || FILTERS[0];
  const shown = sorted.filter(active.match);
  const urgent = sorted.filter(f => GROUPS[0].match(f.severity)).length;

  if (!insights.length) {
    return <p className="ed-muted">No findings were stored for this analysis. Run the analysis again to generate them.</p>;
  }

  let n = 0;
  return (
    <div className="fx">
      <header className="fx-head">
        <div>
          <h3>{urgent ? `${urgent} ${urgent === 1 ? 'thing' : 'things'} to fix before sending` : 'Nothing urgent'}</h3>
          <p>{insights.length} findings in total, ordered by how much each is worth. Open one for the reasoning and the exact lines.</p>
        </div>
        <div className="fx-filters" role="group" aria-label="Filter findings">
          {FILTERS.map(x => {
            const count = sorted.filter(x.match).length;
            return <button key={x.id} type="button" aria-pressed={filter === x.id} disabled={!count} onClick={() => setFilter(x.id)}>{x.label} {count}</button>;
          })}
        </div>
      </header>

      {GROUPS.map(g => {
        const items = shown.filter(f => g.match(f.severity));
        if (!items.length) return null;
        return (
          <section key={g.id} className="fx-group">
            <h4>{g.label}<span>{g.hint}</span></h4>
            <ol>
              {items.map(f => {
                n += 1;
                const isOpen = open === undefined ? n === 1 : open === f.id;
                return <Fix key={f.id} f={f} n={n} open={isOpen} onToggle={() => setOpen(isOpen ? null : f.id)} onLocate={onLocate} />;
              })}
            </ol>
          </section>
        );
      })}
      {shown.length === 0 && <p className="ed-muted">Nothing in this category.</p>}
    </div>
  );
}
