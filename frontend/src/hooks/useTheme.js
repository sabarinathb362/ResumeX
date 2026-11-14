/**
 * Light / dark theme. The initial value is set on <html data-theme> by the inline script in
 * index.html (saved choice, else the system setting), so there is no flash on load. A choice made
 * with the toggle is remembered; until then the app follows the system setting.
 */
import { useCallback, useEffect, useState } from 'react';

const KEY = 'resumex-theme';

function stored() {
  try { return localStorage.getItem(KEY); } catch { return null; }
}

function current() {
  return document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light';
}

export function useTheme() {
  const [theme, setTheme] = useState(current);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
  }, [theme]);

  // Follow the system setting while the user has not chosen explicitly.
  useEffect(() => {
    const mq = window.matchMedia?.('(prefers-color-scheme: dark)');
    if (!mq) return undefined;
    const onChange = e => { if (!stored()) setTheme(e.matches ? 'dark' : 'light'); };
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, []);

  const toggle = useCallback(() => {
    setTheme(t => {
      const next = t === 'dark' ? 'light' : 'dark';
      try { localStorage.setItem(KEY, next); } catch { /* private mode: the choice lasts for this visit */ }
      return next;
    });
  }, []);

  return { theme, toggle };
}
