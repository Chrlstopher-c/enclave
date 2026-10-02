/* Icônes du domaine retours, au trait comme celles des actions du chat (16 × 16, `currentColor`). */

import type { ReactElement } from 'react';

const TAILLE = 'h-3.5 w-3.5';

function Cadre({ d }: { d: string }): ReactElement {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true" className={TAILLE}>
      <path d={d} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function IconePouceHaut(): ReactElement {
  return <Cadre d="M5 7v6.5H2.5V7H5Zm0 0 2.6-4.6a1.2 1.2 0 0 1 2.2.8L9.3 6h3.3a1.2 1.2 0 0 1 1.2 1.4l-.9 5a1.2 1.2 0 0 1-1.2 1.1H5" />;
}

export function IconePouceBas(): ReactElement {
  return <Cadre d="M5 9V2.5H2.5V9H5Zm0 0 2.6 4.6a1.2 1.2 0 0 0 2.2-.8L9.3 10h3.3a1.2 1.2 0 0 0 1.2-1.4l-.9-5a1.2 1.2 0 0 0-1.2-1.1H5" />;
}

export function IconeCorriger(): ReactElement {
  return <Cadre d="M2.5 13.5h4M9.6 3.4a1.5 1.5 0 0 1 2.1 2.1L6 11.2l-2.6.6.6-2.6 5.6-5.8Z" />;
}
