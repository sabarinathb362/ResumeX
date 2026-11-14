/**
 * ResumeX shell: three stages.
 *   1. Upload     resume + optional JD. Analysing shows the run step by step, with what each step found.
 *   2. Dashboard  three scores, the analysis record (including which model graded what), and one
 *                 detail panel at a time.
 *   3. Workspaces the editor and the mock interview, each full screen. Once opened they stay mounted
 *                 (hidden), so switching back to the dashboard never loses edits or answers.
 *
 * Animation: Motion handles stage, tab and marker transitions; GSAP the dashboard entrance and score
 * count-up; anime.js the analysis run; Lenis page scrolling; three.js the upload backdrop (lazy chunk).
 * All of it is skipped when the user prefers reduced motion.
 */
import { Suspense, lazy, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, MotionConfig, motion } from 'motion/react';
import gsap from 'gsap';
import FileUpload from './components/FileUpload';
import InsightsPanel from './components/InsightsPanel';
import SkillMatrix from './components/SkillMatrix';
import RRIPanel from './components/RRIPanel';
import RecommendationsView from './components/RecommendationsView';
import CompanyIntel from './components/CompanyIntel';
import Ats2Panel from './components/Ats2Panel';
import IntegrityPanel from './components/IntegrityPanel';
import AnalysisProgress from './components/AnalysisProgress';
import ScoreCard, { status } from './components/ScoreCard';
import ThemeToggle from './components/ThemeToggle';
import { useTheme } from './hooks/useTheme';
import { scrollToTop, useSmoothScroll } from './hooks/useSmoothScroll';
import { prefersReducedMotion, stageMotion } from './lib/motion';
import {
  uploadResume, analyzeJD, runAnalysis, researchCompany, checkLLM, runDeepReview, getAnalysis, exportOriginalPdf,
  exportResumeDocx, exportResumeLatex, exportResumePdf, exportResumeTxt,
  getMe, signOut, saveToHistory, getResume, getHistoryJD,
} from './api/client';
import { AuthPage, HistoryPage } from './components/AccountPages';

// Heavy, rarely-first-needed parts load on demand: the editor (Tiptap), the interview, and three.js.
const ResumeEditor = lazy(() => import('./components/ResumeEditor'));
const InterviewArena = lazy(() => import('./components/InterviewArena'));
const BackdropField = lazy(() => import('./components/BackdropField'));

const ACCEPT = ['.pdf', '.docx', '.doc', '.tex', '.typ'];
const MAX_MB = 10;
const plural = (n, word, many = `${word}s`) => `${n} ${n === 1 ? word : many}`;
const listOf = items => (items.length < 3 ? items.join(' and ') : `${items.slice(0, -1).join(', ')} and ${items.at(-1)}`);

/* ── Navbar ────────────────────────────────────────────────────── */

function Navbar({ stage, setStage, hasResults, theme, onToggleTheme, user, onSignOut }) {
  const steps = [['upload', '01', 'Upload'], ['dashboard', '02', 'Dashboard'], ['editor', '03', 'Editor'], ['interview', '04', 'Interview']];
  return (
    <nav className="navbar no-print">
      <div className="container navbar-inner">
        <button type="button" className="navbar-brand" data-link={hasResults ? 'y' : 'n'}
                onClick={() => hasResults && setStage('dashboard')} aria-label="ResumeX">
          <span className="brand-mark" aria-hidden="true">R</span><span>ResumeX</span>
        </button>
        <ol className="stepper" aria-label="Workflow">
          {steps.map(([id, n, label]) => (
            <li key={id}>
              <button aria-current={stage === id ? 'step' : undefined} disabled={id !== 'upload' && !hasResults} onClick={() => setStage(id)}>
                <span>{n}</span>{label}
                {stage === id && <motion.i layoutId="stepper-mark" className="stepper-mark" transition={{ duration: 0.25, ease: [0.2, 0.7, 0.2, 1] }} />}
              </button>
            </li>
          ))}
        </ol>
        <div className="nav-account">
          {user ? (
            <>
              <button className="btn btn-ghost btn-sm" aria-current={stage === 'history' ? 'page' : undefined}
                      onClick={() => setStage('history')}>My resumes</button>
              <button className="btn btn-ghost btn-sm" onClick={onSignOut} title={user.email}>Sign out</button>
            </>
          ) : (
            <button className="btn btn-secondary btn-sm" onClick={() => setStage('login')}>Sign in</button>
          )}
        </div>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
      </div>
    </nav>
  );
}

/* ── Stage 1: upload and the analysis run ──────────────────────── */

function preflight(file) {
  if (!file) return [];
  const ext = '.' + file.name.split('.').pop().toLowerCase();
  const out = [];
  out.push(ACCEPT.includes(ext)
    ? { ok: true, text: `${ext.slice(1).toUpperCase()} file` }
    : { ok: false, text: `${ext} is not supported. Use PDF, DOCX, LaTeX (.tex) or Typst (.typ).` });
  out.push(file.size <= MAX_MB * 1024 * 1024
    ? { ok: true, text: `${(file.size / 1024).toFixed(0)} KB` }
    : { ok: false, text: `Larger than ${MAX_MB} MB.` });
  return out;
}

const STEPS = [
  { id: 'parse', label: 'Read the resume' },
  { id: 'jd', label: 'Read the job description' },
  { id: 'score', label: 'Score against the rubrics' },
  { id: 'review', label: 'Model review' },
];

/** Facts about the parsed resume, for the first step of the run. */
function resumeFacts(file, resume) {
  const d = resume.resume_data || {};
  const sections = d.doc_sections || [];
  const entries = sections.reduce((n, s) => n + (s.entries?.length || 0), 0);
  const bullets = sections.reduce((n, s) => n + (s.entries || []).reduce((m, e) => m + (e.statements?.length || 0), 0), 0);
  const words = (d.raw_text || '').split(/\s+/).filter(Boolean).length;
  const pages = d.page_sizes?.length || d.document_metadata?.page_count || 0;
  const out = [
    [file.name, pages ? plural(pages, 'page') : null, `${words} words extracted`].filter(Boolean).join(' · '),
    sections.length
      ? `${plural(sections.length, 'section')} · ${plural(entries, 'entry', 'entries')} · ${plural(bullets, 'bullet')}`
      : { text: 'No sections recognised. Headings such as "Experience" and "Education" help every parser.', kind: 'warn' },
  ];
  if (words < 120) out.push({ text: 'Very little text could be extracted. If this is a scan, export a text PDF instead.', kind: 'warn' });
  for (const w of resume.warnings || []) out.push({ text: w, kind: 'warn' });
  return { lines: out, bullets };
}

function UploadStage({ onDone }) {
  const [file, setFile] = useState(null);
  const [jdText, setJdText] = useState('');
  const [error, setError] = useState(null);
  const [run, setRun] = useState(null);                 // { steps, progress, startedAt, canSkip }
  const [backdrop, setBackdrop] = useState(false);
  const skipRef = useRef(null);
  const pre = preflight(file);
  const blocked = !file || pre.some(c => !c.ok);
  const busy = !!run;

  // Load the three.js backdrop only after the stage has painted, and never for reduced motion.
  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    const t = setTimeout(() => setBackdrop(true), 400);
    return () => clearTimeout(t);
  }, []);

  async function analyze() {
    setError(null);
    const jd = jdText.trim();
    const steps = STEPS.map(s => ({ ...s, status: 'pending', detail: [] }));
    const push = (progress, canSkip = false) => setRun(r => ({ startedAt: r?.startedAt ?? Date.now(), steps: steps.map(s => ({ ...s })), progress, canSkip }));
    const set = (id, patch) => Object.assign(steps.find(s => s.id === id), patch);

    try {
      // 1. parse
      set('parse', { status: 'active', detail: [{ text: `Extracting text and layout from ${file.name}`, kind: 'note' }] });
      push(4);
      const resume = await uploadResume(file);
      const facts = resumeFacts(file, resume);
      set('parse', { status: 'done', detail: facts.lines });
      push(25);

      // 2. job description
      let jdId = null;
      let jdData = null;
      if (jd) {
        set('jd', { status: 'active', detail: [{ text: 'Extracting requirements and skills', kind: 'note' }] });
        push(28);
        const parsed = await analyzeJD(jd, null);
        jdId = parsed.id;
        jdData = parsed.jd_data || {};
        set('jd', {
          status: 'done',
          detail: [
            [jdData.title || 'Role title not found', jdData.company].filter(Boolean).join(' · '),
            `${plural(jdData.requirements?.length || 0, 'requirement')} · ${jdData.required_skills?.length || 0} required and ${jdData.preferred_skills?.length || 0} preferred skills`,
            ...(parsed.warnings || []).map(w => ({ text: w, kind: 'warn' })),
          ],
        });
      } else {
        set('jd', { status: 'skipped', detail: [{ text: 'No job description was provided, so job match is not scored.', kind: 'note' }] });
      }
      push(42);

      // 3. deterministic scoring
      set('score', { status: 'active', detail: [{ text: jd ? 'Running the ATS, readability and job-match rubrics. The first run loads the embedding model and can take about 20 seconds.' : 'Running the ATS and readability rubrics', kind: 'note' }] });
      push(46);
      const analysis = await runAnalysis(resume.id, jdId);
      const { ats_result: ats, readability_result: rri, match_result: match } = analysis;
      const findings = analysis.insights || [];
      const urgent = findings.filter(f => f.severity === 'critical' || f.severity === 'high').length;
      set('score', {
        status: 'done',
        detail: [
          `ATS compatibility ${Math.round(ats.overall_score)} / ${ats.max_possible} · rubric v${ats.rubric_version}`,
          rri && `Recruiter readability ${Math.round(rri.overall_score)} / ${rri.max_possible} · ${plural(rri.statements?.length || 0, 'bullet')} graded · rubric v${rri.rubric_version}`,
          match && `Job match ${Math.round(match.overall_score)} / ${match.max_possible} · ${match.matched_skills?.length || 0} skills matched, ${match.missing_skills?.length || 0} missing`,
          `${plural(findings.length, 'finding')}, ${urgent} high priority`,
        ].filter(Boolean),
      });
      push(66);

      let companyIntel = null;
      if (jd) {
        try { companyIntel = await researchCompany(jd); } catch { /* optional, offline JD analysis */ }
      }
      const base = { resume, analysis, companyIntel, jdText: jd, fileName: file.name };

      // 4. model review (only when Ollama is running)
      const llm = await checkLLM().catch(() => null);
      if (!llm?.online) {
        set('review', { status: 'skipped', detail: [{ text: 'Ollama is not running, so no model reviewed this resume. Scores are rule-based.', kind: 'note' }] });
        push(100);
        await new Promise(r => setTimeout(r, 900));
        onDone({ ...base, review: 'offline' });
        return;
      }
      const model = llm.tiers?.deep?.model || 'local model';
      set('review', { status: 'active', detail: [{ text: `Starting ${model} through Ollama on this machine`, kind: 'note' }] });
      push(68, true);
      const reviewed = runDeepReview(analysis.id, (p, message) => {
        if (message && message !== 'complete' && message !== 'Done') set('review', { detail: [{ text: message, kind: 'note' }] });
        push(68 + Math.round(p * 30), true);
      }).then(() => getAnalysis(analysis.id));
      const skipped = new Promise(resolve => { skipRef.current = () => resolve(null); });
      let final = null;
      try {
        final = await Promise.race([reviewed, skipped]);
      } catch (e) {
        set('review', { status: 'failed', detail: [{ text: `The model review did not finish: ${e.message}. Scores are rule-based.`, kind: 'warn' }] });
        push(100);
        await new Promise(r => setTimeout(r, 1400));
        onDone({ ...base, review: 'failed' });
        return;
      }
      if (final === null) {                              // the user chose not to wait
        onDone({ ...base, review: 'pending', pendingReview: reviewed });
        return;
      }
      const v = final.versions || {};
      const models = v.llm_models || {};
      const before = Math.round(rri?.overall_score ?? 0);
      const after = Math.round(final.readability_result?.overall_score ?? before);
      set('review', {
        status: 'done',
        detail: Object.keys(models).length ? [
          models.bullet_grades && `${models.bullet_grades} graded ${plural(v.llm_graded_bullets ?? 0, 'bullet')} and ran the skim test`,
          models.requirement_judge && `${models.requirement_judge} judged ${plural(jdData?.requirements?.length || 0, 'job requirement')}`,
          before === after ? `Readability unchanged at ${after}` : `Readability ${before} → ${after} after the model's votes`,
        ].filter(Boolean) : [{ text: 'The model returned no usable output, so scores are rule-based.', kind: 'warn' }],
      });
      push(100);
      await new Promise(r => setTimeout(r, 1100));
      onDone({ ...base, analysis: final, review: 'done' });
    } catch (e) {
      setError(e.message);
      setRun(null);
    }
  }

  return (
    <div className="container page">
      <div className="upload-stage">
        {backdrop && !busy && <Suspense fallback={null}><BackdropField /></Suspense>}
        <header className="stage-head">
          <span className="eyebrow">Resume analysis</span>
          <h1>Check a resume before a recruiter does.</h1>
          <p className="lead">ATS compatibility, a simulated recruiter skim and, with a job description, a requirement-by-requirement match. Everything runs on this machine.</p>
        </header>

        <AnimatePresence mode="wait" initial={false}>
          {run ? (
            <motion.div key="run" {...stageMotion}>
              <AnalysisProgress steps={run.steps} progress={run.progress} startedAt={run.startedAt}
                                onSkip={run.canSkip ? () => skipRef.current?.() : null} skipLabel="Show results now; the review will finish in the background" />
            </motion.div>
          ) : (
            <motion.div key="form" {...stageMotion} style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
              <div className="upload-grid">
                <div>
                  <div className="field-label">Resume</div>
                  <FileUpload onFileSelect={setFile} accept={ACCEPT.join(',')} label="Drop a resume here, or click to choose"
                              subtitle={`PDF, DOCX, LaTeX or Typst, up to ${MAX_MB} MB`} />
                  {pre.length > 0 && (
                    <ul className="file-check" aria-label="File check">
                      {pre.map((c, i) => <li key={i} data-ok={c.ok ? 'y' : 'n'}>{c.text}</li>)}
                    </ul>
                  )}
                </div>
                <label className="jd-box">
                  <span className="field-label">Job description <small>optional</small></span>
                  <textarea className="textarea" value={jdText} onChange={e => setJdText(e.target.value)}
                            placeholder="Paste the job description to see matched and missing requirements." />
                </label>
              </div>
              {error && <p className="ed-error" role="alert">{error}</p>}
              <div className="stage-actions">
                <button className="btn btn-primary btn-lg" onClick={analyze} disabled={blocked}>Analyze resume</button>
                <small>{file ? (blocked ? 'Fix the file issue above to continue.' : 'Ready.') : 'Choose a file to begin.'}</small>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}

/* ── Stage 2: dashboard ────────────────────────────────────────── */

const TASK_LABEL = { bullet_grades: 'bullet grades', skim_test: 'the skim test', requirement_judge: 'the requirement judge' };

/** What produced the numbers on this page: rubrics, the model (by name) and the embedding model. */
function AnalysisRecord({ analysis, review, hasJD }) {
  const v = analysis.versions || {};
  const models = v.llm_models || {};
  const byModel = {};
  for (const [task, model] of Object.entries(models)) (byModel[model] ||= []).push(TASK_LABEL[task] || task);
  const names = Object.keys(byModel);

  let modelLine;
  if (names.length) {
    modelLine = (
      <dd>
        {names.map((m, i) => (
          <span key={m}>{i > 0 && '; '}<code>{m}</code> for {listOf(byModel[m])}</span>
        ))}
        {v.llm_graded_bullets != null && ` (${plural(v.llm_graded_bullets, 'bullet')} graded)`}. Run through Ollama on this machine; the model votes on labels and the rubric computes the score.
      </dd>
    );
  } else if (review === 'pending') {
    modelLine = <dd data-state="off">In progress. The scores below are rule-based until the model review finishes.</dd>;
  } else if (review === 'failed') {
    modelLine = <dd data-state="off">Did not finish. No model contributed; the scores are rule-based.</dd>;
  } else if (v.deep_review) {
    modelLine = <dd data-state="off">Ran, but the model returned no usable output. The scores are rule-based.</dd>;
  } else {
    modelLine = <dd data-state="off">Not run: Ollama was not running. No model contributed; the scores are rule-based.</dd>;
  }

  return (
    <dl className="record" aria-label="Analysis record">
      <dt>Scoring</dt>
      <dd>Deterministic rubrics: ATS v{v.ats_rubric || analysis.ats_result?.rubric_version}, readability v{v.readability_rubric || analysis.readability_result?.rubric_version}. Parser v{v.parser || '1'}.</dd>
      <dt>Model review</dt>
      {modelLine}
      {hasJD && <dt>Job match</dt>}
      {hasJD && (v.embedding_model
        ? <dd>Skill and requirement rules, with semantic similarity from the <code>{v.embedding_model}</code> embedding model.</dd>
        : <dd>Skill and requirement rules with word-overlap similarity (the embedding model was not available).</dd>)}
    </dl>
  );
}

function ExportMenu({ onExport, busy, originalPdf }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="menu" onBlur={e => !e.currentTarget.contains(e.relatedTarget) && setOpen(false)}>
      <button className="btn btn-secondary" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(o => !o)}>
        {busy ? `Exporting ${busy}…` : 'Export'}
      </button>
      {open && (
        <div role="menu" className="menu-pop">
          {[['pdf', originalPdf ? 'PDF, your layout' : 'PDF'], ['docx', 'Word (.docx)'], ['latex', 'LaTeX (.tex)'], ['txt', 'Plain text']].map(([k, l]) => (
            <button key={k} role="menuitem" onClick={() => { setOpen(false); onExport(k); }}>{l}</button>
          ))}
        </div>
      )}
    </div>
  );
}

function Dashboard({ results, analysis, review, onOpen, onExport, exporting, edited, onNew }) {
  const { resume, companyIntel } = results;
  const d = resume.resume_data;
  const ats = analysis.ats_result;
  const rri = analysis.readability_result;
  const match = analysis.match_result;
  const insights = analysis.insights || [];
  const urgent = insights.filter(f => f.severity === 'critical' || f.severity === 'high').length;
  const rootRef = useRef(null);

  const tabs = useMemo(() => [
    ['fixes', `Fixes (${insights.length})`],
    rri && ['readability', 'Readability'],
    match && ['match', 'Job match'],
    ['ats2', 'ATS 2.0'],
    ['integrity', 'Integrity'],
    companyIntel && companyIntel.company_name !== 'Unknown Company' && ['company', 'Company'],
  ].filter(Boolean), [insights.length, rri, match, companyIntel]);
  const [tab, setTab] = useState('fixes');

  // Entrance: one short GSAP stagger over the page's blocks.
  useLayoutEffect(() => {
    if (prefersReducedMotion()) return undefined;
    const ctx = gsap.context(() => {
      gsap.from('[data-enter]', { opacity: 0, y: 10, duration: 0.45, ease: 'power2.out', stagger: 0.07, clearProps: 'opacity,transform' });
    }, rootRef);
    return () => ctx.revert();
  }, []);

  return (
    <div className="container page" ref={rootRef}>
      <header className="dash-head" data-enter>
        <div>
          <span className="eyebrow">Analysis report</span>
          <h1>{d.contact?.name || 'Your resume'}</h1>
          <p className="lead">{results.fileName}{' · '}{urgent ? `${plural(urgent, 'high-priority fix', 'high-priority fixes')}` : 'no high-priority fixes'}
            {edited ? ' · editor changes are included in Export' : ''}</p>
        </div>
        <div className="dash-actions">
          <button className="btn btn-primary" onClick={() => onOpen('editor')}>Open editor</button>
          <button className="btn btn-secondary" onClick={() => onOpen('interview')}>Mock interview</button>
          <ExportMenu onExport={onExport} busy={exporting} originalPdf={resume.file_type === 'pdf'} />
          <button className="btn btn-ghost" onClick={onNew} title="Upload and analyse another resume">Analyse another resume</button>
        </div>
      </header>

      <section className="score-row" aria-label="Scores" data-enter>
        <ScoreCard title="ATS compatibility" score={ats.overall_score} max={ats.max_possible} note="Can a parser read and structure this file" delay={0.15} />
        {rri && <ScoreCard title="Recruiter readability" score={rri.overall_score} max={rri.max_possible} note="How a 7-second skim lands" delay={0.25} />}
        {match
          ? <ScoreCard title="Job match" score={match.overall_score} max={match.max_possible} delay={0.35}
                       note={`${match.matched_skills?.length || 0} skills matched, ${match.missing_skills?.length || 0} missing`} />
          : <div className="score-card empty"><span className="score-title">Job match</span>
              <p>Not scored. Add a job description on the upload step to see matched and missing requirements.</p></div>}
      </section>

      <div data-enter><AnalysisRecord analysis={analysis} review={review} hasJD={!!match} /></div>

      <section className="detail" data-enter>
        <div className="tabbar" role="tablist" aria-label="Details">
          {tabs.map(([id, label]) => (
            <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
              {label}
              {tab === id && <motion.i layoutId="tab-mark" className="tab-mark" transition={{ duration: 0.22, ease: [0.2, 0.7, 0.2, 1] }} />}
            </button>
          ))}
        </div>
        {/* Keyed, so the new panel mounts at once and fades in; no exit animation to wait for. */}
        <motion.div key={tab} role="tabpanel" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0, transition: { duration: 0.22 } }}>
            {tab === 'fixes' && <div className="card"><InsightsPanel insights={insights} onLocate={f => onOpen('editor', f)} /></div>}
            {tab === 'readability' && rri && <RRIPanel readability={rri} onLocate={f => onOpen('editor', f)} />}
            {tab === 'match' && match && (
              <>
                <div className="bento-grid" style={{ marginBottom: '1rem' }}>
                  <div className="card span-6">
                    <div className="card-header"><span className="card-title">Match dimensions</span></div>
                    {match.dimension_scores?.filter(dim => dim.max_score > 0).map((dim, i) => {
                      const pct = Math.round((dim.score / dim.max_score) * 100);
                      return (
                        <div key={i} className="dim-row" data-tone={status(pct)[1]}>
                          <span>{dim.dimension}</span><b>{dim.score}/{dim.max_score}</b>
                          <div className="score-bar"><i style={{ width: `${pct}%` }} /></div>
                        </div>
                      );
                    })}
                  </div>
                  <div className="card span-6">
                    <div className="card-header"><span className="card-title">Skills</span></div>
                    <SkillMatrix skillMatches={match.skill_matches} />
                  </div>
                </div>
                <RecommendationsView resumeId={resume.id} jdId={analysis.jd_id} resumeData={d} matchResult={match}
                                     companyIntel={companyIntel} onOpenEditor={() => onOpen('editor')} />
              </>
            )}
            {tab === 'ats2' && <Ats2Panel resumeId={resume.id} analysisId={analysis.id} resumeData={d} onLocate={f => onOpen('editor', f)} />}
            {tab === 'integrity' && <IntegrityPanel resumeId={resume.id} jdId={analysis.jd_id} />}
          {tab === 'company' && <CompanyIntel intel={companyIntel} />}
        </motion.div>
      </section>

      <p className="disclosure">Scores come from ResumeX's own published rubrics. They are not industry standards and do not predict hiring outcomes.</p>
    </div>
  );
}

/* ── Root ──────────────────────────────────────────────────────── */

export default function App() {
  const { theme, toggle } = useTheme();
  useSmoothScroll();
  const [stage, setStage] = useState('upload');
  const [results, setResults] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [review, setReview] = useState(null);          // done | offline | failed | pending
  const [focus, setFocus] = useState(null);
  const [mounted, setMounted] = useState({ editor: false, interview: false });
  const [edited, setEdited] = useState(null);          // resume data with accepted editor edits applied
  const [exporting, setExporting] = useState(null);
  const [user, setUser] = useState(null);

  useEffect(() => { scrollToTop(); }, [stage]);
  useEffect(() => { getMe().then(setUser); }, []);

  // Signed-in users get every analysis saved to their history (and the one on screen when they sign in).
  useEffect(() => {
    if (user && analysis?.id) saveToHistory(analysis.id).catch(() => {});
  }, [user, analysis?.id]);

  async function handleSignOut() {
    await signOut().catch(() => {});
    setUser(null);
    if (stage === 'history') setStage(results ? 'dashboard' : 'upload');
  }

  async function openFromHistory(item) {
    const [resume, a, jd] = await Promise.all([
      getResume(item.resume_id), getAnalysis(item.analysis_id),
      item.jd_id ? getHistoryJD(item.id).catch(() => ({ jd_text: '' })) : Promise.resolve({ jd_text: '' }),
    ]);
    let companyIntel = null;
    if (jd.jd_text) { try { companyIntel = await researchCompany(jd.jd_text); } catch { /* optional */ } }
    const reviewed = Object.keys(a.versions?.llm_models || {}).length > 0;
    start({ resume, analysis: a, companyIntel, jdText: jd.jd_text, fileName: resume.filename, review: reviewed ? 'done' : 'offline' });
  }

  function open(which, f = null) {
    if (which === 'editor') setFocus(f);
    setMounted(m => ({ ...m, [which]: true }));
    setStage(which);
  }

  function start(data) {
    setResults(data); setAnalysis(data.analysis); setReview(data.review); setEdited(null); setFocus(null);
    setMounted({ editor: false, interview: false });
    setStage('dashboard');
    // The user did not wait for the model review: swap its result in when it lands.
    data.pendingReview
      ?.then(a => { setAnalysis(cur => (cur?.id === a.id ? a : cur)); setReview(r => (r === 'pending' ? 'done' : r)); })
      .catch(() => setReview(r => (r === 'pending' ? 'failed' : r)));
  }

  async function exportAs(fmt) {
    const data = edited?.data || results.resume.resume_data;
    const name = `${(data.contact?.name || 'Resume').replace(/[^\w-]/g, '_')}${edited ? '_edited' : ''}`;
    setExporting(fmt);
    try {
      // A PDF upload is exported as that same PDF with the edits set in place; other formats are re-typeset.
      if (fmt === 'pdf' && results.resume.file_type === 'pdf') await exportOriginalPdf(results.resume.id, edited?.layout || [], name);
      else await { pdf: exportResumePdf, docx: exportResumeDocx, latex: exportResumeLatex, txt: exportResumeTxt }[fmt](data, name);
    } finally { setExporting(null); }
  }

  // Clear the current report and go straight to a fresh upload form.
  function newFile() {
    if (edited && !window.confirm('Start a new resume? Your unsaved editor changes will be lost. Export first if you want to keep them.')) return;
    setResults(null); setAnalysis(null); setReview(null); setEdited(null); setFocus(null);
    setMounted({ editor: false, interview: false });
    setStage('upload');
  }

  const go = s => (s === 'login' || s === 'history') ? setStage(s) : (s === 'upload' || results) && (s === 'upload' || s === 'dashboard' ? setStage(s) : open(s));

  return (
    <MotionConfig reducedMotion="user">
      <div className="app-shell">
        <Navbar stage={stage} setStage={go} hasResults={!!results} theme={theme} onToggleTheme={toggle}
                user={user} onSignOut={handleSignOut} />
        <AnimatePresence mode="wait" initial={false}>
          {stage === 'upload' && (
            <motion.main key="upload" {...stageMotion}><UploadStage onDone={start} /></motion.main>
          )}
          {stage === 'login' && (
            <motion.main key="login" {...stageMotion}>
              <AuthPage onSignedIn={u => { setUser(u); setStage(results ? 'dashboard' : 'history'); }}
                        onSkip={() => setStage(results ? 'dashboard' : 'upload')} />
            </motion.main>
          )}
          {stage === 'history' && user && (
            <motion.main key="history" {...stageMotion}>
              <HistoryPage user={user} onOpen={openFromHistory} onNew={() => setStage('upload')} />
            </motion.main>
          )}
          {stage === 'dashboard' && results && (
            <motion.main key="dashboard" {...stageMotion}>
              <Dashboard results={results} analysis={analysis} review={review} onOpen={open}
                         onExport={exportAs} exporting={exporting} edited={!!edited} onNew={newFile} />
            </motion.main>
          )}
        </AnimatePresence>
        <Suspense fallback={<div className="container page"><p className="ed-muted">Loading…</p></div>}>
          {results && mounted.editor && (
            <div className="workspace" hidden={stage !== 'editor'}>
              <ResumeEditor resumeId={results.resume.id} resumeData={results.resume.resume_data} analysis={analysis}
                            jdId={analysis.jd_id} focus={focus} onBack={() => setStage('dashboard')} onNew={newFile} onEditsChange={setEdited} />
            </div>
          )}
          {results && mounted.interview && (
            <div className="workspace container page" hidden={stage !== 'interview'}>
              <InterviewArena resumeId={results.resume.id} jdId={analysis.jd_id} analysisId={analysis.id}
                              defaultCompany={results.companyIntel?.company_name && results.companyIntel.company_name !== 'Unknown Company'
                                ? results.companyIntel.company_name : ''} />
            </div>
          )}
        </Suspense>
      </div>
    </MotionConfig>
  );
}
