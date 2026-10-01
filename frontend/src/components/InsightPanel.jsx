/**
 * InsightPanel — Redesigned warnings & findings with visual priority markers,
 * impact estimates, and actionable diffs instead of walls of text.
 */
import { useState } from 'react';

export default function InsightPanel({ warnings, matchResult, resumeData }) {
  const [expandedIdx, setExpandedIdx] = useState(null);

  // Sort warnings by severity
  const severityOrder = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
  const sorted = [...(warnings || [])].sort((a, b) => {
    const sa = severityOrder[a.severity] ?? 4;
    const sb = severityOrder[b.severity] ?? 4;
    return sa - sb;
  });

  const critCount = sorted.filter(w => w.severity === 'critical').length;
  const highCount = sorted.filter(w => w.severity === 'high').length;
  const medCount = sorted.filter(w => w.severity === 'medium' || w.severity === 'low' || w.severity === 'info').length;

  const getSeverityConfig = (sev) => {
    switch (sev) {
      case 'critical': return { icon: '', color: 'var(--accent-danger)', label: 'Critical' };
      case 'high': return { icon: '', color: 'var(--accent-warning)', label: 'High' };
      case 'medium': return { icon: '', color: 'var(--accent-info)', label: 'Medium' };
      case 'low': return { icon: '', color: 'var(--text-muted)', label: 'Low' };
      default: return { icon: '', color: 'var(--text-muted)', label: 'Info' };
    }
  };

  // Estimate impact points based on severity
  const getImpactEstimate = (sev) => {
    switch (sev) {
      case 'critical': return '+5-8 pts';
      case 'high': return '+3-5 pts';
      case 'medium': return '+1-3 pts';
      default: return '+1 pt';
    }
  };

  if (!sorted.length) {
    return (
      <div>
        <div className="card-header">
          <span className="card-title">Issues & Findings</span>
        </div>
        <div style={{ textAlign: 'center', padding: '2rem 1rem' }}>
          <span style={{ fontSize: '2rem', display: 'block', marginBottom: '0.5rem' }}></span>
          <div style={{ fontSize: '0.9375rem', fontWeight: 600, color: 'var(--accent-success)' }}>No issues found!</div>
          <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)', marginTop: '0.25rem' }}>Your resume looks great.</div>
        </div>
      </div>
    );
  }

  return (
    <div>
      <div className="card-header">
        <span className="card-title">Priority Issues</span>
        <div style={{ display: 'flex', gap: '0.375rem' }}>
          {critCount > 0 && <span className="badge badge-danger">{critCount} critical</span>}
          {highCount > 0 && <span className="badge badge-warning">{highCount} high</span>}
          {medCount > 0 && <span className="badge badge-neutral">{medCount} other</span>}
        </div>
      </div>

      <div style={{ maxHeight: '420px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
        {sorted.map((warning, i) => {
          const config = getSeverityConfig(warning.severity);
          const isExpanded = expandedIdx === i;
          const msg = warning.message || '';
          const remediation = Array.isArray(warning.remediation)
            ? warning.remediation.join(' ')
            : (warning.remediation || '');

          return (
            <div
              key={i}
              className={`insight-card ${warning.severity || 'medium'}`}
              onClick={() => setExpandedIdx(isExpanded ? null : i)}
              style={{ cursor: 'pointer' }}
            >
              <div className="insight-header">
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1 }}>
                  <span style={{ fontSize: '0.875rem' }}>{config.icon}</span>
                  <span className="insight-title" style={{ fontSize: '0.8125rem' }}>{msg.slice(0, 100)}{msg.length > 100 ? '...' : ''}</span>
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  <span className="insight-impact">{getImpactEstimate(warning.severity)}</span>
                  <span style={{
                    fontSize: '0.75rem',
                    color: 'var(--text-muted)',
                    transform: isExpanded ? 'rotate(180deg)' : 'rotate(0)',
                    transition: 'transform 0.2s',
                  }}>▼</span>
                </div>
              </div>

              {isExpanded && (
                <div style={{ marginTop: '0.5rem', animation: 'fadeIn 0.2s ease-out' }}>
                  {warning.dimension && (
                    <div style={{ fontSize: '0.6875rem', color: 'var(--text-muted)', marginBottom: '0.375rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                      Category: {warning.dimension}
                    </div>
                  )}
                  {msg.length > 100 && (
                    <div className="insight-body" style={{ marginBottom: '0.5rem' }}>{msg}</div>
                  )}
                  {remediation && (
                    <div style={{
                      padding: '0.5rem 0.75rem',
                      background: 'rgba(61, 122, 58, 0.04)',
                      border: '1px solid rgba(61, 122, 58, 0.12)',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.8125rem',
                      color: 'var(--text-primary)',
                      lineHeight: 1.5,
                    }}>
                      <span style={{ fontWeight: 700, color: 'var(--accent-success)' }}>Fix: </span>
                      {remediation}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
