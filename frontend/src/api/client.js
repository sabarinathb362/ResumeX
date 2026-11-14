/**
 * ResumeIQ API Client
 * Talks to the FastAPI backend through the versioned REST API.
 */

import { readSSE } from "../lib/sse";

const API_BASE = "/api";

// ── Optional account ────────────────────────────────────────────
// The session token lives in this browser only; signing in is never required.
const TOKEN_KEY = "resumex.token";
export function getAuthToken() {
  try { return localStorage.getItem(TOKEN_KEY); } catch { return null; }
}
function setAuthToken(token) {
  try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ }
}
const jsonPost = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function signUp(email, password, name = "") {
  const r = await request("/auth/signup", jsonPost({ email, password, name }));
  setAuthToken(r.token);
  return r.user;
}
export async function signIn(email, password) {
  const r = await request("/auth/login", jsonPost({ email, password }));
  setAuthToken(r.token);
  return r.user;
}
export async function signOut() {
  try { await request("/auth/logout", { method: "POST" }); } finally { setAuthToken(null); }
}
export async function getMe() {
  if (!getAuthToken()) return null;
  try { return await request("/auth/me"); } catch { setAuthToken(null); return null; }
}
export const saveToHistory = (analysisId) => request("/auth/history", jsonPost({ analysis_id: analysisId }));
export const getHistory = () => request("/auth/history");
export const getHistoryJD = (id) => request(`/auth/history/${id}/jd`);
export const deleteHistory = (id) => request(`/auth/history/${id}`, { method: "DELETE" });

async function request(url, options = {}) {
  const response = await fetch(`${API_BASE}${url}`, {
    ...options,
    headers: {
      ...(getAuthToken() ? { Authorization: `Bearer ${getAuthToken()}` } : {}),
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

export async function runAnalysis(resumeId, jdId = null, { useLlm = false } = {}) {
  return request("/analysis/run", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_id: resumeId, jd_id: jdId, use_llm: useLlm }),
  });
}

/** Start the background LLM review; resolves when the job finishes. onProgress(p, message). */
export async function runDeepReview(analysisId, onProgress = () => {}) {
  const { job_id } = await request(`/analysis/${analysisId}/deep`, { method: "POST" });
  return new Promise((resolve, reject) => {
    const es = new EventSource(`${API_BASE}/jobs/${job_id}/events`);
    es.onmessage = (ev) => {
      const data = JSON.parse(ev.data);
      onProgress(data.progress ?? 0, data.message || "");
      if (data.done) { es.close(); data.error ? reject(new Error(data.error)) : resolve(data.result); }
    };
    es.onerror = () => { es.close(); reject(new Error("Lost connection to the deep review job")); };
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

export async function researchCompany(jdText, companyName = null, allowWeb = false) {
  // allowWeb sends only the company name to a public search API, and only if the server enables it
  return request('/company/research', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ jd_text: jdText, company_name: companyName, allow_web: allowWeb }),
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

export async function suggestForStatement(resumeId, statementId, { jdRequirement = null, userFacts = null, currentText = null, useLlm = true } = {}) {
  return request('/editor/suggest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      resume_id: resumeId,
      statement_id: statementId,
      jd_requirement: jdRequirement,
      user_facts: userFacts,
      current_text: currentText,
      use_llm: useLlm,
    }),
  });
}

/** SSE stream: `rules` first, then Tier-1 `token`s, then validated `candidate` / `rejected`, then `done`. */
export async function streamSuggestions(resumeId, statementId, { currentText = null, userFacts = null, jdRequirement = null, signal, onEvent }) {
  const response = await fetch(`${API_BASE}/editor/suggest/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify({
      resume_id: resumeId,
      statement_id: statementId,
      current_text: currentText,
      user_facts: userFacts,
      jd_requirement: jdRequirement,
      use_llm: true,
    }),
    signal,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `API Error: ${response.status}`);
  }
  await readSSE(response, onEvent);
}

// ── Editing in the original PDF layout ──────────────────────────

/** Editable text runs of the uploaded PDF: [{ id, page, bbox, text, size, font, flags, line_id }]. */
export async function getEditorUnits(resumeId) {
  return request(`/editor/${resumeId}/units`);
}

/** Typeset edits into the original pages. Returns { results: [{ key, ok, reason, scale, font }], pages: { n: dataUrl } }. */
export async function previewLayout(resumeId, edits, { scale = 2, signal } = {}) {
  return request(`/editor/${resumeId}/layout/preview`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edits, scale }),
    signal,
  });
}

/** Download the uploaded PDF with the edits applied in place (same template, fonts and spacing). */
export async function exportOriginalPdf(resumeId, edits, filename = 'resume_edited') {
  const response = await fetch(`${API_BASE}/editor/${resumeId}/layout/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ edits }),
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: response.statusText }));
    throw new Error(error.detail || `Export failed: ${response.status}`);
  }
  const blob = await response.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${filename}.pdf`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
  return { skipped: Number(response.headers.get('X-ResumeX-Skipped-Edits') || 0) };
}

export async function getEditorSidebar(resumeId, jdId = null) {
  const q = jdId ? `?jd_id=${encodeURIComponent(jdId)}` : '';
  return request(`/editor/${resumeId}/sidebar${q}`);
}

export async function checkLLM() {
  const response = await fetch('/health/llm');
  if (!response.ok) throw new Error('LLM health check failed');
  return response.json();
}

// ── ATS 2.0 ──
export async function getAts2Report(resumeId, analysisId = null) {
  const q = analysisId ? `?analysis_id=${encodeURIComponent(analysisId)}` : '';
  return request(`/ats2/${resumeId}${q}`);
}

// ── Mock Interview Arena ────────────────────────────────────────

export async function startInterview({ resumeId, jdId = null, analysisId = null, company = '', role = '' }) {
  return request('/interview/generate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ resume_id: resumeId, jd_id: jdId, analysis_id: analysisId, company, role }),
  });
}

export async function evaluateAnswer(sessionId, questionId, answer) {
  return request('/interview/evaluate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ session_id: sessionId, question_id: questionId, answer }),
  });
}

export async function getInterviewSession(sessionId) {
  return request(`/interview/sessions/${sessionId}`);
}

// ── Integrity checks (Phase 5) ──────────────────────────────────

export async function getIntegrity(resumeId, jdId = null) {
  const q = jdId ? `?jd_id=${encodeURIComponent(jdId)}` : '';
  return request(`/verify/${resumeId}${q}`);
}

export async function verifyGithub(resumeId, { consent, username = null }) {
  return request(`/verify/${resumeId}/github`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ consent, username }),
  });
}
