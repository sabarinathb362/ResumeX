import { useState } from 'react';

export default function ReadabilitySection({ readabilityResult }) {
  const [selectedDimension, setSelectedDimension] = useState(0);

  if (!readabilityResult) return null;

  const { overall_score, max_possible, rri_percentage, dimensions, rubric_version, disclosure } = readabilityResult;
  const currentDim = dimensions?.[selectedDimension] || dimensions?.[0];

  const getDimensionIcon = (name) => {
    switch (name) {
      case 'Bullet Quality': return '';
      case 'Quantification': return '';
      case 'Sentence Complexity': return '';
      case 'Section Balance': return '';
      case 'Formatting Consistency': return '';
      case 'Scannability': return '';
      default: return '';
    }
  };

  return (
    <div className="card">
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1.25rem' }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <span style={{ fontSize: '1.125rem' }}></span>
            <h3 style={{ margin: 0, fontSize: '1.0625rem' }}>Resume Readability Index</h3>
            <span className="badge badge-neutral">v{rubric_version || '1.0'}</span>
          </div>
          <p style={{ margin: 0, fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            Scannability, bullet impact, and writing clarity analysis.
          </p>
        </div>
        <div style={{ textAlign: 'right' }}>
          <span style={{
            fontSize: '1.5rem',
            fontWeight: 800,
            color: rri_percentage >= 80 ? 'var(--accent-success)' : rri_percentage >= 60 ? 'var(--accent-warning)' : 'var(--accent-danger)',
          }}>
            {Math.round(overall_score)}
          </span>
          <span style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>/{max_possible}</span>
          <div style={{ fontSize: '0.6875rem', color: 'var(--text-secondary)' }}>
            {rri_percentage}% scannable
          </div>
        </div>
      </div>

      {/* Dimension Grid */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
        gap: '0.5rem',
        marginBottom: '1.25rem',
      }}>
        {dimensions?.map((dim, idx) => {
          const isSelected = idx === selectedDimension;
          const pct = Math.round((dim.score / dim.max_score) * 100);
          const color = pct >= 80 ? 'var(--accent-success)' : pct >= 60 ? 'var(--accent-warning)' : 'var(--accent-danger)';

          return (
            <div
              key={dim.dimension}
              onClick={() => setSelectedDimension(idx)}
              style={{
                padding: '0.75rem',
                borderRadius: 'var(--radius-md)',
                background: isSelected ? 'rgba(85, 107, 47, 0.08)' : 'var(--bg-surface)',
                border: isSelected ? '1px solid var(--accent-primary)' : '1px solid var(--border-subtle)',
                cursor: 'pointer',
                transition: 'all var(--transition-fast)',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.375rem' }}>
                <span style={{ fontSize: '0.875rem' }}>{getDimensionIcon(dim.dimension)}</span>
                <span style={{ fontSize: '0.75rem', fontWeight: 700, color }}>{dim.score}/{dim.max_score}</span>
              </div>
              <div style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                color: isSelected ? 'var(--accent-primary-light)' : 'var(--text-primary)',
                marginBottom: '0.375rem',
              }}>
                {dim.dimension}
              </div>
              <div className="progress-bar" style={{ height: 3 }}>
                <div className="fill" style={{
                  width: `${pct}%`,
                  background: `linear-gradient(90deg, ${color}aa, ${color})`,
                }} />
              </div>
            </div>
          );
        })}
      </div>

      {/* Selected Dimension Detail */}
      {currentDim && (
        <div style={{
          background: 'var(--bg-surface)',
          borderRadius: 'var(--radius-md)',
          padding: '1rem 1.25rem',
          border: '1px solid var(--border-subtle)',
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.75rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>{getDimensionIcon(currentDim.dimension)}</span>
              <h4 style={{ margin: 0, fontSize: '0.9375rem' }}>{currentDim.dimension}</h4>
              {(() => {
                const ratio = currentDim.score / currentDim.max_score;
                if (ratio >= 0.8) return <span className="badge badge-success">Strong</span>;
                if (ratio >= 0.6) return <span className="badge badge-warning">Moderate</span>;
                return <span className="badge badge-danger">Needs Work</span>;
              })()}
            </div>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: 'var(--text-secondary)' }}>
              {currentDim.score}/{currentDim.max_score} pts
            </span>
          </div>

          <div className="grid-2" style={{ gap: '1rem' }}>
            {/* Findings */}
            <div>
              <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.375rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Findings
              </div>
              {currentDim.details?.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.25rem' }}>
                  {currentDim.details.map((detail, dIdx) => (
                    <div key={dIdx} style={{
                      fontSize: '0.8125rem',
                      color: 'var(--text-secondary)',
                      display: 'flex',
                      alignItems: 'flex-start',
                      gap: '0.375rem',
                      lineHeight: 1.5,
                    }}>
                      <span style={{ color: 'var(--accent-info)', fontSize: '0.5rem', marginTop: '0.4rem' }}>●</span>
                      <span>{detail}</span>
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>No specific findings.</div>
              )}
            </div>

            {/* Tips */}
            <div>
              <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', marginBottom: '0.375rem', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                Tips
              </div>
              {currentDim.tips?.length > 0 ? (
                <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
                  {currentDim.tips.map((tip, tIdx) => (
                    <div key={tIdx} style={{
                      background: 'rgba(183, 121, 31, 0.04)',
                      border: '1px solid rgba(183, 121, 31, 0.12)',
                      borderRadius: 'var(--radius-sm)',
                      padding: '0.375rem 0.625rem',
                      fontSize: '0.8125rem',
                      color: 'var(--text-primary)',
                      lineHeight: 1.5,
                    }}>
                      {tip}
                    </div>
                  ))}
                </div>
              ) : (
                <div style={{
                  background: 'rgba(61, 122, 58, 0.04)',
                  border: '1px solid rgba(61, 122, 58, 0.12)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.375rem 0.625rem',
                  fontSize: '0.8125rem',
                  color: 'var(--accent-success)',
                }}>
                  Excellent! No revisions needed.
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Disclosure */}
      {disclosure && (
        <div style={{
          marginTop: '1rem',
          paddingTop: '0.75rem',
          borderTop: '1px solid var(--border-subtle)',
          fontSize: '0.6875rem',
          color: 'var(--text-muted)',
          display: 'flex',
          alignItems: 'center',
          gap: '0.375rem',
        }}>
          <span></span>
          <span>{disclosure}</span>
        </div>
      )}
    </div>
  );
}
