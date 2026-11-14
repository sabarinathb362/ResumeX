/**
 * Smooth page scrolling with Lenis, driven by GSAP's ticker so the app has one animation-frame loop.
 * Off when the user prefers reduced motion. Scrollable panels inside the page (editor sidebar,
 * parser output, text areas, menus) keep native scrolling.
 */
import { useEffect } from 'react';
import Lenis from 'lenis';
import 'lenis/dist/lenis.css';
import gsap from 'gsap';
import { prefersReducedMotion } from '../lib/motion';

const NATIVE_SCROLL = '.ed-side, .ats2-terminal, .a2-compare pre, .menu-pop, textarea, select, [data-lenis-prevent]';
let lenis = null;

export function useSmoothScroll() {
  useEffect(() => {
    if (prefersReducedMotion()) return undefined;
    lenis = new Lenis({
      lerp: 0.14,                 // settles quickly: smooth, not floaty
      wheelMultiplier: 1,
      prevent: node => node.matches?.(NATIVE_SCROLL),
    });
    const tick = time => lenis?.raf(time * 1000);
    gsap.ticker.add(tick);
    gsap.ticker.lagSmoothing(0);
    return () => {
      gsap.ticker.remove(tick);
      lenis.destroy();
      lenis = null;
    };
  }, []);
}

/** Jump to the top when the stage changes (no animation: the new stage fades in on its own). */
export function scrollToTop() {
  if (lenis) lenis.scrollTo(0, { immediate: true, force: true });
  else window.scrollTo(0, 0);
}
