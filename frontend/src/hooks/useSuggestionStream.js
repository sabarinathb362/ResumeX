/**
 * Per-statement suggestion state fed by POST /api/editor/suggest/stream.
 *   rules     — instant, rule-based (arrives first, < 50 ms server time)
 *   partial   — LLM text still being typed, keyed by angle
 *   llm       — finished candidates that passed the fact-checker
 *   model     — the Ollama model writing them (shown on each AI suggestion)
 *   rejected  — finished candidates the fact-checker blocked (shown collapsed)
 * Selecting another bullet aborts the previous stream, which stops generation in Ollama.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { streamSuggestions } from '../api/client';

const EMPTY = { status: 'idle', rules: null, llm: [], rejected: [], partial: {}, llmState: null, model: null, error: null };

export function useSuggestionStream(resumeId) {
  const [bySid, setBySid] = useState({});
  const ctrl = useRef(null);
  const timer = useRef(null);

  const cancel = useCallback(() => {
    clearTimeout(timer.current);
    ctrl.current?.abort();
    ctrl.current = null;
  }, []);

  useEffect(() => cancel, [cancel]);

  const run = useCallback((sid, { currentText = null, userFacts = null, jdRequirement = null, immediate = false } = {}) => {
    cancel();
    const patch = (fn) => setBySid(m => ({ ...m, [sid]: fn(m[sid] || EMPTY) }));
    patch(() => ({ ...EMPTY, status: 'loading' }));
    timer.current = setTimeout(async () => {
      const ac = new AbortController();
      ctrl.current = ac;
      try {
        await streamSuggestions(resumeId, sid, {
          currentText, userFacts, jdRequirement, signal: ac.signal,
          onEvent: (ev, data) => {
            if (ev === 'rules') patch(s => ({ ...s, rules: data, status: 'streaming' }));
            else if (ev === 'status') patch(s => ({ ...s, llmState: data.llm, model: data.model || s.model, error: data.message || null }));
            else if (ev === 'token') patch(s => ({ ...s, partial: { ...s.partial, [data.angle]: (s.partial[data.angle] || '') + data.text } }));
            else if (ev === 'candidate' || ev === 'rejected') patch(s => {
              const partial = { ...s.partial };
              delete partial[data.angle];
              return ev === 'candidate' ? { ...s, partial, llm: [...s.llm, data] } : { ...s, partial, rejected: [...s.rejected, data] };
            });
            else if (ev === 'done') patch(s => ({ ...s, status: 'done', partial: {} }));
          },
        });
      } catch (e) {
        if (e.name !== 'AbortError') patch(s => ({ ...s, status: 'error', error: e.message }));
      }
    }, immediate ? 0 : 200);
  }, [resumeId, cancel]);

  return { bySid, run, cancel };
}
