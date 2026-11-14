/**
 * Mock Interview Arena (Phase 4).
 * Three rounds (resume deep-dive, role scenario, behavioral & values), one question at a time.
 * The score is computed on the server from STAR labels; quotes the grader could not find in the
 * answer are shown as unverified, and numbers that are not on the resume are flagged.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { evaluateAnswer, startInterview } from '../api/client';

const PARTS = [['situation', 'Situation'], ['task', 'Task'], ['action', 'Action'], ['result', 'Result']];
const SpeechRec = typeof window !== 'undefined' ? (window.SpeechRecognition || window.webkitSpeechRecognition) : null;

function StarBars({ ev }) {
  return (
    <div className="ia-star">
      {PARTS.map(([k, label]) => {
        const p = ev.parts[k];
        return (
          <div key={k} className="ia-star-row">
            <span className="ia-star-label">{label} <small>×{ev.weights[k]}%</small></span>
            <span className="ia-bar" role="meter" aria-valuemin={0} aria-valuemax={10} aria-valuenow={p.score}
                  aria-label={`${label} ${p.score} of 10`}>
              <i style={{ width: `${p.score * 10}%` }} data-level={p.score >= 8 ? 'hi' : p.score >= 5 ? 'mid' : 'lo'} />
            </span>
            <span className="ia-star-score">{p.score}/10</span>
            {p.quote && <q className="ia-quote">{p.quote}</q>}
            {!p.quote_verified && <span className="ia-flag">The grader quoted words that are not in your answer, so this part is capped at 3.</span>}
          </div>
        );
      })}
    </div>
  );
}

export default function InterviewArena({ resumeId, jdId = null, analysisId = null, defaultCompany = '', defaultRole = '' }) {
  const [company, setCompany] = useState(defaultCompany);
  const [role, setRole] = useState(defaultRole);
  const [session, setSession] = useState(null);
  const [roundIdx, setRoundIdx] = useState(0);
  const [qIdx, setQIdx] = useState(0);
  const [answer, setAnswer] = useState('');
  const [results, setResults] = useState({});       // question id -> evaluation
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);
  const [voiceOk, setVoiceOk] = useState(false);    // user accepted the cloud speech warning
  const [listening, setListening] = useState(false);
  const recRef = useRef(null);

  useEffect(() => () => recRef.current?.abort(), []);

  const round = session?.rounds?.[roundIdx];
  const question = round?.questions?.[qIdx];
  const ev = question ? results[question.id] : null;
  const answered = useMemo(() => Object.values(results), [results]);
  const avg = answered.length ? Math.round(answered.reduce((s, r) => s + r.overall, 0) / answered.length) : null;

  async function begin() {
    setBusy(true); setErr(null);
    try {
      const s = await startInterview({ resumeId, jdId, analysisId, company: company.trim(), role: role.trim() });
      setSession(s); setRoundIdx(0); setQIdx(0); setResults({}); setAnswer('');
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  async function submit() {
    if (!answer.trim() || !question) return;
    setBusy(true); setErr(null);
    try {
      const r = await evaluateAnswer(session.session_id, question.id, answer.trim());
      setResults(prev => ({ ...prev, [question.id]: r }));
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  }

  function next() {
    setAnswer('');
    if (qIdx + 1 < round.questions.length) setQIdx(qIdx + 1);
    else if (roundIdx + 1 < session.rounds.length) { setRoundIdx(roundIdx + 1); setQIdx(0); }
  }

  function toggleVoice() {
    if (!SpeechRec) return;
    if (listening) { recRef.current?.stop(); return; }
    const rec = new SpeechRec();
    rec.lang = 'en-US'; rec.continuous = true; rec.interimResults = false;
    rec.onresult = e => {
      const text = Array.from(e.results).slice(e.resultIndex).map(r => r[0].transcript).join(' ');
      setAnswer(a => (a ? a + ' ' : '') + text.trim());
    };
    rec.onend = () => setListening(false);
    rec.onerror = () => setListening(false);
    recRef.current = rec; rec.start(); setListening(true);
  }

  if (!session) {
    return (
      <div className="card ia-setup">
        <h3>Mock interview</h3>
        <p className="ed-muted">Questions come from your resume, the job description and the company's published values.
          They are practice questions, not questions this company is known to ask.</p>
        <div className="ia-fields">
          <label>Company <input value={company} onChange={e => setCompany(e.target.value)} placeholder="Optional, e.g. Amazon" /></label>
          <label>Role <input value={role} onChange={e => setRole(e.target.value)} placeholder="Optional, e.g. Backend Engineer" /></label>
        </div>
        <button className="btn btn-primary" onClick={begin} disabled={busy}>{busy ? 'Preparing…' : 'Start interview'}</button>
        {err && <p className="ed-error">{err}</p>}
      </div>
    );
  }

  const last = roundIdx === session.rounds.length - 1 && qIdx === round.questions.length - 1;

  return (
    <div className="ia-root">
      <div className="ed-seg" role="tablist" aria-label="Interview rounds">
        {session.rounds.map((r, i) => (
          <button key={r.round} role="tab" aria-selected={i === roundIdx} onClick={() => { setRoundIdx(i); setQIdx(0); setAnswer(''); }}>
            {r.round}. {r.name}
          </button>
        ))}
      </div>
      <span className="ia-avg">{session.question_model ? `Questions written by ${session.question_model} from your resume and the job description.` : 'Questions come from built-in templates filled with your resume and the job description (no model was used).'}</span>
      {avg !== null && <span className="ia-avg">Average so far: {avg}/100 over {answered.length} answer{answered.length > 1 ? 's' : ''}</span>}

      <div className="card ia-q">
        <div className="ia-q-meta">Question {qIdx + 1} of {round.questions.length} · <span>{question.why}</span></div>
        <p className="ia-q-text">{question.text}</p>
        {session.values_source && roundIdx === 2 && (
          <p className="ed-note">Values from <a href={session.values_source} target="_blank" rel="noreferrer">the company's careers page</a>.</p>
        )}

        <textarea className="ia-answer" rows={7} value={answer} onChange={e => setAnswer(e.target.value)}
                  placeholder="Answer as you would out loud: the situation, your task, what you did, and the result." />
        <div className="ia-actions">
          {SpeechRec && !voiceOk && (
            <button className="btn btn-ghost" onClick={() => setVoiceOk(window.confirm(
              'Voice input uses your browser\'s speech service. In Chrome and Edge the audio is sent to the browser vendor\'s servers. Continue?'))}>
              Enable voice
            </button>
          )}
          {SpeechRec && voiceOk && (
            <button className="btn btn-ghost" onClick={toggleVoice} aria-pressed={listening}>{listening ? 'Stop' : 'Dictate'}</button>
          )}
          <span className="ed-spacer" />
          <button className="btn btn-primary" onClick={submit} disabled={busy || !answer.trim()}>{busy ? 'Grading…' : 'Grade answer'}</button>
          {ev && !last && <button className="btn" onClick={next}>Next question</button>}
        </div>
        {err && <p className="ed-error">{err}</p>}
      </div>

      {ev && (
        <div className="card ia-result">
          <div className="ia-score"><b>{Math.round(ev.overall)}</b>/100 <small>{ev.method === 'llm' ? `graded by ${ev.model || 'the local model'}` : 'rule-based check (no model was used)'}</small></div>
          <StarBars ev={ev} />
          {ev.tip && <p className="ia-tip"><b>Biggest improvement:</b> {ev.tip}</p>}
          {ev.numbers_not_on_resume.length > 0 && (
            <p className="ia-flag">You said {ev.numbers_not_on_resume.join(', ')}, which is not on your resume.
              An interviewer may ask you to back it up, and it could be worth adding to the resume if it is true.</p>
          )}
          {ev.stronger_answer && (
            <details className="ia-stronger"><summary>A tighter version, using only what you said</summary>
              <p>{ev.stronger_answer}</p>
              <small>Words in [brackets] are facts you still need to supply.</small>
            </details>
          )}
        </div>
      )}
    </div>
  );
}
