/**
 * ResumeEditor (ResumeX 2.0) — the real resume with every finding anchored to it.
 *
 *  Page view : the uploaded PDF rendered by the backend, with boxes on the exact lines
 *              each finding refers to (colour = severity) and a grade bar per bullet.
 *  Text view : a Tiptap editor. Bullets are directly editable; headings are locked.
 *  Sidebar   : Live fixes (rules instantly, local AI streaming in, fact-checked),
 *              JD gaps (each requirement anchored to its evidence) and Strategy.
 */
import { useEffect, useMemo, useState, useCallback, useRef } from 'react';
import '../editor.css';
import {
  pageImageUrl, getEditorSidebar, getProjectRecommendations, getAts2Report,
  getEditorUnits, previewLayout, exportOriginalPdf,
  exportResumeDocx, exportResumeLatex, exportResumePdf, exportResumeTxt,
} from '../api/client';
import { wordDiff, applyEdits, SEVERITY_COLOR, SEVERITY_RANK, GRADE_COLOR } from '../lib/diff';
import { useSuggestionStream } from '../hooks/useSuggestionStream';
import ResumeTextCanvas from './editor/ResumeTextCanvas';
import { SidebarTabs, JDGapsTab, StrategyTab } from './editor/EditorSidebar';

const SOURCE_LABEL = { rules: 'Rearranged from your words', llm: 'Local model · fact-checked', template: 'Fill in the blanks', user: 'Your edit' };
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

export default function ResumeEditor({ resumeId, resumeData, analysis, jdId = null, focus, onBack, onNew, onEditsChange }) {
  const insights = analysis?.insights || [];
  const rri = analysis?.readability_result;
  const lines = resumeData?.lines || [];
  const sections = resumeData?.doc_sections || [];
  const pageSizes = resumeData?.page_sizes || [];
  const renderable = resumeData?.document_metadata?.file_type === 'pdf' && pageSizes.length > 0;

  const [view, setView] = useState(renderable ? 'page' : 'text');
  const [layers, setLayers] = useState({ issues: true, grades: true, gaze: false });
  const [attention, setAttention] = useState(null);
  const [tab, setTab] = useState('fix');
  const [sel, setSel] = useState(null);          // { lineIds, statementId, findingId }
  const [edits, setEdits] = useState({});        // statementId | "add:<entry>:<n>" -> { text, source, entryId? }
  const [draft, setDraft] = useState(null);      // { sid, text }
  const [factsBySid, setFactsBySid] = useState({});
  const [alignBySid, setAlignBySid] = useState({});
  const [sidebar, setSidebar] = useState(null);
  const [sidebarError, setSidebarError] = useState(null);
  const [projects, setProjects] = useState(null);
  const [exporting, setExporting] = useState(null);
  const [error, setError] = useState(null);
  // Editing in the original layout (PDF uploads)
  const [units, setUnits] = useState([]);           // editable text runs of the PDF
  const [unitEdits, setUnitEdits] = useState({});   // unit id -> text, for text that is not a bullet
  const [pageImages, setPageImages] = useState({}); // page -> data URL with the edits typeset in place
  const [fit, setFit] = useState({});               // edit key -> { ok, reason, scale, font }
  const [inline, setInline] = useState(null);       // the text box open on the page
  const inlineDone = useRef(false);
  const { bySid: streamState, run: runStream, cancel: cancelStream } = useSuggestionStream(resumeId);

  // ── indexes ──
  const { statementsById, lineToStatement, entriesById, addableEntries } = useMemo(() => {
    const byId = {}, l2s = {}, entries = {}, addable = [];
    for (const section of sections) {
      for (const entry of section.entries || []) {
        entries[entry.id] = entry;
        if (['experience', 'projects', 'volunteer', 'leadership'].includes(section.kind) && entry.statements?.length) {
          addable.push({ id: entry.id, title: entry.title, section: section.heading });
        }
        for (const st of entry.statements || []) {
          byId[st.id] = { statement: st, entry, section };
          for (const lid of st.line_ids || []) l2s[lid] = st.id;
        }
      }
    }
    return { statementsById: byId, lineToStatement: l2s, entriesById: entries, addableEntries: addable };
  }, [sections]);

  const findingsByLine = useMemo(() => {
    const m = {};
    for (const f of insights) for (const lid of f.line_ids || []) (m[lid] ||= []).push(f);
    return m;
  }, [insights]);

  const gradeById = useMemo(() => Object.fromEntries((rri?.statements || []).map(g => [g.id, g])), [rri]);
  const lineById = useMemo(() => Object.fromEntries(lines.map(l => [l.id, l])), [lines]);
  const severityBySid = useMemo(() => {
    const m = {};
    for (const [sid, ref] of Object.entries(statementsById)) {
      const fs = (ref.statement.line_ids || []).flatMap(l => findingsByLine[l] || []);
      if (fs.length) m[sid] = maxSeverity(fs);
    }
    return m;
  }, [statementsById, findingsByLine]);

  // ── sidebar data (JD gaps + strategy), once per resume/JD ──
  useEffect(() => {
    let alive = true;
    setSidebar(null); setSidebarError(null);
    getEditorSidebar(resumeId, jdId)
      .then(d => { if (alive) setSidebar(d); })
      .catch(e => { if (alive) setSidebarError(e.message); });
    return () => { alive = false; };
  }, [resumeId, jdId]);

  // ── simulated skim (ATS 2.0 gaze layer) ──
  useEffect(() => {
    let alive = true;
    getAts2Report(resumeId, analysis?.id).then(r => { if (alive) setAttention(r.attention); }).catch(() => {});
    return () => { alive = false; };
  }, [resumeId, analysis?.id]);

  const heatByPage = useMemo(() => {
    const m = {};
    for (const h of attention?.lines || []) {
      const l = lineById[h.line_id];
      if (l && h.weight > 0.05) (m[l.page] ||= []).push({ ...h, bbox: l.bbox });
    }
    return m;
  }, [attention, lineById]);

  // ── suggestions ──
  const currentText = useCallback((sid) => edits[sid]?.text ?? statementsById[sid]?.statement.text ?? '', [edits, statementsById]);

  const loadSuggestions = useCallback((sid, { userFacts = null, jdRequirement = null, immediate = false } = {}) => {
    if (!sid || !statementsById[sid]) return;
    runStream(sid, {
      currentText: currentText(sid),
      userFacts: userFacts ?? (factsBySid[sid]?.trim() || null),
      jdRequirement: jdRequirement ?? alignBySid[sid] ?? null,
      immediate,
    });
  }, [runStream, currentText, factsBySid, alignBySid, statementsById]);

  // ── selection ──
  const select = useCallback((next) => {
    setSel(next);
    setDraft(null);
    if (next?.statementId) { setTab('fix'); loadSuggestions(next.statementId); }
    else cancelStream();
  }, [loadSuggestions, cancelStream]);

  const selectFinding = useCallback((f) => {
    const sid = f.statement_ids?.[0] || (f.line_ids || []).map(l => lineToStatement[l]).find(Boolean) || null;
    select({ lineIds: f.line_ids || [], statementId: sid, findingId: f.id });
  }, [lineToStatement, select]);

  const selectLine = (lid) => {
    const sid = lineToStatement[lid];
    select({ lineIds: sid ? statementsById[sid].statement.line_ids : [lid], statementId: sid || null, findingId: null });
  };

  const selectStatement = useCallback((sid) => {
    const ref = statementsById[sid];
    if (!ref || sel?.statementId === sid) return;
    select({ lineIds: ref.statement.line_ids, statementId: sid, findingId: null });
  }, [statementsById, sel, select]);

  const locate = (statementIds, lineIds) => {
    const sid = statementIds?.[0];
    if (sid) selectStatement(sid);
    else select({ lineIds: lineIds || [], statementId: null, findingId: null });
  };

  const alignTo = (sid, requirement) => {
    setAlignBySid(m => ({ ...m, [sid]: requirement }));
    const ref = statementsById[sid];
    setSel({ lineIds: ref?.statement.line_ids || [], statementId: sid, findingId: null });
    setTab('fix');
    loadSuggestions(sid, { jdRequirement: requirement, immediate: true });
  };

  // Run only when a new focus arrives from the dashboard, not every time callbacks change.
  const latestSelectFinding = useRef(selectFinding);
  latestSelectFinding.current = selectFinding;
  useEffect(() => { if (focus) latestSelectFinding.current(focus); }, [focus]);

  useEffect(() => {
    if (!sel || view !== 'page') return;
    document.getElementById(`ov-${sel.lineIds?.[0]}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }, [sel, view]);

  const latestSelect = useRef(select);
  latestSelect.current = select;
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') latestSelect.current(null); };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // ── edits ──
  const accept = (sid, text, source) => {
    if (HAS_BLANK.test(text)) { setDraft({ sid, text }); return; }  // templates must be completed first
    setEdits(e => ({ ...e, [sid]: { ...(e[sid] || {}), text: text.trim(), source } }));
    setDraft(null);
  };
  const undo = (sid) => setEdits(e => { const n = { ...e }; delete n[sid]; return n; });
  const onEditText = (sid, text) => {
    const original = statementsById[sid]?.statement.text;
    setEdits(e => {
      if (!sid.startsWith('add:') && text.trim() === (original || '').trim()) { const n = { ...e }; delete n[sid]; return n; }
      return { ...e, [sid]: { ...(e[sid] || {}), text, source: 'user' } };
    });
  };
  const addBullet = (entryId, text) => {
    const sid = `add:${entryId}:${Date.now()}`;
    setEdits(e => ({ ...e, [sid]: { text, source: 'user', entryId } }));
  };
  // Every ready-to-use rewrite: the rule-based fix on each finding, plus the first fact-checked suggestion
  // already loaded for a bullet. Templates with [blanks] need the user's facts, so they are left out.
  // Edits go through layoutEdits, i.e. they are typeset into the original PDF: the template is never changed.
  const pendingSuggestions = useMemo(() => {
    const out = {};
    for (const f of insights) {
      const sid = f.statement_ids?.length === 1 ? f.statement_ids[0] : null;
      if (!sid || !statementsById[sid] || edits[sid] || out[sid]) continue;
      if (f.suggestion && !HAS_BLANK.test(f.suggestion)) out[sid] = { text: f.suggestion.trim(), source: 'rules' };
    }
    for (const [sid, s] of Object.entries(streamState)) {
      if (!statementsById[sid] || edits[sid]) continue;
      const c = [...(s.llm || []), ...(s.rules?.suggestions || [])]
        .find(x => x.source !== 'template' && !x.needs_input && x.text && !HAS_BLANK.test(x.text));
      if (c) out[sid] = { text: c.text.trim(), source: c.source };
    }
    for (const sid of Object.keys(out)) {
      if (out[sid].text === (statementsById[sid].statement.text || '').trim()) delete out[sid];
    }
    return out;
  }, [insights, streamState, statementsById, edits]);
  const pendingCount = Object.keys(pendingSuggestions).length;
  const [lastApplied, setLastApplied] = useState(null);
  const applyAll = () => {
    const ids = Object.keys(pendingSuggestions);
    if (!ids.length) return;
    setEdits(e => ({ ...e, ...pendingSuggestions }));
    setLastApplied(ids);
    setDraft(null);
  };
  const undoApplyAll = () => {
    if (!lastApplied) return;
    setEdits(e => { const n = { ...e }; for (const sid of lastApplied) delete n[sid]; return n; });
    setLastApplied(null);
  };
  const findProjects = async (requirement) => {
    setTab('strategy');
    try { setProjects(await getProjectRecommendations([requirement])); } catch (e) { setError(e.message); }
  };

  const handleExport = async (fmt) => {
    setExporting(fmt); setError(null);
    try {
      const data = applyEdits(resumeData, statementsById, edits, entriesById);
      const name = `${(data.contact?.name || 'Resume').replace(/[^\w-]/g, '_')}_edited`;
      if (fmt === 'layout') {
        await exportOriginalPdf(resumeId, layoutEdits, name);
      } else {
        const fn = { docx: exportResumeDocx, latex: exportResumeLatex, pdf: exportResumePdf, txt: exportResumeTxt }[fmt];
        await fn(data, name);
      }
    } catch (e) { setError(e.message); }
    finally { setExporting(null); }
  };

  // ── editing in the original layout ──
  useEffect(() => {
    if (!renderable) return undefined;
    let alive = true;
    getEditorUnits(resumeId).then(r => { if (alive) setUnits(r.units || []); }).catch(() => {});
    return () => { alive = false; };
  }, [resumeId, renderable]);

  const { unitById, unitsByPage, statementUnits } = useMemo(() => {
    const byId = {}, byPage = {}, bySid = {};
    for (const u of units) {
      byId[u.id] = u;
      (byPage[u.page] ||= []).push(u);
      const sid = u.line_id ? lineToStatement[u.line_id] : null;
      if (sid) (bySid[sid] ||= []).push(u.id);
    }
    // A bullet is edited as one paragraph only when its page text IS the statement. If the line also
    // carries a label (e.g. "OBJECTIVE: ..."), its pieces are edited individually so the label survives.
    const norm = t => (t || '').replace(/\s+/g, ' ').trim();
    for (const [sid, ids] of Object.entries(bySid)) {
      if (norm(ids.map(i => byId[i].text).join(' ')) !== norm(statementsById[sid]?.statement.text)) delete bySid[sid];
    }
    return { unitById: byId, unitsByPage: byPage, statementUnits: bySid };
  }, [units, lineToStatement, statementsById]);

  // Everything that can be typeset into the PDF: accepted bullet edits and free edits of any other text.
  const layoutEdits = useMemo(() => {
    const out = [];
    for (const [sid, e] of Object.entries(edits)) {
      if (statementUnits[sid]) out.push({ key: sid, unit_ids: statementUnits[sid], text: e.text });
    }
    for (const [uid, text] of Object.entries(unitEdits)) out.push({ key: uid, unit_ids: [uid], text });
    return out;
  }, [edits, unitEdits, statementUnits]);

  // Edits that exist but cannot be placed on the original pages.
  const unplaced = useMemo(() => Object.entries(edits)
    .filter(([sid]) => renderable && !statementUnits[sid])
    .map(([sid, e]) => ({ key: sid, text: e.text, reason: sid.startsWith('add:')
      ? 'A new bullet cannot be inserted into the original PDF layout. It is included in the Word, LaTeX and text exports.'
      : 'This text could not be matched to one place on the page. It is included in the Word, LaTeX and text exports.' })),
  [edits, statementUnits, renderable]);

  // Re-render the affected pages with the edits set in the original fonts and positions.
  useEffect(() => {
    if (!renderable) return undefined;
    if (!layoutEdits.length) { setPageImages({}); setFit({}); return undefined; }
    const ac = new AbortController();
    const t = setTimeout(() => {
      previewLayout(resumeId, layoutEdits, { signal: ac.signal })
        .then(r => { setPageImages(r.pages || {}); setFit(Object.fromEntries((r.results || []).map(x => [x.key, x]))); })
        .catch(e => { if (e.name !== 'AbortError') setError(e.message); });
    }, 200);
    return () => { clearTimeout(t); ac.abort(); };
  }, [resumeId, renderable, layoutEdits]);

  const startInline = (u) => {
    const sid = u.line_id ? lineToStatement[u.line_id] : null;
    inlineDone.current = false;
    if (sid && statementUnits[sid]) {
      const us = statementUnits[sid].map(i => unitById[i]);
      const rect = [Math.min(...us.map(x => x.bbox[0])), Math.min(...us.map(x => x.bbox[1])),
        Math.max(...us.map(x => x.bbox[2])), Math.max(...us.map(x => x.bbox[3]))];
      setInline({ sid, page: u.page, rect, lines: us.length, size: u.size, font: u.font, flags: u.flags, text: currentText(sid) });
    } else {
      setInline({ unitId: u.id, page: u.page, rect: u.bbox, lines: 1, size: u.size, font: u.font, flags: u.flags, text: unitEdits[u.id] ?? u.text });
    }
  };
  const commitInline = (text) => {
    if (inlineDone.current || !inline) return;
    inlineDone.current = true;
    const value = text.replace(/\s+/g, ' ').trim();
    if (inline.sid) {
      if (value) onEditText(inline.sid, value);
    } else {
      const original = unitById[inline.unitId]?.text || '';
      setUnitEdits(m => {
        const n = { ...m };
        if (value === original.trim()) delete n[inline.unitId]; else n[inline.unitId] = value;
        return n;
      });
    }
    setInline(null);
  };
  const cancelInline = () => { inlineDone.current = true; setInline(null); };
  const undoUnit = (uid) => setUnitEdits(m => { const n = { ...m }; delete n[uid]; return n; });

  // Report the edited resume to the shell, so the dashboard's Export includes accepted edits.
  useEffect(() => {
    const any = Object.keys(edits).length || Object.keys(unitEdits).length;
    onEditsChange?.(any ? { data: applyEdits(resumeData, statementsById, edits, entriesById), layout: layoutEdits } : null);
  }, [edits, unitEdits, layoutEdits]); // eslint-disable-line react-hooks/exhaustive-deps

  // ── overlays per page ──
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
  const editCount = Object.keys(edits).length + Object.keys(unitEdits).length;
  const notPlaced = [...unplaced, ...Object.values(fit).filter(r => !r.ok).map(r => ({ key: r.key, reason: r.reason,
    text: edits[r.key]?.text ?? unitEdits[r.key] ?? '' }))];
  const selRef = sel?.statementId ? statementsById[sel.statementId] : null;

  const selFindings = useMemo(() => {
    if (!sel) return [];
    const seen = new Set(), out = [];
    const add = (f) => { if (f && !seen.has(f.id)) { seen.add(f.id); out.push(f); } };
    if (sel.findingId) add(insights.find(x => x.id === sel.findingId));
    for (const lid of sel.lineIds || []) (findingsByLine[lid] || []).forEach(add);
    return out;
  }, [sel, findingsByLine, insights]);

  // ── side panel pieces ──
  const renderSuggestionList = (sid, base) => {
    const s = streamState[sid];
    if (!s) return null;
    const rules = s.rules?.suggestions || [];
    const list = [...rules.filter(x => x.source !== 'template'), ...s.llm, ...rules.filter(x => x.source === 'template')];
    const typing = Object.entries(s.partial || {});
    return (
      <div className="ed-suggs" aria-live="polite">
        {s.rules?.question && <p className="ed-q">{s.rules.question}</p>}
        {list.map((c, i) => (
          <div key={`${c.source}-${i}`} className="ed-sugg rx-in">
            <div className="ed-sugg-src">{c.source === 'llm' && s.model ? `${s.model} · fact-checked` : SOURCE_LABEL[c.source] || c.source}</div>
            <p className="ed-text">{c.needs_input ? c.text : <Diff from={base} to={c.text} />}</p>
            {c.warnings?.map((w, j) => <p key={j} className="ed-warn">{w}</p>)}
            <div className="ed-row">
              <span className="ed-muted">{c.why}</span>
              <button className="btn btn-secondary btn-sm" onClick={() => accept(sid, c.text, c.source)}>
                {c.needs_input ? 'Fill in' : 'Accept'}
              </button>
            </div>
          </div>
        ))}
        {typing.map(([angle, text]) => (
          <div key={angle} className="ed-sugg is-typing">
            <div className="ed-sugg-src">{s.model || 'Local model'} · writing ({angle})</div>
            <p className="ed-text">{text}<span className="rx-caret" /></p>
          </div>
        ))}
        {s.status === 'loading' && <p className="ed-muted">Finding fixes…</p>}
        {s.llmState === 'offline' && <p className="ed-muted">Ollama is not running, so these are rule-based fixes only. Start Ollama for model rewrites.</p>}
        {s.llmState === 'error' && <p className="ed-muted">{s.model || 'The model'} stopped: {s.error}</p>}
        {s.status === 'done' && list.length === 0 && (
          <p className="ed-muted">No safe rewrite is possible from what's written. Add a real fact below.</p>
        )}
        {s.rejected?.length > 0 && (
          <details className="ed-rejected">
            <summary>{s.rejected.length} suggestion{s.rejected.length > 1 ? 's' : ''} blocked by the fact-checker</summary>
            {s.rejected.map((r, i) => (
              <div key={i}><p className="ed-strike">{r.text}</p><p className="ed-muted">{(r.problems || []).join('; ')}</p></div>
            ))}
          </details>
        )}
        {s.status === 'error' && <p className="ed-error" role="alert">{s.error}</p>}
      </div>
    );
  };

  const renderStatementCard = () => {
    if (!selRef) return null;
    const sid = sel.statementId;
    const st = selRef.statement;
    const g = gradeById[sid];
    const edited = edits[sid];
    const facts = factsBySid[sid] || '';
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
              <button className="ed-link" onClick={() => loadSuggestions(sid, { immediate: true })}>Improve again</button>
            </div>
          </>
        ) : <p className="ed-text">{st.text}</p>}
        {alignBySid[sid] && (
          <p className="ed-norm">Aligning to: {alignBySid[sid]} <button className="ed-link" onClick={() => setAlignBySid(m => { const n = { ...m }; delete n[sid]; return n; })}>clear</button></p>
        )}
        {(streamState[sid]?.rules?.reasons || g?.reasons || []).length > 0 && (
          <ul className="ed-reasons">{(streamState[sid]?.rules?.reasons || g.reasons).map((r, i) => <li key={i}>{r}</li>)}</ul>
        )}
        {renderSuggestionList(sid, currentText(sid))}
        <div className="ed-facts">
          <label htmlFor={`ed-facts-${sid}`}>Give it a real fact to use</label>
          <textarea id={`ed-facts-${sid}`} rows={2} value={facts}
            onChange={e => setFactsBySid(m => ({ ...m, [sid]: e.target.value }))}
            placeholder="e.g. evaluated 3 open-source LLMs on 500 test prompts; cut manual review from 2 days to 3 hours" />
          <button className="btn btn-ghost btn-sm" disabled={!facts.trim()}
            onClick={() => loadSuggestions(sid, { userFacts: facts.trim(), immediate: true })}>Regenerate with this fact</button>
        </div>
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
        ) : (
          <button className="ed-link" onClick={() => setDraft({ sid, text: currentText(sid) })}>Edit manually</button>
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
            <p className="ed-text">{canApply && !isTemplate ? <Diff from={currentText(sel.statementId)} to={f.suggestion} /> : f.suggestion}</p>
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
      <p className="ed-muted ed-intro">{renderable
        ? 'Double-click any text on the page to edit it where it is: your layout, fonts and spacing stay as they are. Click a highlighted line, or an issue below, for suggestions.'
        : 'Click a highlighted line, or an issue below. Box colour shows severity; the bar on a bullet shows its grade.'}</p>
      {insights.map(f => (
        <button key={f.id} className="ed-ov-item" onClick={() => selectFinding(f)}>
          <span className="ed-dot" style={{ background: SEVERITY_COLOR[f.severity] }} />
          <span className="ed-ov-title">{f.title}</span>
          {f.points > 0 && <span className="ed-ov-pts">+{f.points}</span>}
        </button>
      ))}
    </>
  );

  // ── canvases ──
  const pageView = (
    <div className="ed-pages">
      {pageSizes.map(([w, h], p) => (
        <div key={p} className="ed-page" style={{ aspectRatio: `${w} / ${h}` }}>
          <img src={pageImages[p] || pageImageUrl(resumeId, p)} alt={`Resume page ${p + 1}`} draggable={false} />
          {layers.gaze && (heatByPage[p] || []).map(hm => {
            const [hx0, hy0, hx1, hy1] = hm.bbox;
            return <div key={`heat-${hm.line_id}`} className="ed-heat" aria-hidden="true" style={{
              left: `${(hx0 / w) * 100}%`, top: `${((hy0 - 2) / h) * 100}%`, width: `${((hx1 - hx0) / w) * 100}%`,
              height: `${((hy1 - hy0 + 4) / h) * 100}%`, '--heat': (hm.weight * 0.55).toFixed(3), '--hot': hm.hot_fraction }} />;
          })}
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
          {/* Every run of text is editable in place: click selects its line, double-click opens a text box on it. */}
          {(unitsByPage[p] || []).map(u => {
            const [x0, y0, x1, y1] = u.bbox;
            const flagged = (findingsByLine[u.line_id] || []).map(f => f.title).join('\n');
            return (
              <button key={u.id} type="button" className="ed-unit" data-edited={unitEdits[u.id] !== undefined ? 'y' : 'n'}
                style={{ left: `${(x0 / w) * 100}%`, top: `${((y0 - 1) / h) * 100}%`, width: `${((x1 - x0) / w) * 100}%`, height: `${((y1 - y0 + 2) / h) * 100}%` }}
                title={`${flagged ? `${flagged}\n` : ''}Double-click to edit`} aria-label={`Edit: ${u.text.slice(0, 60)}`}
                onClick={() => u.line_id && selectLine(u.line_id)} onDoubleClick={() => startInline(u)}
                onKeyDown={e => { if (e.key === 'Enter' || e.key === 'F2') { e.preventDefault(); startInline(u); } }} />
            );
          })}
          {inline?.page === p && (() => {
            const [x0, y0, x1, y1] = inline.rect;
            const boxW = inline.sid ? x1 - x0 + 6 : Math.max(x1 - x0 + 40, 150);
            const left = Math.max(2, Math.min(x0 - 2, w - boxW - 4));
            const lineH = (y1 - y0) / inline.lines;
            const serif = /times|serif|georgia|garamond|cambria|roman|book|minion|palatino/i.test(inline.font);
            return (
              <textarea className="ed-inline" autoFocus defaultValue={inline.text} spellCheck aria-label="Edit text in place"
                style={{
                  left: `${(left / w) * 100}%`, top: `${((y0 - 2) / h) * 100}%`, width: `${(boxW / w) * 100}%`,
                  height: `${((lineH * (inline.lines + (inline.sid ? 1 : 0)) + 4) / h) * 100}%`,
                  fontSize: `calc(${inline.size} / ${w} * 100cqw)`,
                  fontFamily: serif ? "'Times New Roman', Times, serif" : 'Arial, Helvetica, sans-serif',
                  fontWeight: (inline.flags & 16) || /bold/i.test(inline.font) ? 700 : 400,
                  fontStyle: (inline.flags & 2) || /italic|oblique/i.test(inline.font) ? 'italic' : 'normal',
                }}
                onFocus={e => e.target.select()}
                onBlur={e => commitInline(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commitInline(e.target.value); }
                  else if (e.key === 'Escape') { e.stopPropagation(); cancelInline(); }
                }} />
            );
          })()}
        </div>
      ))}
    </div>
  );

  const textView = (
    <ResumeTextCanvas resumeData={resumeData} sections={sections} edits={edits} grades={gradeById}
      severityBySid={layers.issues ? severityBySid : {}} showGrades={layers.grades}
      selectedSid={sel?.statementId || null} onSelect={selectStatement} onEditText={onEditText} />
  );

  return (
    <div className="ed-root">
      <div className="ed-toolbar">
        <button className="btn btn-ghost btn-sm" onClick={onBack}>Dashboard</button>
        {onNew && <button className="btn btn-ghost btn-sm" onClick={onNew}>New resume</button>}
        {renderable && <span className="ed-muted">Your PDF · double-click text to edit</span>}
        <label className="ed-toggle"><input type="checkbox" checked={layers.issues} onChange={e => setLayers(l => ({ ...l, issues: e.target.checked }))} /> Issues</label>
        <label className="ed-toggle"><input type="checkbox" checked={layers.grades} onChange={e => setLayers(l => ({ ...l, grades: e.target.checked }))} /> Bullet grades</label>
        <label className="ed-toggle" title={attention?.disclosure}>
          <input type="checkbox" checked={layers.gaze} disabled={!attention?.lines?.length}
            onChange={e => setLayers(l => ({ ...l, gaze: e.target.checked }))} /> Simulated skim
        </label>
        <div className="ed-legend" aria-hidden="true">
          {['A', 'B', 'C', 'D'].map(g => <span key={g}><i style={{ background: GRADE_COLOR[g] }} />{g}</span>)}
        </div>
        <div className="ed-spacer" />
        <span className="ed-muted">{editCount} change{editCount === 1 ? '' : 's'}</span>
        {lastApplied ? (
          <button className="btn btn-ghost btn-sm" onClick={undoApplyAll}>Undo apply all ({lastApplied.length})</button>
        ) : null}
        <button className="btn btn-primary btn-sm" disabled={!pendingCount} onClick={applyAll}
          title={renderable
            ? 'Accept every ready suggestion. Text is replaced in place on your PDF; the template, fonts and spacing are kept.'
            : 'Accept every ready suggestion.'}>
          Apply all suggestions{pendingCount ? ` (${pendingCount})` : ''}
        </button>
        {renderable && (
          <button className="btn btn-primary btn-sm" disabled={!!exporting} onClick={() => handleExport('layout')}
            title="Your original PDF with the edits set in place: same template, fonts and spacing">
            {exporting === 'layout' ? 'Exporting…' : 'Export PDF (your layout)'}
          </button>
        )}
        {(renderable ? ['docx', 'latex', 'txt'] : ['pdf', 'docx', 'latex', 'txt']).map(f => (
          <button key={f} className="btn btn-secondary btn-sm" disabled={!!exporting} onClick={() => handleExport(f)}
            title="Re-typeset into ResumeX's standard template">
            {exporting === f ? '…' : f === 'latex' ? '.tex' : `.${f}`}
          </button>
        ))}
      </div>
      {error && <div className="ed-error" role="alert">{error}</div>}
      {!renderable && <div className="ed-note">Editing in the original layout is available for PDF uploads; this file is shown as editable text.</div>}
      {notPlaced.length > 0 && (
        <div className="ed-note ed-unplaced" role="status">
          <strong>{notPlaced.length} change{notPlaced.length === 1 ? '' : 's'} not placed on the page</strong>
          <ul>{notPlaced.map(n => <li key={n.key}><q>{n.text.slice(0, 90)}{n.text.length > 90 ? '…' : ''}</q> {n.reason}</li>)}</ul>
        </div>
      )}

      <div className="ed-body">
        <div className="ed-canvas">{view === 'page' ? pageView : textView}</div>
        <aside className="ed-side" aria-label="Suggestions">
          <SidebarTabs tab={tab} onTab={setTab} hasJD={!!jdId}
            counts={{ fix: insights.length, jd: sidebar?.jd?.missing, strategy: sidebar?.strategy?.length }} />
          {tab === 'fix' && (sel ? (
            <>
              <button className="ed-link" onClick={() => select(null)}>All issues</button>
              {renderStatementCard()}
              {!selRef && sel.lineIds?.length > 0 && (
                <div className="ed-card"><p className="ed-text">{sel.lineIds.map(l => lineById[l]?.text).filter(Boolean).join(' ')}</p></div>
              )}
              {selFindings.length > 0 && <h4 className="ed-side-h">Why this was flagged</h4>}
              {selFindings.map(renderFinding)}
              {!selFindings.length && !selRef && <p className="ed-muted">Nothing flagged on this line.</p>}
            </>
          ) : overview)}
          {tab === 'jd' && (
            <JDGapsTab data={sidebar?.jd} error={sidebarError} entries={addableEntries}
              onLocate={locate} onAlign={alignTo} onAddBullet={addBullet} onFindProjects={findProjects} />
          )}
          {tab === 'strategy' && (
            <StrategyTab items={sidebar?.strategy} error={sidebarError} projects={projects} onLocate={locate} />
          )}

          {editCount > 0 && (
            <div className="ed-changes">
              <h4 className="ed-side-h">Accepted changes</h4>
              {Object.entries(edits).map(([sid, e]) => (
                <div key={sid} className="ed-change">
                  {sid.startsWith('add:') ? (
                    <>
                      <span className="ed-muted">New bullet · {entriesById[e.entryId]?.title}</span>
                      <p className="ed-text"><ins>{e.text}</ins></p>
                    </>
                  ) : (
                    <>
                      <button className="ed-link" onClick={() => selectStatement(sid)}>
                        {statementsById[sid]?.entry.title || statementsById[sid]?.section.heading}
                      </button>
                      <p className="ed-text"><Diff from={statementsById[sid]?.statement.text || ''} to={e.text} /></p>
                    </>
                  )}
                  <button className="ed-link" onClick={() => undo(sid)}>Undo</button>
                </div>
              ))}
              {Object.entries(unitEdits).map(([uid, text]) => (
                <div key={uid} className="ed-change">
                  <span className="ed-muted">Text on page {(unitById[uid]?.page ?? 0) + 1}</span>
                  <p className="ed-text"><Diff from={unitById[uid]?.text || ''} to={text} /></p>
                  <button className="ed-link" onClick={() => undoUnit(uid)}>Undo</button>
                </div>
              ))}
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
