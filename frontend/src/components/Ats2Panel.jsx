/**
 * ATS 2.0: three checks that go beyond a keyword score, each shown with its evidence.
 *   1. Simulated 7-second skim, drawn on the real page: where a first look lands and what it misses.
 *   2. Impact: every bullet rated by whether it states an action, something specific and a measured result.
 *   3. Naive parser: what a simple text extractor recovers from the file, next to how a person reads it.
 * Every figure is labelled for what it is (a simulation, a naive parser); none claims to be a vendor's ATS.
 */
import { useEffect, useMemo, useState } from 'react';
import { getAts2Report, pageImageUrl } from '../api/client';

const TAG = {
  green: { label: 'Quantified result', short: 'Quantified', color: 'var(--accent-success)' },
  amber: { label: 'Action, no measured result', short: 'No result', color: 'var(--accent-warning)' },
  red: { label: 'Duty or involvement', short: 'Duty', color: 'var(--accent-danger)' },
};
const ROLE = { contact: 'Header', heading: 'Section heading', title: 'Entry title', meta: 'Entry detail', statement: 'Bullet', item: 'List item', text: 'Text' };
const tone = (v, good, mid) => (v >= good ? 'good' : v >= mid ? 'mid' : 'bad');

function Stat({ label, value, unit, note, tone: t }) {
  return (
    <div className="a2-stat" data-tone={t}>
      <span className="a2-stat-label">{label}</span>
      <span className="a2-stat-value"><b>{value}</b>{unit && <i>{unit}</i>}</span>
      <span className="a2-stat-note">{note}</span>
    </div>
  );
}

function SkimPage({ resumeId, resumeData, attention }) {
  const [page, setPage] = useState(0);
  const [heat, setHeat] = useState(true);
  const sizes = resumeData?.page_sizes || [];
  const lineById = useMemo(() => Object.fromEntries((resumeData?.lines || []).map(l => [l.id, l])), [resumeData]);
  if (!sizes.length) return null;
  const [w, h] = sizes[page];
  const spots = attention.lines.filter(x => x.page === page && x.weight > 0.05 && lineById[x.line_id]);
  return (
    <figure className="a2-figure">
      <div className="a2-page" style={{ aspectRatio: `${w} / ${h}` }}>
        <img src={pageImageUrl(resumeId, page, 1.5)} alt={`Page ${page + 1} of the resume`} loading="lazy" draggable={false} />
        {heat && spots.map(s => {
          const [x0, y0, x1, y1] = lineById[s.line_id].bbox;
          return (
            <i key={s.line_id} className="ed-heat" aria-hidden="true" style={{
              left: `${(x0 / w) * 100}%`, top: `${((y0 - 2) / h) * 100}%`, width: `${((x1 - x0) / w) * 100}%`,
              height: `${((y1 - y0 + 4) / h) * 100}%`, '--heat': (s.weight * 0.6).toFixed(3), '--hot': s.hot_fraction,
            }} />
          );
        })}
      </div>
      <figcaption>
        <label className="ed-toggle"><input type="checkbox" checked={heat} onChange={e => setHeat(e.target.checked)} /> Show where the skim lands</label>
        {sizes.length > 1 && (
          <span className="ed-seg">
            {sizes.map((_, p) => <button key={p} aria-selected={p === page} onClick={() => setPage(p)}>Page {p + 1}</button>)}
          </span>
        )}
      </figcaption>
    </figure>
  );
}

export default function Ats2Panel({ resumeId, analysisId, resumeData, onLocate, onReport }) {
  const [rep, setRep] = useState(null);
  const [err, setErr] = useState(null);
  const [view, setView] = useState('rows');
  const [filter, setFilter] = useState('all');
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let alive = true;
    setRep(null); setErr(null);
    getAts2Report(resumeId, analysisId)
      .then(r => { if (alive) { setRep(r); onReport?.(r); } })
      .catch(e => { if (alive) setErr(e.message); });
    return () => { alive = false; };
  }, [resumeId, analysisId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (err) return <div className="card"><p className="ed-error" role="alert">{err}</p></div>;
  if (!rep) return <div className="card"><p className="ed-muted">Running the skim, impact and parser checks…</p></div>;

  const { attention: a, impact: i, parser: p } = rep;
  const total = i.items.length;
  const counts = i.counts || {};
  const worst = p?.views?.filter(v => v.name !== 'tables').reduce((m, v) => (m === null || v.integrity < m ? v.integrity : m), null);
  const glyphs = p?.glyph_issues?.reduce((n, g) => n + g.count, 0) || 0;
  const shown = p?.views?.find(v => v.name === view) || p?.views?.[0];
  const items = i.items.filter(x => filter === 'all' || x.tag === filter);
  const visible = showAll ? items : items.slice(0, 8);
  const locate = sid => onLocate?.({ statement_ids: [sid], line_ids: [] });

  return (
    <div className="a2">
      <div className="a2-stats">
        {a
          ? <Stat label="Skim coverage" value={Math.round(a.seen_share * 100)} unit="%" tone={tone(a.seen_share, 0.4, 0.25)}
                  note={`${a.seen_line_ids.length} of ${a.total_lines} lines get a look in a 7-second skim`} />
          : <Stat label="Skim coverage" value="n/a" note="Needs page layout: upload the compiled PDF" tone="mid" />}
        <Stat label="Impact quotient" value={Math.round(i.viq)} unit="/ 100" tone={tone(i.viq, 50, 25)}
              note={total ? `${counts.green || 0} of ${total} bullets state a measured result` : 'No achievement bullets were found to rate'} />
        {p
          ? <Stat label="Parser fidelity" value={Math.round((worst ?? 1) * 100)} unit="%" tone={glyphs || p.field_checks.some(c => !Object.values(c.found_in).every(Boolean)) ? 'mid' : tone(worst ?? 1, 0.95, 0.85)}
                  note={glyphs ? `Reading order kept, but ${glyphs} characters extract as unknown symbols` : 'of your reading order survives naive extraction'} />
          : <Stat label="Parser fidelity" value="n/a" note="Runs on PDF uploads" tone="mid" />}
      </div>

      {/* 1 ── skim */}
      <section className="card a2-section">
        <header className="a2-head">
          <div><span className="eyebrow">Check 1</span><h3>What a 7-second skim sees</h3></div>
          <span className="badge badge-neutral">Simulated</span>
        </header>
        {a ? (
          <div className="a2-skim">
            <SkimPage resumeId={resumeId} resumeData={resumeData} attention={a} />
            <div className="a2-col">
              <p className="a2-verdict">{a.verdict}</p>
              <h4>Where the first look lands</h4>
              <ol className="a2-seen">
                {a.seen_lines.map(s => (
                  <li key={s.line_id}>
                    <span className="a2-meter" aria-hidden="true"><i style={{ width: `${Math.round(s.weight * 100)}%` }} /></span>
                    <span className="a2-seen-text">{s.text}</span>
                    <span className="a2-kind">{ROLE[s.role] || s.role}</span>
                  </li>
                ))}
              </ol>
              {a.missed_strong?.length > 0 && (
                <>
                  <h4>Strong bullets a skimmer is likely to miss</h4>
                  <ul className="a2-list">
                    {a.missed_strong.map(m => (
                      <li key={m.statement_id}>
                        <span>{m.text}</span>
                        <small>{m.entry} · grade {m.grade}. Move it up, or lead with the result.</small>
                        <button className="link-btn" onClick={() => locate(m.statement_id)}>Open in editor</button>
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="a2-note">{a.disclosure} {a.budget_fixations} fixations are shared out by position, type size, weight and numbers.</p>
            </div>
          </div>
        ) : <p className="ed-muted">The skim simulation needs page layout. Upload the compiled PDF to see it.</p>}
      </section>

      {/* 2 ── impact */}
      <section className="card a2-section">
        <header className="a2-head">
          <div><span className="eyebrow">Check 2</span><h3>Does each bullet prove something?</h3></div>
          <span className="badge badge-neutral">{Math.round(i.viq_weighted)}% weighted by section</span>
        </header>
        {total === 0 ? (
          <p className="ed-muted">No bullets were found under experience, projects or volunteering, so there is nothing to rate.
            {rep.total_statements > 0 && ` The parser found ${rep.total_statements} statements elsewhere in the resume.`}</p>
        ) : (
          <>
            <div className="a2-bar" role="img" aria-label={`${counts.green || 0} quantified, ${counts.amber || 0} without a measured result, ${counts.red || 0} duty statements`}>
              {['green', 'amber', 'red'].map(t => counts[t] > 0 && <i key={t} style={{ flexGrow: counts[t], background: TAG[t].color }} />)}
            </div>
            <div className="a2-filters" role="group" aria-label="Filter bullets">
              <button aria-pressed={filter === 'all'} onClick={() => setFilter('all')}>All {total}</button>
              {['green', 'amber', 'red'].map(t => (
                <button key={t} aria-pressed={filter === t} onClick={() => setFilter(t)} disabled={!counts[t]}>
                  <i style={{ background: TAG[t].color }} />{TAG[t].label} {counts[t] || 0}
                </button>
              ))}
            </div>
            <ul className="a2-bullets">
              {visible.map(x => (
                <li key={x.statement_id}>
                  <i className="a2-dot" style={{ background: TAG[x.tag].color }} title={TAG[x.tag].label} />
                  <div>
                    <p>{x.text}</p>
                    <small>{x.entry || x.section}{x.grade && ` · grade ${x.grade}`} · opens with “{x.verb}”{x.tier === 1 ? ' (strong verb)' : x.tier === 3 ? ' (passive)' : ''} · {x.why}</small>
                  </div>
                  <button className="link-btn" onClick={() => locate(x.statement_id)}>{x.tag === 'green' ? 'View' : 'Fix in editor'}</button>
                </li>
              ))}
            </ul>
            {items.length > 8 && <button className="link-btn" onClick={() => setShowAll(s => !s)}>{showAll ? 'Show fewer' : `Show all ${items.length}`}</button>}
            <p className="a2-note">Impact quotient = bullets with an action, something specific and a number, divided by all rated bullets. Experience counts 1.6×, volunteering 0.4×.</p>
          </>
        )}
      </section>

      {/* 3 ── parser */}
      <section className="card a2-section">
        <header className="a2-head">
          <div><span className="eyebrow">Check 3</span><h3>What a simple parser recovers</h3></div>
          <span className="badge badge-neutral">Naive extraction</span>
        </header>
        {!p ? <p className="ed-muted">This check runs on PDF uploads.</p> : (
          <>
            <p className="a2-verdict">{p.verdict}</p>
            {p.advice?.length > 0 && (
              <ol className="a2-advice">{p.advice.map((t, k) => <li key={k}>{t}</li>)}</ol>
            )}
            <div className="a2-facts">
              {p.glyph_issues?.length > 0 && (
                <table className="a2-table">
                  <caption>Characters a parser cannot read</caption>
                  <thead><tr><th>Character</th><th>What it is</th><th>Count</th><th>Seen in</th></tr></thead>
                  <tbody>
                    {p.glyph_issues.map(g => (
                      <tr key={g.codepoint}><td><code>{g.codepoint}</code></td><td>{g.kind}</td><td>{g.count}</td><td className="a2-ex">{g.example}</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
              {p.field_checks?.length > 0 && (
                <table className="a2-table">
                  <caption>Contact details recovered</caption>
                  <thead><tr><th>Field</th>{p.views.filter(v => v.name !== 'tables').map(v => <th key={v.name}>{v.name}</th>)}</tr></thead>
                  <tbody>
                    {p.field_checks.map(c => (
                      <tr key={c.field}><td>{c.field}</td>
                        {p.views.filter(v => v.name !== 'tables').map(v => <td key={v.name} data-ok={c.found_in[v.name] ? 'y' : 'n'}>{c.found_in[v.name] ? 'Found' : 'Lost'}</td>)}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
            <div className="a2-compare-head">
              <h4>Side by side</h4>
              <span className="ed-seg">
                {p.views.map(v => <button key={v.name} aria-selected={shown?.name === v.name} onClick={() => setView(v.name)}>{v.name}</button>)}
              </span>
            </div>
            <div className="a2-compare">
              <div><span className="a2-pane-label">As you read it</span><pre data-lenis-prevent>{p.reference}</pre></div>
              <div>
                <span className="a2-pane-label">Naive “{shown?.name}” extraction{shown?.name !== 'tables' && ` · ${Math.round((shown?.integrity || 0) * 100)}% of the order kept`}</span>
                <pre data-lenis-prevent>{shown?.text}</pre>
              </div>
            </div>
            {shown?.issues?.length > 0 && <ul className="ed-reasons">{shown.issues.map((x, k) => <li key={k}>{x}</li>)}</ul>}
            <p className="a2-note">{p.disclosure} “stream” reads text in the file's internal order; “rows” reads straight across the page, ignoring columns.</p>
          </>
        )}
      </section>
    </div>
  );
}
