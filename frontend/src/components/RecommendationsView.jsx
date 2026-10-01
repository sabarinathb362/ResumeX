import { useState, useEffect } from 'react';
import {
  getGeneralRecommendations,
  getJDRecommendations,
  getProjectRecommendations,
  rewriteBullet,
} from '../api/client';

export default function RecommendationsView({ resumeId, jdId, resumeData, matchResult, companyIntel, onOpenEditor }) {
  const [activeTab, setActiveTab] = useState('recommendations');
  const [generalRecs, setGeneralRecs] = useState(null);
  const [jdRecs, setJdRecs] = useState(null);
  const [projects, setProjects] = useState(null);
  const [loading, setLoading] = useState(false);
  const [expandedRec, setExpandedRec] = useState(null);

  // Rewriter state
  const [bulletInput, setBulletInput] = useState('');
  const [userMetric, setUserMetric] = useState('');
  const [rewrites, setRewrites] = useState(null);
  const [rewriting, setRewriting] = useState(false);
  const [copiedIndex, setCopiedIndex] = useState(null);

  useEffect(() => {
    async function loadData() {
      if (!resumeId) return;
      setLoading(true);
      try {
        const gen = await getGeneralRecommendations(resumeId);
        setGeneralRecs(gen);

        if (jdId) {
          const jd = await getJDRecommendations(resumeId, jdId);
          setJdRecs(jd);
        }

        const gaps = matchResult?.missing_skills || ['Distributed Systems', 'Cloud CI/CD'];
        const proj = await getProjectRecommendations(gaps);
        setProjects(proj);
      } catch (err) {
        console.error('Failed to load recommendations:', err);
      } finally {
        setLoading(false);
      }
    }
    loadData();
  }, [resumeId, jdId]);

  const handleRewrite = async (textToRewrite = null) => {
    const text = textToRewrite || bulletInput;
    if (!text.trim()) return;
    setRewriting(true);
    setRewrites(null);
    try {
      const res = await rewriteBullet(text, resumeData?.raw_text || '', null, userMetric || null);
      setRewrites(res);
    } catch (err) {
      console.error('Rewrite failed:', err);
    } finally {
      setRewriting(false);
    }
  };

  const copyToClipboard = (text, idx) => {
    navigator.clipboard.writeText(text);
    setCopiedIndex(idx);
    setTimeout(() => setCopiedIndex(null), 2000);
  };

  const getSeverityConfig = (sev) => {
    switch (sev) {
      case 'critical': return { icon: '', badge: 'badge-danger', label: 'Critical', impact: '+5-8 pts' };
      case 'high': return { icon: '', badge: 'badge-warning', label: 'High Priority', impact: '+3-5 pts' };
      case 'medium': return { icon: '', badge: 'badge-info', label: 'Medium', impact: '+1-3 pts' };
      default: return { icon: '', badge: 'badge-neutral', label: 'Suggestion', impact: '+1 pt' };
    }
  };

  const tabs = [
    { id: 'recommendations', label: 'Action Items', icon: '', count: generalRecs?.total_recommendations || 0 },
    { id: 'rewriter', label: 'Bullet Rewriter', icon: '' },
    { id: 'projects', label: 'Gap Projects', icon: '', count: projects?.projects?.length || 0 },
  ];

  return (
    <div style={{ marginBottom: '2rem' }}>
      {/* Tab Navigation */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap', gap: '0.75rem' }}>
        <div className="tab-nav">
          {tabs.map(tab => (
            <button
              key={tab.id}
              className={`tab-btn ${activeTab === tab.id ? 'active' : ''}`}
              onClick={() => setActiveTab(tab.id)}
            >
              {tab.icon} {tab.label}
              {tab.count !== undefined && (
                <span style={{
                  fontSize: '0.625rem',
                  fontWeight: 700,
                  background: activeTab === tab.id ? 'var(--accent-glow)' : 'rgba(31,36,24,0.05)',
                  padding: '0.125rem 0.375rem',
                  borderRadius: 'var(--radius-full)',
                  color: activeTab === tab.id ? 'var(--accent-primary-light)' : 'var(--text-muted)',
                }}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: '0.375rem' }}>
          {onOpenEditor && (
            <button className="btn btn-primary btn-sm" onClick={onOpenEditor}>
              Open Editor
            </button>
          )}
        </div>
      </div>

      {/* ═══ Tab 1: Action Items ═══ */}
      {activeTab === 'recommendations' && (
        <div className="card animate-fade-in">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
            <div>
              <h3 style={{ fontSize: '1.0625rem', marginBottom: '0.125rem' }}>Actionable Improvements</h3>
              <div style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
                Target Role: <strong style={{ color: 'var(--accent-primary-light)' }}>{generalRecs?.top_role || 'Software Engineer'}</strong>
                {jdRecs && (
                  <span className="badge badge-success" style={{ marginLeft: '0.5rem' }}>
                    AI Match: {jdRecs.ai_match_percentage}%
                  </span>
                )}
              </div>
            </div>
            {companyIntel && companyIntel.company_name !== 'Unknown Company' && (
              <span className="badge badge-glow">{companyIntel.company_name}-Aligned</span>
            )}
          </div>

          {loading ? (
            <div style={{ textAlign: 'center', padding: '2rem' }}>
              <span className="spinner" />
              <div className="loading-text">Loading recommendations...</div>
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
              {generalRecs?.recommendations?.map((rec, idx) => {
                const config = getSeverityConfig(rec.severity);
                const isExpanded = expandedRec === rec.id;

                return (
                  <div
                    key={rec.id}
                    className={`insight-card ${rec.severity}`}
                    onClick={() => setExpandedRec(isExpanded ? null : rec.id)}
                    style={{ cursor: 'pointer' }}
                  >
                    <div className="insight-header">
                      <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flex: 1 }}>
                        <span>{config.icon}</span>
                        <span className="insight-title">{rec.title}</span>
                      </div>
                      <div style={{ display: 'flex', gap: '0.375rem', alignItems: 'center' }}>
                        <span className="insight-impact">{config.impact}</span>
                        <span className={`badge ${config.badge}`} style={{ fontSize: '0.5625rem' }}>{config.label}</span>
                        <span style={{
                          fontSize: '0.75rem', color: 'var(--text-muted)',
                          transform: isExpanded ? 'rotate(180deg)' : 'rotate(0)',
                          transition: 'transform 0.2s',
                        }}>▼</span>
                      </div>
                    </div>

                    {isExpanded && (
                      <div style={{ marginTop: '0.75rem', animation: 'fadeIn 0.2s ease-out' }}>
                        <div style={{ marginBottom: '0.625rem' }}>
                          <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>
                            Why This Matters
                          </div>
                          <div className="insight-body">{rec.why}</div>
                        </div>

                        <div style={{ marginBottom: '0.625rem' }}>
                          <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>
                            How To Fix
                          </div>
                          <div style={{
                            padding: '0.5rem 0.75rem',
                            background: 'rgba(61, 122, 58, 0.04)',
                            border: '1px solid rgba(61, 122, 58, 0.12)',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.8125rem',
                            color: 'var(--text-primary)',
                            lineHeight: 1.5,
                          }}>
                            {rec.how}
                          </div>
                        </div>

                        {rec.evidence_span && (
                          <div>
                            <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '0.25rem' }}>
                              Found In Resume
                            </div>
                            <div className="diff-before" style={{ marginBottom: '0.375rem' }}>
                              "{rec.evidence_span.slice(0, 120)}{rec.evidence_span.length > 120 ? '...' : ''}"
                            </div>
                            <button
                              className="btn btn-secondary btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                setBulletInput(rec.evidence_span);
                                setActiveTab('rewriter');
                                handleRewrite(rec.evidence_span);
                              }}
                              style={{ fontSize: '0.75rem', marginTop: '0.25rem' }}
                            >
                              Rewrite This Bullet
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* ═══ Tab 2: Bullet Rewriter ═══ */}
      {activeTab === 'rewriter' && (
        <div className="card animate-fade-in">
          <div style={{ marginBottom: '1rem' }}>
            <h3 style={{ fontSize: '1.0625rem', marginBottom: '0.125rem' }}>XYZ Bullet Rewriter</h3>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              Accomplished [X], as measured by [Y], by doing [Z] — with factual hard gate validation.
            </p>
          </div>

          <div style={{ marginBottom: '1.25rem' }}>
            <textarea
              className="textarea"
              placeholder="Paste any resume bullet to rewrite. e.g., 'Responsible for backend development and optimizing database queries.'"
              value={bulletInput}
              onChange={(e) => setBulletInput(e.target.value)}
              style={{ minHeight: '80px', marginBottom: '0.75rem' }}
            />
            <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
              <input
                className="input"
                placeholder="Optional verified metric (e.g. 35% latency, $1.2M volume)"
                value={userMetric}
                onChange={(e) => setUserMetric(e.target.value)}
                style={{ flex: 1 }}
              />
              <button
                className="btn btn-primary"
                onClick={() => handleRewrite()}
                disabled={rewriting || !bulletInput.trim()}
                style={{ minWidth: '160px' }}
              >
                {rewriting ? 'Rewriting...' : 'Generate Rewrites'}
              </button>
            </div>
          </div>

          {rewrites && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              <div style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                Validated Candidates
              </div>
              {rewrites.candidates?.map((c, i) => (
                <div key={i} style={{
                  padding: '1rem',
                  background: 'var(--bg-surface)',
                  borderRadius: 'var(--radius-md)',
                  border: '1px solid var(--border-subtle)',
                }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                    <span style={{ fontSize: '0.6875rem', fontWeight: 700, color: 'var(--accent-primary-light)', letterSpacing: '0.05em' }}>
                      OPTION {i + 1}
                    </span>
                    <span className={`badge ${c.is_factually_validated ? 'badge-success' : 'badge-danger'}`}>
                      {c.is_factually_validated ? 'Grounded' : 'Unverified'}
                    </span>
                  </div>

                  {/* Before/After Diff */}
                  <div style={{ marginBottom: '0.75rem' }}>
                    <div className="diff-before" style={{ marginBottom: '0.25rem' }}>
                      {bulletInput.slice(0, 120)}{bulletInput.length > 120 ? '...' : ''}
                    </div>
                    <div className="diff-after">
                      {c.rewritten_text}
                    </div>
                  </div>

                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {c.rationale}
                    </span>
                    <button
                      className="btn btn-secondary btn-sm"
                      onClick={() => copyToClipboard(c.rewritten_text, i)}
                      style={{ fontSize: '0.6875rem' }}
                    >
                      {copiedIndex === i ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ═══ Tab 3: Gap Projects ═══ */}
      {activeTab === 'projects' && (
        <div className="card animate-fade-in">
          <div style={{ marginBottom: '1rem' }}>
            <h3 style={{ fontSize: '1.0625rem', marginBottom: '0.125rem' }}>Skill-Gap Bridging Projects</h3>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              Targeted projects to gain verifiable proof-of-work for missing skills.
            </p>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: '0.75rem' }}>
            {projects?.projects?.map((p) => (
              <div key={p.id} style={{
                padding: '1.25rem',
                background: 'var(--bg-surface)',
                borderRadius: 'var(--radius-md)',
                border: '1px solid var(--border-subtle)',
                display: 'flex',
                flexDirection: 'column',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '0.5rem' }}>
                  <span className="badge badge-info">{p.difficulty}</span>
                </div>

                <h4 style={{ fontSize: '0.9375rem', marginBottom: '0.375rem' }}>{p.title}</h4>
                <p style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)', marginBottom: '0.75rem', flex: 1, lineHeight: 1.5 }}>
                  {p.why_recommended}
                </p>

                {p.suggested_stack?.length > 0 && (
                  <div style={{ marginBottom: '0.75rem' }}>
                    <div style={{ fontSize: '0.625rem', color: 'var(--text-muted)', marginBottom: '0.25rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
                      Stack
                    </div>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: '0.25rem' }}>
                      {p.suggested_stack.map((tech, idx) => (
                        <span key={idx} className="skill-tag matched" style={{ fontSize: '0.625rem', padding: '0.15rem 0.4rem' }}>{tech}</span>
                      ))}
                    </div>
                  </div>
                )}

                <div style={{
                  padding: '0.5rem 0.625rem',
                  background: 'rgba(85, 107, 47, 0.06)',
                  border: '1px solid rgba(85, 107, 47, 0.15)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.6875rem',
                  color: 'var(--text-secondary)',
                }}>
                  <strong style={{ color: 'var(--text-heading)' }}>Resume Bullet:</strong>
                  <div style={{ marginTop: '0.125rem', fontStyle: 'italic' }}>"{p.resume_bullet_template}"</div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
