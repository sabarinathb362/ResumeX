/**
 * Word-level diff (LCS) for showing what a suggestion changes.
 * Returns [{type: 'same'|'del'|'ins', text}] with whitespace kept on tokens.
 */
export function wordDiff(a = '', b = '') {
  const A = a.split(/(\s+)/).filter(Boolean);
  const B = b.split(/(\s+)/).filter(Boolean);
  const n = A.length, m = B.length;
  const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) {
    for (let j = m - 1; j >= 0; j--) {
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
    }
  }
  const out = [];
  const push = (type, text) => {
    const last = out[out.length - 1];
    if (last && last.type === type) last.text += text;
    else out.push({ type, text });
  };
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { push('same', A[i]); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { push('del', A[i]); i++; }
    else { push('ins', B[j]); j++; }
  }
  while (i < n) push('del', A[i++]);
  while (j < m) push('ins', B[j++]);
  return out;
}

/** Apply accepted statement edits to a copy of resume_data so exports include them. */
export function applyEdits(resumeData, statementsById, edits) {
  const data = JSON.parse(JSON.stringify(resumeData || {}));
  for (const [sid, edit] of Object.entries(edits)) {
    const ref = statementsById[sid];
    if (!ref) continue;
    const path = ref.statement.path || [];
    if (path[0] === 'summary') {
      data.summary = (data.summary || '').replace(ref.statement.text, edit.text);
      continue;
    }
    if (path.length < 2) continue;
    let node = data;
    for (let k = 0; k < path.length - 1; k++) {
      if (node == null) break;
      node = node[path[k]];
    }
    if (node && Array.isArray(node)) node[path[path.length - 1]] = edit.text;
  }
  return data;
}

export const SEVERITY_COLOR = {
  critical: '#f87171',
  high: '#fb923c',
  medium: '#fbbf24',
  low: '#60a5fa',
  info: '#94a3b8',
};
export const SEVERITY_RANK = { critical: 4, high: 3, medium: 2, low: 1, info: 0 };
export const GRADE_COLOR = { A: '#34d399', B: '#2dd4bf', C: '#fbbf24', D: '#f87171' };
