/**
 * The analysis run, shown while a resume is being analysed: one row per pipeline step with what that
 * step actually found (file facts, requirement counts, scores, which model is grading), and a progress
 * bar underneath. anime.js draws each check mark, staggers the detail lines in and eases the bar.
 *
 * steps: [{ id, label, status: 'pending' | 'active' | 'done' | 'skipped' | 'failed', detail: [string | { text, kind }] }]
 */
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { animate, stagger, svg } from 'animejs';
import { prefersReducedMotion } from '../lib/motion';

const STATE = { pending: 'Waiting', active: 'Running', done: 'Done', skipped: 'Skipped', failed: 'Failed' };

function Mark({ status }) {
  if (status === 'active') {
    return (
      <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true">
        <circle cx="9" cy="9" r="7" opacity=".22" />
        <path className="run-spin" d="M9 2a7 7 0 0 1 7 7" strokeLinecap="round" />
      </svg>
    );
  }
  if (status === 'done') {
    return (
      <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path className="run-check" d="M3.5 9.5l3.5 3.5 7.5-8" />
      </svg>
    );
  }
  if (status === 'failed') {
    return (
      <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" aria-hidden="true">
        <path d="M5 5l8 8M13 5l-8 8" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
      {status === 'skipped' ? <path d="M5 9h8" /> : <circle cx="9" cy="9" r="2" fill="currentColor" stroke="none" opacity=".5" />}
    </svg>
  );
}

function Step({ step }) {
  const ref = useRef(null);
  const prev = useRef({ status: step.status, lines: 0 });

  // Animate only what is new: the check when the step completes, and detail lines as they arrive.
  useLayoutEffect(() => {
    const el = ref.current;
    const lines = [...el.querySelectorAll('.run-detail li')];
    const fresh = lines.slice(prev.current.lines);
    const becameDone = step.status === 'done' && prev.current.status !== 'done';
    prev.current = { status: step.status, lines: lines.length };
    if (prefersReducedMotion()) return;
    if (becameDone) {
      const check = el.querySelector('.run-check');
      if (check) animate(svg.createDrawable(check), { draw: ['0 0', '0 1'], duration: 420, ease: 'outQuad' });
    }
    if (fresh.length) {
      animate(fresh, { opacity: [0, 1], translateY: [4, 0], duration: 320, delay: stagger(70), ease: 'outQuad' });
    }
  }, [step.status, step.detail]);

  return (
    <li ref={ref} className="run-step" data-status={step.status}>
      <span className="run-mark"><Mark status={step.status} /></span>
      <span className="run-label">{step.label}</span>
      <span className="run-state">{STATE[step.status]}</span>
      {step.detail?.length > 0 && (
        <ul className="run-detail">
          {step.detail.map((d, i) => {
            const item = typeof d === 'string' ? { text: d } : d;
            return <li key={i} data-kind={item.kind || 'fact'}>{item.text}</li>;
          })}
        </ul>
      )}
    </li>
  );
}

function clock(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

export default function AnalysisProgress({ steps, progress, startedAt, onSkip, skipLabel }) {
  const barRef = useRef(null);
  const [now, setNow] = useState(() => Date.now());
  const active = steps.find(s => s.status === 'active');
  const finished = steps.every(s => s.status !== 'pending' && s.status !== 'active');

  useEffect(() => {
    if (finished) return undefined;
    const t = setInterval(() => setNow(Date.now()), 500);
    return () => clearInterval(t);
  }, [finished]);

  useEffect(() => {
    const bar = barRef.current;
    if (prefersReducedMotion()) { bar.style.width = `${progress}%`; return undefined; }
    const a = animate(bar, { width: `${progress}%`, duration: 700, ease: 'outCubic' });
    return () => a.pause();
  }, [progress]);

  const done = steps.filter(s => s.status === 'done' || s.status === 'skipped' || s.status === 'failed').length;

  return (
    <section className="run" aria-label="Analysis progress">
      <header className="run-head">
        <h2>{finished ? 'Analysis complete' : 'Analysing'}</h2>
        <span>Elapsed {clock(now - startedAt)}</span>
      </header>
      <ol className="run-steps" aria-live="polite">
        {steps.map(s => <Step key={s.id} step={s} />)}
      </ol>
      <div className="run-foot">
        <div className="run-bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(progress)}
             aria-label="Analysis progress"><i ref={barRef} /></div>
        <div className="run-meta">
          <span><b>{Math.round(progress)}%</b> · step {Math.min(done + 1, steps.length)} of {steps.length}{active ? ` · ${active.label}` : ''}</span>
          {onSkip && <button type="button" className="link-btn" onClick={onSkip}>{skipLabel}</button>}
        </div>
      </div>
    </section>
  );
}
