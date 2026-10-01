export default function SkillMatchList({ skillMatches }) {
  if (!skillMatches || skillMatches.length === 0) return null;

  const grouped = {
    direct: skillMatches.filter(m => m.match_type === 'direct'),
    related: skillMatches.filter(m => m.match_type === 'related'),
    partial: skillMatches.filter(m => m.match_type === 'partial'),
    missing: skillMatches.filter(m => m.match_type === 'missing'),
  };

  return (
    <div>
      {grouped.direct.length > 0 && (
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-success)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Direct Matches ({grouped.direct.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem' }}>
            {grouped.direct.map((m, i) => (
              <span key={i} className="skill-tag matched" title={m.evidence?.[0]}>
                {m.jd_skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {grouped.related.length > 0 && (
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-info)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            ≈ Related Matches ({grouped.related.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem' }}>
            {grouped.related.map((m, i) => {
              const isSemantic = m.evidence?.some(e => e.startsWith('Semantic similarity'));
              const pct = Math.round(m.confidence * 100);
              return (
                <span
                  key={i}
                  className="skill-tag partial"
                  title={m.evidence?.join('\n') || `Via: ${m.resume_skill}`}
                  style={isSemantic ? { borderColor: 'rgba(85, 107, 47, 0.4)', background: 'rgba(85, 107, 47, 0.08)' } : {}}
                >
                  {m.jd_skill} {m.resume_skill}
                  <span style={{ fontSize: '0.625rem', opacity: 0.7, marginLeft: '0.25rem' }}>
                    {pct}%{isSemantic ? ' ' : ''}
                  </span>
                </span>
              );
            })}
          </div>
        </div>
      )}

      {grouped.partial.length > 0 && (
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-warning)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            ~ Partial Matches ({grouped.partial.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem' }}>
            {grouped.partial.map((m, i) => (
              <span key={i} className="skill-tag partial" title={`Partial: ${m.resume_skill}`}>
                {m.jd_skill}
              </span>
            ))}
          </div>
        </div>
      )}

      {grouped.missing.length > 0 && (
        <div style={{ marginBottom: '1rem' }}>
          <div style={{ fontSize: '0.75rem', fontWeight: 600, color: 'var(--accent-danger)', marginBottom: '0.5rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Missing ({grouped.missing.length})
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.375rem' }}>
            {grouped.missing.map((m, i) => (
              <span key={i} className="skill-tag missing">
                {m.jd_skill}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
