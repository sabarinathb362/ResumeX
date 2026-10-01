import { useState, useEffect } from 'react';
import './index.css';
import FileUpload from './components/FileUpload';
import ScoreGauge from './components/ScoreGauge';
import InsightsPanel from './components/InsightsPanel';
import SkillMatrix from './components/SkillMatrix';
import RRIPanel from './components/RRIPanel';
import RecommendationsView from './components/RecommendationsView';
import ResumeEditor from './components/ResumeEditor';
import CompanyIntel from './components/CompanyIntel';
import { uploadResume, analyzeJD, runAnalysis, researchCompany } from './api/client';

function Navbar({ view, setView, hasResults }) {
  return (
    <nav className="navbar no-print">
      <div className="container navbar-inner">
        <div className="navbar-brand" onClick={() => hasResults && setView('dashboard')} style={{ cursor: hasResults ? 'pointer' : 'default' }}>
          <div className="logo-icon">X</div>
          <span>Resume<span style={{ color: 'var(--accent-cyan)' }}>X</span></span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {hasResults && (
            <>
              {view === 'editor' ? (
                <button className="btn btn-secondary btn-sm" onClick={() => setView('dashboard')}>
                  Dashboard
                </button>
              ) : (
                <button className="btn btn-primary btn-sm" onClick={() => setView('editor')}>
                  Resume Editor
                </button>
              )}
            </>
          )}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div className="pulse-dot" />
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Local AI</span>
          </div>
        </div>
      </div>
    </nav>
  );
}

function HeroSection({ onGetStarted }) {
  return (
    <div style={{
      background: 'var(--gradient-hero)',
      padding: '5rem 0 4rem',
      textAlign: 'center',
      position: 'relative',
      overflow: 'hidden',
    }}>
      {/* Animated gradient orbs */}
      <div style={{
        position: 'absolute', top: '10%', left: '15%',
        width: '500px', height: '500px',
        background: 'radial-gradient(circle, rgba(85, 107, 47, 0.08) 0%, transparent 60%)',
        animation: 'glowPulse 4s ease-in-out infinite', pointerEvents: 'none',
      }} />
      <div style={{
        position: 'absolute', bottom: '10%', right: '10%',
        width: '400px', height: '400px',
        background: 'radial-gradient(circle, rgba(107, 142, 35, 0.06) 0%, transparent 60%)',
        animation: 'glowPulse 5s ease-in-out infinite 1s', pointerEvents: 'none',
      }} />

      <div className="container animate-fade-in-up" style={{ position: 'relative', zIndex: 1 }}>
        <div style={{ marginBottom: '1rem' }}>
          <span className="badge badge-glow" style={{ fontSize: '0.75rem', padding: '0.4rem 1rem' }}>
            100% Local AI · Your data never leaves your device
          </span>
        </div>
        <h1 style={{ marginBottom: '1.25rem', fontSize: '3.25rem', letterSpacing: '-0.04em', lineHeight: 1.15 }}>
          AI-Powered Resume
          <br />
          <span style={{
            background: 'var(--gradient-accent)',
            WebkitBackgroundClip: 'text',
            WebkitTextFillColor: 'transparent',
          }}>Intelligence Platform</span>
        </h1>
        <p style={{
          fontSize: '1.0625rem',
          color: 'var(--text-secondary)',
          maxWidth: '580px',
          margin: '0 auto 2.5rem',
          lineHeight: 1.7,
        }}>
          Deep ATS analysis, real-time company intelligence, and 
          evidence-grounded optimization — all running privately on your machine.
        </p>
        <button className="btn btn-primary btn-lg" onClick={onGetStarted}
          style={{ boxShadow: '0 8px 30px rgba(85, 107, 47, 0.4)' }}>
          Start Analysis
        </button>
      </div>
    </div>
  );
}

function UploadSection({ onAnalysisComplete }) {
  const [resumeFile, setResumeFile] = useState(null);
  const [jdText, setJdText] = useState('');
  const [jdFile, setJdFile] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [step, setStep] = useState('');
  const [progress, setProgress] = useState(0);

  const handleAnalyze = async () => {
    if (!resumeFile) return;
    setLoading(true);
    setError(null);
    setProgress(0);

    try {
      setStep('Parsing resume...');
      setProgress(15);
      const resumeResult = await uploadResume(resumeFile);

      let jdId = null;
      if (jdText.trim() || jdFile) {
        setStep('Analyzing job description...');
        setProgress(35);
        const jdResult = await analyzeJD(jdText.trim() || null, jdFile || null);
        jdId = jdResult.id;
      }

      setStep(jdId ? 'Running ATS + match analysis...' : 'Running ATS analysis...');
      setProgress(60);
      const analysisResult = await runAnalysis(resumeResult.id, jdId);

      // Company research (if JD provided)
      let companyIntel = null;
      if (jdText.trim()) {
        setStep('Researching company...');
        setProgress(85);
        try {
          companyIntel = await researchCompany(jdText.trim());
        } catch (e) {
          console.warn('Company research failed:', e);
        }
      }

      setProgress(100);
      onAnalysisComplete?.({
        resume: resumeResult,
        analysis: analysisResult,
        companyIntel,
        jdText: jdText.trim(),
      });
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
      setStep('');
      setProgress(0);
    }
  };

  return (
    <div className="container page">
      <div style={{ maxWidth: '920px', margin: '0 auto' }}>
        <div style={{ textAlign: 'center', marginBottom: '2.5rem' }}>
          <h2 style={{ marginBottom: '0.5rem' }}>Upload & Analyze</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.9375rem' }}>
            Upload your resume and optionally provide a job description for company-tailored insights.
          </p>
        </div>

        <div className="grid-2" style={{ marginBottom: '2rem', gap: '1.5rem' }}>
          <div>
            <h4 style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              Resume <span className="badge badge-danger" style={{ fontSize: '0.5625rem' }}>Required</span>
            </h4>
            <FileUpload
              onFileSelect={setResumeFile}
              accept=".pdf,.docx,.doc"
              label="Drop your resume here"
              subtitle="PDF or DOCX · Max 10 MB"
              disabled={loading}
            />
          </div>

          <div>
            <h4 style={{ marginBottom: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              Job Description <span className="badge badge-neutral" style={{ fontSize: '0.5625rem' }}>Optional</span>
            </h4>
            <textarea
              className="textarea"
              placeholder="Paste the job description here for company-specific insights, skill gap analysis, and tailored optimization..."
              value={jdText}
              onChange={(e) => setJdText(e.target.value)}
              disabled={loading}
              style={{ minHeight: '220px' }}
            />
          </div>
        </div>

        {error && (
          <div style={{
            background: 'var(--accent-danger-bg)',
            border: '1px solid rgba(180, 35, 24, 0.3)',
            borderRadius: 'var(--radius-md)',
            padding: '0.875rem 1rem',
            color: 'var(--accent-danger)',
            fontSize: '0.875rem',
            marginBottom: '1.5rem',
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
          }}>
            {error}
          </div>
        )}

        {loading && (
          <div style={{ marginBottom: '1.5rem' }}>
            <div className="progress-bar" style={{ height: 4, marginBottom: '0.5rem' }}>
              <div className="fill" style={{
                width: `${progress}%`,
                background: 'var(--gradient-primary)',
                transition: 'width 0.5s ease',
              }} />
            </div>
            <div style={{ textAlign: 'center', fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              {step}
            </div>
          </div>
        )}

        <div style={{ textAlign: 'center' }}>
          <button
            className="btn btn-primary btn-lg"
            onClick={handleAnalyze}
            disabled={!resumeFile || loading}
            style={{ minWidth: '240px' }}
          >
            {loading ? (
              <>
                <span className="spinner" style={{ width: 18, height: 18, margin: 0, borderWidth: 2 }} />
                Analyzing...
              </>
            ) : (
              'Analyze Resume'
            )}
          </button>
          <p style={{ marginTop: '0.75rem', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            {jdText.trim()
              ? 'Will run ATS + match analysis + company research'
              : 'Will run ATS compatibility + readability analysis'}
          </p>
        </div>
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   DASHBOARD — Premium Bento Grid Layout
   ═══════════════════════════════════════════════════════════════ */

function Dashboard({ results, onOpenEditor }) {
  const { resume, analysis, companyIntel, jdText } = results;
  const ats = analysis.ats_result;
  const match = analysis.match_result;
  const readability = analysis.readability_result;
  const resumeData = resume.resume_data;

  const atsPercent = Math.round((ats.overall_score / ats.max_possible) * 100);
  const readPercent = readability ? Math.round((readability.overall_score / readability.max_possible) * 100) : null;
  const matchPercent = match ? Math.round((match.overall_score / match.max_possible) * 100) : null;

  // Unified, evidence-linked findings (ATS + readability + quality)
  const insights = analysis.insights || [];
  const criticalCount = insights.filter(f => f.severity === 'critical' || f.severity === 'high').length;

  return (
    <div className="container page">

      {/* ── Top Summary Banner ────────────────────────────────── */}
      <div className="animate-fade-in-up" style={{ marginBottom: '1.5rem' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', justifyContent: 'space-between', alignItems: 'center', gap: '1rem' }}>
          <div>
            <h2 style={{ fontSize: '1.5rem', marginBottom: '0.25rem' }}>
              Analysis for <span style={{ color: 'var(--accent-primary-light)' }}>{resumeData.contact?.name || 'Your Resume'}</span>
            </h2>
            <p style={{ fontSize: '0.8125rem', color: 'var(--text-muted)' }}>
              {criticalCount > 0 ? `${criticalCount} high-priority issue${criticalCount > 1 ? 's' : ''} found` : 'No critical issues'} 
              {' · '}{insights.length} total findings · {resumeData.all_skills_flat?.length || 0} skills detected
            </p>
          </div>
          <div style={{ display: 'flex', gap: '0.5rem' }}>
            <button className="btn btn-primary" onClick={() => onOpenEditor(null)} style={{ boxShadow: '0 4px 16px rgba(85, 107, 47, 0.35)' }}>
              Open Resume Editor
            </button>
            <button className="btn btn-secondary" onClick={() => window.location.reload()}>
              New Analysis
            </button>
          </div>
        </div>
      </div>

      {/* ── Bento Score Grid ──────────────────────────────────── */}
      <div className="bento-grid" style={{ marginBottom: '1.5rem' }}>

        {/* ATS Score — Large */}
        <div className={`card animate-fade-in-up span-${match ? '3' : '4'}`}
          style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '2rem 1.5rem' }}>
          <div className="card-title" style={{ marginBottom: '1rem' }}>ATS Compatibility</div>
          <ScoreGauge
            score={ats.overall_score}
            maxScore={ats.max_possible}
            size={120}
            label="ATS Score"
          />
          <span className="badge badge-neutral" style={{ marginTop: '0.75rem' }}>Rubric v{ats.rubric_version}</span>
        </div>

        {/* Readability Score */}
        {readability && (
          <div className={`card animate-fade-in-up span-${match ? '3' : '4'}`}
            style={{ animationDelay: '0.05s', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '2rem 1.5rem' }}>
            <div className="card-title" style={{ marginBottom: '1rem' }}>Readability</div>
            <ScoreGauge
              score={readability.overall_score}
              maxScore={readability.max_possible}
              size={120}
              label="RRI Score"
            />
            <span className="badge badge-neutral" style={{ marginTop: '0.75rem' }}>ATS 2.0 · Recruiter Readability</span>
          </div>
        )}

        {/* Match Score */}
        {match && (
          <div className="card animate-fade-in-up span-3"
            style={{ animationDelay: '0.1s', display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', padding: '2rem 1.5rem' }}>
            <div className="card-title" style={{ marginBottom: '1rem' }}>Job Match</div>
            <ScoreGauge
              score={match.overall_score}
              maxScore={match.max_possible}
              size={120}
              label="Match Score"
            />
            <span className="badge badge-info" style={{ marginTop: '0.75rem' }}>Hybrid Analysis</span>
          </div>
        )}

        {/* Quick Stats */}
        <div className={`card animate-fade-in-up span-${match ? '3' : '4'}`}
          style={{ animationDelay: '0.15s', padding: '1.5rem' }}>
          <div className="card-title" style={{ marginBottom: '1rem' }}>Resume Profile</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.625rem', fontSize: '0.875rem' }}>
            <div style={{ fontWeight: 700, color: 'var(--text-heading)', fontSize: '1rem', marginBottom: '0.25rem' }}>
              {resumeData.contact?.name || 'Name not detected'}
            </div>
            {resumeData.contact?.email && (
              <div style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem' }}>{resumeData.contact.email}</div>
            )}
            <div style={{ borderTop: '1px solid var(--border-subtle)', paddingTop: '0.625rem', display: 'flex', flexDirection: 'column', gap: '0.375rem' }}>
              {[
                ['', 'Sections', resumeData.sections?.length || 0],
                ['', 'Experience', resumeData.experience?.length || 0],
                ['', 'Education', resumeData.education?.length || 0],
                ['', 'Skills', resumeData.all_skills_flat?.length || 0],
                ['', 'Projects', resumeData.projects?.length || 0],
              ].map(([icon, label, count]) => (
                <div key={label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8125rem' }}>
                  <span style={{ color: 'var(--text-muted)' }}>{icon} {label}</span>
                  <span style={{ color: 'var(--text-heading)', fontWeight: 600 }}>{count}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* ── Company Intelligence (if JD provided) ────────────── */}
      {companyIntel && companyIntel.company_name !== 'Unknown Company' && (
        <div className="animate-fade-in-up" style={{ animationDelay: '0.2s', marginBottom: '1.5rem' }}>
          <CompanyIntel intel={companyIntel} />
        </div>
      )}

      {/* ── Insight Panels ────────────────────────────────────── */}
      <div className="bento-grid" style={{ marginBottom: '1.5rem' }}>

        {/* ATS Breakdown */}
        <div className="card animate-fade-in-up span-6" style={{ animationDelay: '0.25s' }}>
          <div className="card-header">
            <span className="card-title">ATS Category Breakdown</span>
            <span className="badge badge-neutral">{ats.category_scores?.length || 0} dimensions</span>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {ats.category_scores?.map((cat, i) => {
              const pct = Math.round((cat.score / cat.max_score) * 100);
              const color = pct >= 80 ? 'var(--accent-success)' : pct >= 60 ? 'var(--accent-warning)' : 'var(--accent-danger)';
              return (
                <div key={i}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                    <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>{cat.dimension}</span>
                    <span style={{ fontSize: '0.8125rem', fontWeight: 700, color }}>{cat.score}/{cat.max_score}</span>
                  </div>
                  <div className="progress-bar">
                    <div className="fill" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}aa, ${color})` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Priority Issues */}
        <div className="card animate-fade-in-up span-6" style={{ animationDelay: '0.3s' }}>
          <InsightsPanel insights={insights} onLocate={(f) => onOpenEditor(f)} />
        </div>
      </div>

      {/* ── Readability Deep Dive ─────────────────────────────── */}
      {readability && (
        <div className="animate-fade-in-up" style={{ animationDelay: '0.35s', marginBottom: '1.5rem' }}>
          <RRIPanel readability={readability} onLocate={(f) => onOpenEditor(f)} />
        </div>
      )}

      {/* ── Skill Analysis ────────────────────────────────────── */}
      {match && (
        <div className="bento-grid" style={{ marginBottom: '1.5rem' }}>
          <div className="card animate-fade-in-up span-6" style={{ animationDelay: '0.4s' }}>
            <div className="card-header">
              <span className="card-title">Match Dimensions</span>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {match.dimension_scores?.map((dim, i) => {
                const pct = Math.round((dim.score / dim.max_score) * 100);
                const color = pct >= 80 ? 'var(--accent-success)' : pct >= 60 ? 'var(--accent-warning)' : 'var(--accent-danger)';
                return (
                  <div key={i}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '0.25rem' }}>
                      <span style={{ fontSize: '0.8125rem', color: 'var(--text-secondary)' }}>{dim.dimension}</span>
                      <span style={{ fontSize: '0.8125rem', fontWeight: 700, color }}>{dim.score}/{dim.max_score}</span>
                    </div>
                    <div className="progress-bar">
                      <div className="fill" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${color}aa, ${color})` }} />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          <div className="card animate-fade-in-up span-6" style={{ animationDelay: '0.45s' }}>
            <div className="card-header">
              <span className="card-title">Skill Analysis</span>
              <div style={{ display: 'flex', gap: '0.375rem' }}>
                <span className="badge badge-success">{match.matched_skills?.length || 0} matched</span>
                <span className="badge badge-danger">{match.missing_skills?.length || 0} gaps</span>
              </div>
            </div>
            <SkillMatrix skillMatches={match.skill_matches} />
          </div>
        </div>
      )}

      {/* ── Recommendations & Rewriter ────────────────────────── */}
      <RecommendationsView
        resumeId={resume.id}
        jdId={analysis.jd_id}
        resumeData={resumeData}
        matchResult={match}
        companyIntel={companyIntel}
        onOpenEditor={() => onOpenEditor(null)}
      />

      {/* ── Disclosure ────────────────────────────────────────── */}
      <div className="disclosure" style={{ marginTop: '2rem' }}>
        <span className="icon"></span>
        All scores are ResumeX's own transparent, versioned rubrics — not industry standards or predictions of hiring outcomes.
      </div>
    </div>
  );
}

/* ═══════════════════════════════════════════════════════════════
   APP ROOT
   ═══════════════════════════════════════════════════════════════ */

export default function App() {
  const [view, setView] = useState('hero');
  const [results, setResults] = useState(null);
  const [editorFocus, setEditorFocus] = useState(null);
  const openEditor = (focus) => { setEditorFocus(focus || null); setView('editor'); };

  return (
    <div>
      <Navbar view={view} setView={setView} hasResults={!!results} />

      {view === 'hero' && (
        <HeroSection onGetStarted={() => setView('upload')} />
      )}

      {view === 'upload' && (
        <UploadSection
          onAnalysisComplete={(data) => {
            setResults(data);
            setView('dashboard');
          }}
        />
      )}

      {view === 'dashboard' && results && (
        <Dashboard
          results={results}
          onOpenEditor={openEditor}
        />
      )}

      {view === 'editor' && results && (
        <ResumeEditor
          resumeId={results.resume.id}
          resumeData={results.resume.resume_data}
          analysis={results.analysis}
          focus={editorFocus}
          onBack={() => setView('dashboard')}
        />
      )}

      {view === 'hero' && (
        <div className="container page">
          <div className="grid-3 stagger-children" style={{ marginTop: '1rem' }}>
            {[
              { icon: '', title: 'ATS + Match Analysis', desc: 'Deterministic scoring across 9 ATS rules and 7 match dimensions with evidence-traced results.' },
              { icon: '', title: 'Company Intelligence', desc: 'Real-time company research for tech stack, culture, and role-specific optimization tips.' },
              { icon: '', title: '100% Private', desc: 'Everything runs locally. No data is ever sent to any server. Your resume stays on your device.' },
            ].map((item, i) => (
              <div key={i} className="card" style={{ padding: '2rem 1.5rem', textAlign: 'center' }}>
                <span style={{ fontSize: '2.5rem', display: 'block', marginBottom: '1rem' }}>{item.icon}</span>
                <h3 style={{ marginBottom: '0.5rem', fontSize: '1.125rem' }}>{item.title}</h3>
                <p style={{ color: 'var(--text-secondary)', fontSize: '0.8125rem', lineHeight: 1.6 }}>{item.desc}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
