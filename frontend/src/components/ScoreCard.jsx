/**
 * One headline score. GSAP counts the number up and draws the bar on first show, and tweens from
 * the old value to the new one if the score changes later (for example when the model review lands).
 */
import { useLayoutEffect, useRef } from 'react';
import gsap from 'gsap';
import { prefersReducedMotion } from '../lib/motion';

export function status(pct) {
  if (pct >= 80) return ['Strong', 'good'];
  if (pct >= 60) return ['Needs work', 'mid'];
  return ['Weak', 'bad'];
}

export default function ScoreCard({ title, score, max, note, delay = 0 }) {
  const pct = Math.round((score / max) * 100);
  const [label, tone] = status(pct);
  const numRef = useRef(null);
  const barRef = useRef(null);
  const shown = useRef(0);          // the value currently on screen

  useLayoutEffect(() => {
    const num = numRef.current;
    const bar = barRef.current;
    if (prefersReducedMotion()) {
      num.textContent = pct;
      bar.style.width = `${pct}%`;
      shown.current = pct;
      return undefined;
    }
    const first = shown.current === 0;
    const state = { v: shown.current };
    const tween = gsap.to(state, {
      v: pct,
      duration: first ? 0.9 : 0.6,
      delay: first ? delay : 0,
      ease: 'power2.out',
      onUpdate: () => {
        shown.current = state.v;
        num.textContent = Math.round(state.v);
        bar.style.width = `${state.v}%`;
      },
    });
    return () => tween.kill();
  }, [pct, delay]);

  return (
    <div className="score-card" data-tone={tone}>
      <span className="score-title">{title}</span>
      <div className="score-value"><b ref={numRef} aria-label={`${pct} out of 100`}>0</b><span>/ 100</span><em>{label}</em></div>
      <div className="score-bar"><i ref={barRef} style={{ width: 0 }} /></div>
      {note && <small>{note}</small>}
    </div>
  );
}
