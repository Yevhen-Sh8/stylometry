import React from 'react';

const GRADE_LABELS = {
  F:   'Фон — низький ризик',
  B:   'Базовий рівень',
  S:   'Значущий',
  SS:  'Високий',
  SSS: 'Критичний',
};

/**
 * DIMS threat-grade badge — the signature data element.
 * Grades per Наказ МО України № 46: F → B → S → SS → SSS.
 */
export function GradeBadge({
  grade = 'F',          // F | B | S | SS | SSS
  size = 'md',          // sm | md | lg
  meta = null,          // optional R_DIMS value shown beside the code
  flag = false,         // appends a ⚑ marker for SS/SSS escalation
  title,
  style = {},
  ...rest
}) {
  const g = String(grade).toUpperCase();
  const bg = `var(--grade-${g.toLowerCase()}-bg)`;
  const fg = `var(--grade-${g.toLowerCase()}-fg)`;

  const sizes = {
    sm: { padding: '1px 6px',  fontSize: 10 },
    md: { padding: '2px 8px',  fontSize: 12 },
    lg: { padding: '6px 14px', fontSize: 18 },
  };

  return (
    <span
      data-grade={g}
      title={title || GRADE_LABELS[g] || g}
      style={{
        display: 'inline-flex',
        alignItems: 'baseline',
        gap: 6,
        fontFamily: 'var(--font-mono)',
        fontWeight: 700,
        lineHeight: 1.35,
        letterSpacing: '0.04em',
        borderRadius: 'var(--r-sm)',
        border: '1px solid transparent',
        whiteSpace: 'nowrap',
        background: bg,
        color: fg,
        boxShadow: g === 'SSS' ? 'inset 0 0 0 1px rgba(255,255,255,0.12)' : 'none',
        ...sizes[size],
        ...style,
      }}
      {...rest}
    >
      <span style={{ fontWeight: 800 }}>{g}</span>
      {meta != null && (
        <span style={{ fontFamily: 'var(--font-sans)', fontWeight: 500, opacity: 0.82, fontSize: '0.85em' }}>
          {meta}
        </span>
      )}
      {flag && <span style={{ fontSize: '0.9em', marginLeft: 2 }}>⚑</span>}
    </span>
  );
}
