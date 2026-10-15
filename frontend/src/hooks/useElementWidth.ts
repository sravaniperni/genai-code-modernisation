import { useEffect, useRef, useState } from 'react';

/** Track an element's content width so SVG charts render at real pixel size instead of scaling text. */
export function useElementWidth<T extends HTMLElement>(fallback = 480) {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(fallback);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (el.clientWidth) setWidth(el.clientWidth);
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w) setWidth(Math.floor(w));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return [ref, width] as const;
}
