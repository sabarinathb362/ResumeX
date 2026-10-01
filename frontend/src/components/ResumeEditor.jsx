/**
 * ResumeEditor — shows the real resume and anchors every finding to it.
 *
 *  Page view : the uploaded PDF rendered by the backend, with boxes drawn on the
 *              exact lines each finding refers to (colour = severity) and a
 *              grade bar next to every bullet (A–D).
 *  Text view : the parsed resume as a clean document with tracked changes
 *              (deleted words struck through, inserted words highlighted).
 *  Side panel: click any highlighted line to see why it was flagged and get
 *              grounded suggestions. Rule-based and local-AI suggestions are
 *              fact-checked server-side; fill-in templates must be completed
 *              by you before they can be accepted.
 */
import { useEffect, useMemo, useState, useCallback } from 'react';
import '../editor.css';
import {
  pageImageUrl, suggestForStatement,
  exportResumeDocx, exportResumeLatex, exportResumePdf, exportResumeTxt,
} from '../api/client';
import { wordDiff, applyEdits, SEVERITY_COLOR, SEVERITY_RANK, GRADE_COLOR } from '../lib/diff';

const SOURCE_LABEL = { rules: 'Rearranged from your words', llm: 'Local AI · fact-checked', template: 'Fill in the blanks', user: 'Your edit' };
const HAS_BLANK = /\[[^\]]*\]/;

function Diff({ from, to }) {
  const parts = useMemo(() => wordDiff(from, to), [from, to]);
  return (
    <span className="ed-diff">
      {parts.map((p, i) =>
        p.type === 'same' ? <span key={i}>{p.text}</span>
          : p.type === 'del' ? <del key={i}>{p.text}</del>
            : <ins key={i}>{p.text}</ins>)}
    </span>
  );
}

function maxSeverity(findings) {
  return findings.reduce((best, f) => (SEVERITY_RANK[f.severity] > SEVERITY_RANK[best] ? f.severity : best), 'info');
}

export default function ResumeEditor({ resumeId, resumeData, analysis, focus, onBack }) {
  const insights = analysis?.insights || [];
  const rri = analysis?.readability_result;
  const lines = resumeData?.lines || [];
  const sections = resumeData?.doc_sections || [];
  const pageSizes = resumeData?.page_sizes || [];
  const renderable = resumeData?.document_metadata?.file_type === 'pdf' && pageSizes.length > 0;

  const [view, setView] = useState(renderable ? 'page' : 'text');
  const [layers, setLayers] = useState({ issues: true, grades: true });
  const [sel, setSel] = useState(null); // { lineIds, statementId, findingId }
  const [edits, setEdits] = useState({}); // statementId -> { text, source }
  const [sugg, setSugg] = useState({}); // statementId -> server response
  const [loadingSid, setLoadingSid] = useState(null);
  const [draft, setDraft] = useState(null); // { sid, text }
  const [facts, setFacts] = useState('');
  const [exporting, setExporting] = useState(null);
  const [error, setError] = useState(null);

  // ── indexes ────────────────────────────────────────────────────
  const { statementsById, lineToStatement } = useMemo(() => {
    const byId = {}, l2s = {};
    for (const section of sections) {
      for (const entry of section.entries || []) {
        for (const st of entry.statements || []) {
          byId[st.id] = { statement: st, entry, section };
          for (const lid of st.line_ids || []) l2s[lid] = st.id;
        }
      }
    }
    return { statementsById: byId, lineToStatement: l2s };
  }, [sections]);

  const findingsByLine = useMemo(() => {
    const m = {};
    for (const f of insights) for (const lid of f.line_ids || []) (m[lid] ||= []).push(f);
    return m;
  }, [insights]);

  const gradeById = useMemo(() => Object.fromEntries((rri?.statements || []).map(g => [g.id, g])), [rri]);
  const lineById = useMemo(() => Object.fromEntries(lines.map(l => [l.id, l])), [lines]);

  // ── selection ──────────────────────────────────────────────────
  const selectFinding = useCallback((f) => {
    const sid = f.statement_ids?.[0] || (f.line_ids || []).map(l => lineToStatement[l]).find(Boolean) || null;
    setSel({ lineIds: f.line_ids || [], statementId: sid, findingId: f.id });
    setDraft(null);
  }, [lineToStatement]);

  const selectLine = (lid) => {
    const sid = lineToStatement[lid];
    setSel({ lineIds: sid ? statementsById[sid].statement.line_ids : [lid], statementId: sid || null, findingId: null });
    setDraft(null);
  };

  const selectStatement = (sid) => {
    const ref = statementsById[sid];
    if (!ref) return;
    setSel({ lineIds: ref.statement.line_ids, statementId: sid, findingId: null });
    setDraft(null);
  };

  useEffect(() => { if (focus) selectFinding(focus); }, [focus, selectFinding]);

  useEffect(() => {
    if (!sel) return;
    const id = view === 'page' ? `ov-${sel.lineIds?.[0]}` : `tx-${sel.statementId}`;
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [sel, view]);

  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') { setSel(null); setDraft(null); } };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── actions ────────────────────────────────────────────────────
  const loadSuggestions = async (sid, withFacts = null) => {
    setLoadingSid(sid); setError(null);
    try {
      const res = await suggestForStatement(resumeId, sid, { userFacts: withFacts });
      setSugg(s => ({ ...s, [sid]: res }));
    } catch (e) { setError(e.message); }
    finally { setLoadingSid(null); }
  };

  const accept = (sid, text, source) => {
    if (HAS_BLANK.test(text)) { setDraft({ sid, text }); return; }  // templates must be completed first
    setEdits(e => ({ ...e, [sid]: { text: text.trim(), source } }));
    setDraft(null);
  };
  const undo = (sid) => setEdits(e => { const n = { ...e }; delete n[sid]; return n; });

  const handleExport = async (fmt) => {
    setExporting(fmt); setError(null);
    try {
      const data = applyEdits(resumeData, statementsById, edits);
      const name = `${(data.contact?.name || 'Resume').replace(/[^\w-]/g, '_')}_edited`;
      const fn = { docx: exportResumeDocx, latex: exportResumeLatex, pdf: exportResumePdf, txt: exportResumeTxt }[fmt];
      await fn(data, name);
    } catch (e) { setError(e.message); }
    finally { setExporting(null); }
  };

  // ── overlays per page ──────────────────────────────────────────
  const overlays = useMemo(() => {
    const byPage = {};
    for (const l of lines) {
      const fs = findingsByLine[l.id] || [];
      const sid = lineToStatement[l.id];
      const grade = sid ? gradeById[sid]?.grade : null;
      if (!fs.length && !grade && !(sid && edits[sid])) continue;
      (byPage[l.page] ||= []).push({ line: l, findings: fs, sid, grade, sev: maxSeverity(fs) });
    }
    return byPage;
  }, [lines, findingsByLine, lineToStatement, gradeById, edits]);

  const selectedSet = new Set(sel?.lineIds || []);
  const editCount = Object.keys(edits).length;
  const selRef = sel?.statementId ? statementsById[sel.statementId] : null;

  const selFindings = useMemo(() => {
    if (!sel) return [];
    const seen = new Set(), out = [];
    const add = (f) => { if (f && !seen.has(f.id)) { seen.add(f.id); out.push(f); } };
    if (sel.findingId) add(insights.find(x => x.id === sel.findingId));
    for (const lid of sel.lineIds || []) (findingsByLine[lid] || []).forEach(add);
    return out;
  }, [sel, findingsByLine, insights]);

  // ── side panel pieces ──────────────────────────────────────────
  const renderStatementCard = () => {
    if (!selRef) return null;
    const sid = sel.statementId;
    const st = selRef.statement;
    const g = gradeById[sid];
    const s = sugg[sid];
    const edited = edits[sid];
    return (
      <div className="ed-card">
        <div className="ed-card-head">
          <span className="ed-where">{selRef.section.heading}{selRef.entry.title ? ` › ${selRef.entry.title}` : ''}</span>
          {g && <span className="ed-grade" style={{ background: GRADE_COLOR[g.grade] }} title="Bullet grade">{g.grade}</span>}
        </div>

        {edited ? (
          <>
            <p className="ed-text"><Diff from={st.text} to={edited.text} /></p>
            <div className="ed-row">
              <span className="ed-chip-ok">Accepted · {SOURCE_LABEL[edited.source] || 'Your edit'}</span>
              <button className="ed-link" onClick={() => undo(sid)}>Undo</button>
            </div>
          </>
        ) : <p className="ed-text">{st.text}</p>}

        {g?.reasons?.length > 0 && <ul className="ed-reasons">{g.reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>}

        {!s && (
          <button className="btn btn-primary btn-sm" disabled={loadingSid === sid} onClick={() => loadSuggestions(sid)}>
            {loadingSid === sid ? 'Working…' : 'Suggest improvements'}
          </button>
        )}

        {s && (
          <div className="ed-suggs">
            {s.question && <p className="ed-q">{s.question}</p>}
            {s.suggestions.length === 0 && (
              <p className="ed-muted">No safe rewrite is possible from what's written. Add a fact below and regenerate.</p>
            )}
            {s.suggestions.map((c, i) => (
              <div key={i} className="ed-sugg">
                <div className="ed-sugg-src">{SOURCE_LABEL[c.source] || c.source}</div>
                <p className="ed-text">{c.needs_input ? c.text : <Diff from={st.text} to={c.text} />}</p>
                <div className="ed-row">
                  <span className="ed-muted">{c.why}</span>
                  <button className="btn btn-secondary btn-sm" onClick={() => accept(sid, c.text, c.source)}>
                    {c.needs_input ? 'Fill in' : 'Accept'}
                  </button>
                </div>
              </div>
            ))}
            {s.rejected?.length > 0 && (
              <details className="ed-rejected">
                <summary>{s.rejected.length} suggestion{s.rejected.length > 1 ? 's' : ''} blocked by the fact-checker</summary>
                {s.rejected.map((r, i) => (
                  <div key={i}><p className="ed-strike">{r.text}</p><p className="ed-muted">{(r.problems || []).join('; ')}</p></div>
                ))}
              </details>
            )}
            <div className="ed-facts">
              <label htmlFor="ed-facts">Give it a real fact to use</label>
              <textarea id="ed-facts" rows={2} value={facts} onChange={e => setFacts(e.target.value)}
                placeholder="e.g. evaluated 3 open-source LLMs on 500 test prompts; cut manual review from 2 days to 3 hours" />
              <button className="btn btn-ghost btn-sm" disabled={!facts.trim() || loadingSid === sid}
                onClick={() => loadSuggestions(sid, facts.trim())}>Regenerate with this fact</button>
            </div>
          </div>
        )}

        {draft?.sid === sid ? (
          <div className="ed-draft">
            <label htmlFor="ed-draft">Edit before accepting</label>
            <textarea id="ed-draft" rows={4} value={draft.text} onChange={e => setDraft({ sid, text: e.target.value })} />
            {HAS_BLANK.test(draft.text) && <p className="ed-warn">Replace every [bracketed] part with your real details.</p>}
            <div className="ed-row">
              <button className="btn btn-primary btn-sm" disabled={HAS_BLANK.test(draft.text) || !draft.text.trim()}
                onClick={() => accept(sid, draft.text, 'user')}>Accept edit</button>
              <button className="ed-link" onClick={() => setDraft(null)}>Cancel</button>
            </div>
          </div>
        ) : !edited && (
          <button className="ed-link" onClick={() => setDraft({ sid, text: st.text })}>Edit manually</button>
        )}
      </div>
    );
  };

  const renderFinding = (f) => {
    const canApply = sel?.statementId && f.suggestion && f.statement_ids?.includes(sel.statementId);
    const isTemplate = f.suggestion && HAS_BLANK.test(f.suggestion);
    return (
      <div key={f.id} className={`ed-finding ${sel?.findingId === f.id ? 'is-active' : ''}`} style={{ borderLeftColor: SEVERITY_COLOR[f.severity] }}>
        <div className="ed-finding-title">{f.title}</div>
        {f.detail && <p className="ed-muted">{f.detail}</p>}
        {f.fix && <p className="ed-fix">{f.fix}</p>}
        {f.suggestion && (
          <div className="ed-sugg">
            <div className="ed-sugg-src">{isTemplate ? SOURCE_LABEL.template : 'Built from your resume'}</div>
            <p className="ed-text">{canApply && !isTemplate
              ? <Diff from={statementsById[sel.statementId]?.statement.text || ''} to={f.suggestion} /> : f.suggestion}</p>
            {canApply && (
              <button className="btn btn-secondary btn-sm" onClick={() => accept(sel.statementId, f.suggestion, 'rules')}>
                {isTemplate ? 'Fill in' : 'Accept'}
              </button>
            )}
          </div>
        )}
        <div className="ed-row ed-meta">
          <span>{f.source === 'ats' ? 'ATS' : f.source === 'rri' ? 'Readability' : 'Contact'} · {f.dimension}</span>
          {f.points > 0 && <span>worth +{f.points} pts</span>}
        </div>
        {f.norm_ref && <div className="ed-norm">Role norm: {f.norm_ref}</div>}
      </div>
    );
  };

  const overview = (
    <>
      <p className="ed-muted ed-intro">
        Click a highlighted line, or an issue below. Box colour shows severity; the bar on the left of a bullet shows its grade.
      </p>
      {insights.map(f => (
        <button key={f.id} className="ed-ov-item" onClick={() => selectFinding(f)}>
          <span className="ed-dot" style={{ background: SEVERITY_COLOR[f.severity] }} />
          <span className="ed-ov-title">{f.title}</span>
          {f.points > 0 && <span className="ed-ov-pts">+{f.points}</span>}
        </button>
      ))}
    </>
  );

  // ── canvases ───────────────────────────────────────────────────
  const pageView = (
    <div className="ed-pages">
      {pageSizes.map(([w, h], p) => (
        <div key={p} className="ed-page" style={{ aspectRatio: `${w} / ${h}` }}>
          <img src={pageImageUrl(resumeId, p)} alt={`Resume page ${p + 1}`} draggable={false} />
          {(overlays[p] || []).map(({ line, findings, sid, grade, sev }) => {
            const [x0, y0, x1, y1] = line.bbox;
            const edited = sid && edits[sid];
            const showIssue = layers.issues && findings.length > 0;
            if (!showIssue && !(layers.grades && grade) && !edited) return null;
            return (
              <button key={line.id} id={`ov-${line.id}`} type="button"
                className={`ed-ov${selectedSet.has(line.id) ? ' is-sel' : ''}${edited ? ' is-edited' : ''}${showIssue ? '' : ' is-quiet'}`}
                style={{
                  left: `${(x0 / w) * 100}%`, top: `${((y0 - 1.5) / h) * 100}%`,
                  width: `${((x1 - x0) / w) * 100}%`, height: `${((y1 - y0 + 3) / h) * 100}%`,
                  '--sev': SEVERITY_COLOR[sev], '--grade': grade ? GRADE_COLOR[grade] : 'transparent',
                }}
                title={findings.map(f => f.title).join('\n') || (grade ? `Bullet grade ${grade}` : '')}
                aria-label={findings[0]?.title || line.text.slice(0, 60)}
                onClick={() => selectLine(line.id)}>
                {layers.grades && grade && <span className="ed-ov-grade" />}
                {edited && line.id === statementsById[sid].statement.line_ids[0] && <span className="ed-ov-badge">edited</span>}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );

  const textView = (
    <div className="ed-paper">
      <div className="ed-paper-name">{resumeData?.contact?.name}</div>
      <div className="ed-paper-contact">
        {[resumeData?.contact?.email, resumeData?.contact?.phone, resumeData?.contact?.linkedin, resumeData?.contact?.github].filter(Boolean).join(' · ')}
      </div>
      {sections.map(sec => (
        <section key={sec.id}>
          <h3 className="ed-paper-h">{sec.heading}</h3>
          {(sec.entries || []).map(e => (
            <div key={e.id} className="ed-paper-entry">
              {(e.title || e.dates) && (
                <div className="ed-paper-title"><span>{e.title}{e.tags?.length ? ` — ${e.tags.join(', ')}` : ''}</span><span>{e.dates}</span></div>
              )}
              {e.subtitle && <div className="ed-paper-sub">{e.subtitle}</div>}
              {(e.statements || []).map(st => {
                const fs = (st.line_ids || []).flatMap(l => findingsByLine[l] || []);
                const g = gradeById[st.id];
                const ed = edits[st.id];
                return (
                  <p key={st.id} id={`tx-${st.id}`}
                    className={`ed-paper-st${sel?.statementId === st.id ? ' is-sel' : ''}`}
                    style={fs.length && layers.issues ? { background: `${SEVERITY_COLOR[maxSeverity(fs)]}26` } : undefined}
                    onClick={() => selectStatement(st.id)}>
                    {g && layers.grades && <span className="ed-gchip" style={{ background: GRADE_COLOR[g.grade] }}>{g.grade}</span>}
                    {ed ? <Diff from={st.text} to={ed.text} /> : st.text}
                  </p>
                );
              })}
            </div>
          ))}
        </section>
      ))}
    </div>
  );

  return (
    <div className="ed-root">
      <div className="ed-toolbar">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>Dashboard</button>
        <div className="ed-seg" role="tablist">
          <button role="tab" aria-selected={view === 'page'} disabled={!renderable} onClick={() => setView('page')}>Your PDF</button>
          <button role="tab" aria-selected={view === 'text'} onClick={() => setView('text')}>Text + changes</button>
        </div>
        <label className="ed-toggle"><input type="checkbox" checked={layers.issues} onChange={e => setLayers(l => ({ ...l, issues: e.target.checked }))} /> Issues</label>
        <label className="ed-toggle"><input type="checkbox" checked={layers.grades} onChange={e => setLayers(l => ({ ...l, grades: e.target.checked }))} /> Bullet grades</label>
        <div className="ed-legend" aria-hidden="true">
          {['A', 'B', 'C', 'D'].map(g => <span key={g}><i style={{ background: GRADE_COLOR[g] }} />{g}</span>)}
        </div>
        <div className="ed-spacer" />
        <span className="ed-muted">{editCount} change{editCount === 1 ? '' : 's'}</span>
        {['pdf', 'docx', 'latex', 'txt'].map(f => (
          <button key={f} className="btn btn-secondary btn-sm" disabled={!!exporting} onClick={() => handleExport(f)}>
            {exporting === f ? '…' : f === 'latex' ? '.tex' : `.${f}`}
          </button>
        ))}
      </div>
      {error && <div className="ed-error" role="alert">{error}</div>}
      {!renderable && <div className="ed-note">Page preview is available for PDF uploads; this file is shown as parsed text.</div>}

      <div className="ed-body">
        <div className="ed-canvas">{view === 'page' ? pageView : textView}</div>
        <aside className="ed-side" aria-label="Suggestions">
          {sel ? (
            <>
              <button className="ed-link" onClick={() => { setSel(null); setDraft(null); }}>All issues</button>
              {renderStatementCard()}
              {!selRef && sel.lineIds?.length > 0 && (
                <div className="ed-card"><p className="ed-text">{sel.lineIds.map(l => lineById[l]?.text).filter(Boolean).join(' ')}</p></div>
              )}
              {selFindings.length > 0 && <h4 className="ed-side-h">Why this was flagged</h4>}
              {selFindings.map(renderFinding)}
              {!selFindings.length && !selRef && <p className="ed-muted">Nothing flagged on this line.</p>}
            </>
          ) : overview}

          {editCount > 0 && (
            <div className="ed-changes">
              <h4 className="ed-side-h">Accepted changes</h4>
              {Object.entries(edits).map(([sid, e]) => (
                <div key={sid} className="ed-change">
                  <button className="ed-link" onClick={() => selectStatement(sid)}>
                    {statementsById[sid]?.entry.title || statementsById[sid]?.section.heading}
                  </button>
                  <p className="ed-text"><Diff from={statementsById[sid]?.statement.text || ''} to={e.text} /></p>
                  <button className="ed-link" onClick={() => undo(sid)}>Undo</button>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
