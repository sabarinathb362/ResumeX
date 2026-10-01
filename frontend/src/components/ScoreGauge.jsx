import { useMemo } from 'react';

function getScoreColor(score, max) {
  const pct = (score / max) * 100;
  if (pct >= 80) return { color: 'var(--accent-success)', glow: 'rgba(61, 122, 58, 0.3)', gradient: 'var(--gradient-score-good)' };
  if (pct >= 60) return { color: 'var(--accent-warning)', glow: 'rgba(183, 121, 31, 0.3)', gradient: 'var(--gradient-score-mid)' };
  return { color: 'var(--accent-danger)', glow: 'rgba(180, 35, 24, 0.3)', gradient: 'var(--gradient-score-bad)' };
}

export default function ScoreGauge({ score, maxScore = 100, label, size = 130 }) {
  const { color, glow, gradient } = useMemo(() => getScoreColor(score, maxScore), [score, maxScore]);
  const pct = Math.min((score / maxScore) * 100, 100);
  const radius = (size - 14) / 2;
  const circumference = 2 * Math.PI * radius;
  const offset = circumference - (pct / 100) * circumference;
  const center = size / 2;

  return (
    <div className="score-gauge">
      <div className="ring-container" style={{ width: size, height: size, '--ring-glow': glow }}>
        <svg viewBox={`0 0 ${size} ${size}`}>
          <defs>
            <linearGradient id={`grad-${label}`} x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" style={{ stopColor: color, stopOpacity: 0.8 }} />
              <stop offset="100%" style={{ stopColor: color, stopOpacity: 1 }} />
            </linearGradient>
          </defs>
          <circle className="track" cx={center} cy={center} r={radius} />
          <circle
            className="progress"
            cx={center} cy={center} r={radius}
            stroke={`url(#grad-${label})`}
            strokeDasharray={circumference}
            strokeDashoffset={offset}
            style={{ filter: `drop-shadow(0 0 8px ${glow})` }}
          />
        </svg>
        <div className="value-display">
          <div className="value-number" style={{ color }}>{Math.round(score)}</div>
          <div className="value-max">/ {maxScore}</div>
        </div>
      </div>
      {label && <div className="gauge-label">{label}</div>}
    </div>
  );
}

export function ScoreBar({ label, score, maxScore, showValue = true }) {
  const pct = Math.min((score / maxScore) * 100, 100);
  const { color } = getScoreColor(score, maxScore);

  return (
    <div style={{ marginBottom: '0.75rem' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
        <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>{label}</span>
        {showValue && (
          <span style={{ fontSize: '0.8125rem', fontWeight: 700, color }}>{score}/{maxScore}</span>
        )}
      </div>
      <div className="progress-bar">
        <div className="fill" style={{
          width: `${pct}%`,
          background: `linear-gradient(90deg, ${color}aa, ${color})`,
        }} />
      </div>
    </div>
  );
}
