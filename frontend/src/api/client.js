/**
 * ResumeIQ API Client
 * Talks to the FastAPI backend through the versioned REST API.
 */

const API_BASE = "/api";

async function request(url, options = {}) {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      ...(options.headers || {}),
    },
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `API Error: ${response.status}`);
  }

  return response.json();
}

// ── Resume ──────────────────────────────────────────────────────

export async function uploadResume(file) {
  const formData = new FormData();
  formData.append("file", file);

  return request("/resume/upload", {
    method: "POST",
    body: formData,
  });
}

export async function getResume(resumeId) {
  return request(`/resume/${resumeId}`);
}

// ── Job Description ─────────────────────────────────────────────

export async function analyzeJD(text = null, file = null) {
  const formData = new FormData();
  if (text) formData.append("text", text);
  if (file) formData.append("file", file);

  return request("/jd/analyze", {
    method: "POST",
    body: formData,
  });
}

// ── Analysis ────────────────────────────────────────────────────

export async function runAnalysis(resumeId, jdId = null) {
  return request("/analysis/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_id: resumeId, jd_id: jdId }),
  });
}

export async function getAnalysis(analysisId) {
  return request(`/analysis/${analysisId}`);
}

export async function getATSResults(analysisId) {
  return request(`/analysis/${analysisId}/ats`);
}

export async function getMatchResults(analysisId) {
  return request(`/analysis/${analysisId}/match`);
}

export async function getReadabilityResults(analysisId) {
  return request(`/analysis/${analysisId}/readability`);
}

// ── Recommendations & Rewriting (Phases 8, 11, 12, 13) ──────────

export async function getGeneralRecommendations(resumeId) {
  return request('/recommendations/general', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_id: resumeId }),
  });
}

export async function getJDRecommendations(resumeId, jdId) {
  return request('/recommendations/jd', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_id: resumeId, jd_id: jdId }),
  });
}

export async function getProjectRecommendations(skillGaps = [], difficulty = null) {
  return request('/projects/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ skill_gaps: skillGaps, difficulty, limit: 3 }),
  });
}

export async function rewriteBullet(originalBullet, resumeContext = '', jdRequirement = null, userMetric = null) {
  return request('/rewrite', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      original_bullet: originalBullet,
      resume_context: resumeContext,
      jd_requirement: jdRequirement,
      user_supplied_metric: userMetric,
    }),
  });
}

// ── Company Intelligence ────────────────────────────────────────

export async function researchCompany(jdText, companyName = null) {
  return request('/company/research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jd_text: jdText, company_name: companyName }),
  });
}

// ── Health ──────────────────────────────────────────────────────

export async function checkHealth() {
  const response = await fetch("/health");
  if (!response.ok) throw new Error("Health check failed");
  return response.json();
}

export async function checkEmbeddings() {
  const response = await fetch("/health/embeddings");
  if (!response.ok) throw new Error("Embeddings health check failed");
  return response.json();
}

// ── Export (Word, LaTeX, PDF, TXT) ──────────────────────────────

async function downloadExportFile(endpoint, resumeData, filename, defaultExt) {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      resume_data: resumeData,
      filename: filename || "edited_resume",
    }),
  });

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Export failed: ${response.status}`);
  }

  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${filename || "edited_resume"}.${defaultExt}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function exportResumeDocx(resumeData, filename = "edited_resume") {
  return downloadExportFile("/export/docx", resumeData, filename, "docx");
}

export async function exportResumeLatex(resumeData, filename = "edited_resume") {
  return downloadExportFile("/export/latex", resumeData, filename, "tex");
}

export async function exportResumePdf(resumeData, filename = "edited_resume") {
  return downloadExportFile("/export/pdf", resumeData, filename, "pdf");
}

export async function exportResumeTxt(resumeData, filename = "edited_resume") {
  return downloadExportFile("/export/txt", resumeData, filename, "txt");
}


// ── In-app editor (layout-anchored) ─────────────────────────────

export function pageImageUrl(resumeId, page, scale = 2) {
  return `${API_BASE}/editor/${resumeId}/page/${page}.png?scale=${scale}`;
}

export async function getEditorDocument(resumeId) {
  return request(`/editor/${resumeId}/document`);
}

export async function suggestForStatement(resumeId, statementId, { jdRequirement = null, userFacts = null } = {}) {
  return request('/editor/suggest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      resume_id: resumeId,
      statement_id: statementId,
      jd_requirement: jdRequirement,
      user_facts: userFacts,
    }),
  });
}
