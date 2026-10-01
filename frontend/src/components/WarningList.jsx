const severityConfig = {
  critical: { icon: '', color: 'var(--accent-danger)', bg: 'var(--accent-danger-bg)' },
  high:     { icon: '', color: 'var(--accent-warning)', bg: 'var(--accent-warning-bg)' },
  medium:   { icon: '', color: 'var(--accent-warning)', bg: 'var(--accent-warning-bg)' },
  low:      { icon: '', color: 'var(--accent-info)', bg: 'var(--accent-info-bg)' },
  info:     { icon: '', color: 'var(--text-muted)', bg: 'transparent' },
};

export default function WarningList({ warnings }) {
  if (!warnings || warnings.length === 0) {
    return (
      <div style={{ textAlign: 'center', padding: '1.5rem', color: 'var(--accent-success)' }}>
        <span style={{ fontSize: '1.5rem' }}></span>
        <p style={{ marginTop: '0.5rem', fontSize: '0.875rem' }}>No issues found!</p>
      </div>
    );
  }

  return (
    <div className="stagger-children">
      {warnings.map((warning, i) => {
        const config = severityConfig[warning.severity] || severityConfig.info;
        return (
          <div
            key={i}
            className="warning-item"
            style={{ background: config.bg, borderLeft: `3px solid ${config.color}` }}
          >
            <span className="icon">{config.icon}</span>
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                <span className={`badge badge-${warning.severity === 'critical' ? 'danger' : warning.severity === 'high' ? 'warning' : 'info'}`}>
                  {warning.severity?.toUpperCase()}
                </span>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                  {warning.dimension}
                </span>
              </div>
              <div className="message">{warning.message}</div>
              {warning.remediation && warning.remediation.length > 0 && (
                <div className="remediation">
                  {Array.isArray(warning.remediation) ? warning.remediation[0] : warning.remediation}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
