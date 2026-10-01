/**
 * SkillMatrix — Visual skill analysis grid replacing the old tag soup.
 * Each skill shows match type, confidence, evidence, and gap action.
 */

export default function SkillMatrix({ skillMatches }) {
  if (!skillMatches || skillMatches.length === 0) return null;

  const grouped = {
    direct: skillMatches.filter(m => m.match_type === 'direct'),
    related: skillMatches.filter(m => m.match_type === 'related'),
    partial: skillMatches.filter(m => m.match_type === 'partial'),
    missing: skillMatches.filter(m => m.match_type === 'missing'),
  };

  const getMatchConfig = (type) => {
    switch (type) {
      case 'direct': return { label: 'Direct Match', color: 'var(--accent-success)', bg: 'var(--accent-success-bg)', icon: '' };
      case 'related': return { label: 'Related', color: 'var(--accent-info)', bg: 'var(--accent-info-bg)', icon: '≈' };
      case 'partial': return { label: 'Partial', color: 'var(--accent-warning)', bg: 'var(--accent-warning-bg)', icon: '~' };
      case 'missing': return { label: 'Missing', color: 'var(--accent-danger)', bg: 'var(--accent-danger-bg)', icon: '' };
      default: return { label: type, color: 'var(--text-muted)', bg: 'transparent', icon: '?' };
    }
  };

  const renderGroup = (items, type) => {
    if (!items.length) return null;
    const config = getMatchConfig(type);

    return (
      <div style={{ marginBottom: '1rem' }}>
        <div style={{
          fontSize: '0.6875rem',
          fontWeight: 700,
          color: config.color,
          marginBottom: '0.5rem',
          textTransform: 'uppercase',
          letterSpacing: '0.06em',
          display: 'flex',
          alignItems: 'center',
          gap: '0.375rem',
        }}>
          <span>{config.icon}</span>
          {config.label} ({items.length})
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
          {items.map((m, i) => {
            const isSemantic = m.evidence?.some(e => e.startsWith('Semantic similarity'));
            const pct = Math.round((m.confidence || 0) * 100);

            return (
              <div key={i} style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                padding: '0.375rem 0.625rem',
                background: config.bg,
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${config.color}15`,
                gap: '0.5rem',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', flex: 1, minWidth: 0 }}>
                  <span style={{
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-heading)',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}>
                    {m.jd_skill}
                  </span>
                  {type === 'related' && m.resume_skill && (
                    <span style={{ fontSize: '0.6875rem', color: 'var(--text-muted)' }}>
                      {m.resume_skill}
                    </span>
                  )}
                </div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', flexShrink: 0 }}>
                  {isSemantic && (
                    <span style={{ fontSize: '0.625rem', color: 'var(--accent-violet)' }}></span>
                  )}
                  {pct > 0 && type !== 'direct' && type !== 'missing' && (
                    <span style={{
                      fontSize: '0.625rem',
                      fontWeight: 600,
                      color: config.color,
                      background: 'rgba(0,0,0,0.2)',
                      padding: '0.125rem 0.375rem',
                      borderRadius: 'var(--radius-full)',
                    }}>
                      {pct}%
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {type === 'missing' && items.length > 0 && (
          <div style={{
            marginTop: '0.5rem',
            padding: '0.5rem 0.625rem',
            background: 'rgba(180, 35, 24, 0.04)',
            border: '1px solid rgba(180, 35, 24, 0.12)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '0.75rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.4,
          }}>
            <strong>Tip:</strong> Add these skills to your resume if you have experience with them,
            or consider building projects that demonstrate these competencies.
          </div>
        )}
      </div>
    );
  };

  return (
    <div>
      {renderGroup(grouped.direct, 'direct')}
      {renderGroup(grouped.related, 'related')}
      {renderGroup(grouped.partial, 'partial')}
      {renderGroup(grouped.missing, 'missing')}
    </div>
  );
}
