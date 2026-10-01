/**
 * CompanyIntel — Displays real-time company intelligence from JD analysis.
 * Shows company overview, tech stack, culture signals, and resume optimization tips.
 */
export default function CompanyIntel({ intel }) {
  if (!intel) return null;

  return (
    <div className="company-panel">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '1rem', position: 'relative', zIndex: 1 }}>
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
            <span style={{ fontSize: '1.25rem' }}></span>
            <div className="company-name">{intel.company_name}</div>
            <span className="badge badge-glow" style={{ fontSize: '0.625rem' }}>
              {intel.confidence === 'high' ? 'Verified' : intel.confidence === 'medium' ? 'Analyzed' : 'Inferred'}
            </span>
          </div>
          {intel.description && (
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', maxWidth: '600px', lineHeight: 1.5 }}>
              {intel.description.slice(0, 200)}{intel.description.length > 200 ? '...' : ''}
            </p>
          )}
        </div>
      </div>

      {/* Meta chips */}
      <div className="company-meta" style={{ position: 'relative', zIndex: 1 }}>
        {intel.industry && (
          <span className="meta-chip">{intel.industry}</span>
        )}
        {intel.company_size && (
          <span className="meta-chip">{intel.company_size}</span>
        )}
        {intel.headquarters && (
          <span className="meta-chip">{intel.headquarters}</span>
        )}
        {intel.founded && (
          <span className="meta-chip">Founded {intel.founded}</span>
        )}
      </div>

      <div className="grid-3" style={{ gap: '1rem', position: 'relative', zIndex: 1 }}>
        {/* Tech Stack from JD */}
        {intel.tech_stack?.length > 0 && (
          <div style={{
            background: 'rgba(31, 36, 24, 0.03)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            border: '1px solid var(--border-subtle)',
          }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
              Tech Stack Detected
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.3rem' }}>
              {intel.tech_stack.map((tech, i) => (
                <span key={i} className="skill-tag matched" style={{ fontSize: '0.6875rem', padding: '0.2rem 0.5rem' }}>
                  {tech}
                </span>
              ))}
            </div>
          </div>
        )}

        {/* Culture Signals */}
        {intel.culture_signals?.length > 0 && (
          <div style={{
            background: 'rgba(31, 36, 24, 0.03)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            border: '1px solid var(--border-subtle)',
          }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
              Culture Signals
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
              {intel.culture_signals.map((signal, i) => (
                <div key={i} style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
                  <span style={{ color: 'var(--accent-cyan)', fontSize: '0.5rem' }}>●</span>
                  {signal}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Hiring Insights */}
        {intel.hiring_insights?.length > 0 && (
          <div style={{
            background: 'rgba(31, 36, 24, 0.03)',
            borderRadius: 'var(--radius-md)',
            padding: '1rem',
            border: '1px solid var(--border-subtle)',
          }}>
            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.625rem' }}>
              Hiring Signals
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
              {intel.hiring_insights.map((insight, i) => (
                <div key={i} style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', display: 'flex', alignItems: 'flex-start', gap: '0.375rem' }}>
                  <span style={{ color: 'var(--accent-info)', fontSize: '0.5rem', marginTop: '0.375rem' }}>●</span>
                  {insight}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Resume Tips */}
      {intel.resume_tips?.length > 0 && (
        <div style={{ marginTop: '1rem', position: 'relative', zIndex: 1 }}>
          <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: '0.5rem' }}>
            Company-Specific Resume Tips
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
            {intel.resume_tips.map((tip, i) => (
              <div key={i} style={{
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.5rem',
                padding: '0.5rem 0.75rem',
                background: 'rgba(61, 122, 58, 0.04)',
                border: '1px solid rgba(61, 122, 58, 0.12)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.8125rem',
                color: 'var(--text-primary)',
                lineHeight: 1.5,
              }}>
                <span style={{ color: 'var(--accent-success)', fontWeight: 700 }}>→</span>
                {tip}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
