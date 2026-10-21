// Small inline icon set (stroke icons, currentColor).
type P = { size?: number; className?: string };
const base = (size = 22) => ({
  width: size,
  height: size,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 1.8,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
});

export const Cloud = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M7 18h10a4 4 0 0 0 .6-7.95A6 6 0 0 0 6.1 9.2 4.5 4.5 0 0 0 7 18z" /></svg>
);
export const Phone = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><rect x="7" y="2.5" width="10" height="19" rx="2.5" /><path d="M11 18.5h2" /></svg>
);
export const Bars = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M5 20v-6M10 20V9M15 20v-9M20 20V4" /></svg>
);
export const WalletIco = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H18v4" /><rect x="3" y="7" width="18" height="12" rx="2.5" /><path d="M16 13h2" /></svg>
);
export const Shield = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 3l7 3v5c0 4.5-3 8.3-7 10-4-1.7-7-5.5-7-10V6l7-3z" /><path d="M9 12l2 2 4-4" /></svg>
);
export const Home = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M4 11l8-7 8 7v9a1 1 0 0 1-1 1h-5v-6h-4v6H5a1 1 0 0 1-1-1z" /></svg>
);
export const Cpu = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><rect x="6" y="6" width="12" height="12" rx="2" /><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4" /></svg>
);
export const Gear = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></svg>
);
export const Download = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 4v11M7 10l5 5 5-5M5 20h14" /></svg>
);

export const Search = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="11" cy="11" r="6.5" /><path d="M20 20l-4.2-4.2" /></svg>
);
export const Dna = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M7 3c0 6 10 6 10 12s-10 6-10 6M17 3c0 6-10 6-10 12M17 21c0-2-.6-3.3-1.6-4.3" /><path d="M8.5 7h7M8.5 17h7" /></svg>
);
export const Sparkle = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z" /><path d="M19 16l.8 2.2L22 19l-2.2.8L19 22l-.8-2.2L16 19l2.2-.8z" /></svg>
);
export const Film = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><rect x="3" y="4" width="18" height="16" rx="2.5" /><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4" /></svg>
);
export const Play = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M8 5.5v13l10.5-6.5z" /></svg>
);
export const Upload = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M12 16V4M7 9l5-5 5 5M5 20h14" /></svg>
);

export const Trash = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M4 7h16M9 7V4.5h6V7M6.5 7l1 13h9l1-13M10 11v5M14 11v5" /></svg>
);

export const Branch = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><circle cx="6" cy="5" r="2.2" /><circle cx="6" cy="19" r="2.2" /><circle cx="18" cy="7" r="2.2" /><path d="M6 7.2v9.6M18 9.2c0 4-6 3.5-11 7.5" /></svg>
);
export const Code = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M8 7l-5 5 5 5M16 7l5 5-5 5M13.5 4l-3 16" /></svg>
);
export const Flask = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M9 3h6M10 3v6l-5.5 9.5A1.7 1.7 0 0 0 6 21h12a1.7 1.7 0 0 0 1.5-2.5L14 9V3" /><path d="M7.5 15h9" /></svg>
);
export const Check = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M5 12.5l4.5 4.5L19 7.5" /></svg>
);
export const Cross = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M6 6l12 12M18 6L6 18" /></svg>
);
export const Rocket = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M14 4c3.5-1 6-.5 6-.5s.5 2.5-.5 6L13 16l-5-5z" /><path d="M8 11l-3.5.5L3 14l4 1M13 16l-.5 3.5L10 21l-1-4" /><circle cx="15.5" cy="8.5" r="1.4" /></svg>
);
export const Doc = ({ size, className }: P) => (
  <svg {...base(size)} className={className}><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z" /><path d="M14 3v5h5M9 13h6M9 17h6" /></svg>
);

/** Brand mark: "F" with a four-point star. */
export function BrandMark({ className = "brand-mark" }: { className?: string }) {
  return (
    <svg viewBox="0 0 64 64" className={className} aria-hidden>
      <rect width="64" height="64" rx="16" fill="#c1fa74" />
      <path d="M20 46V18h22v6H27v6h13v6H27v10z" fill="#14112f" />
      <path d="M50 8l1.6 4.4L56 14l-4.4 1.6L50 20l-1.6-4.4L44 14l4.4-1.6z" fill="#14112f" />
    </svg>
  );
}
