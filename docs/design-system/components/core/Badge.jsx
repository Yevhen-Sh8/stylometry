import React from 'react';

/**
 * DIMS Badge — compact mono label/count. For severities, grades use GradeBadge.
 */
export function Badge({
  children,
  tone = 'neutral',   // neutral | ok | warn | danger | info
  style = {},
  ...rest
}) {
  const tones = {
    neutral: { color: 'var(--text-1)',   bg: 'var(--bg-2)',                  border: 'var(--border-1)' },
    ok:      { color: 'var(--ok)',       bg: 'color-mix(in srgb, var(--ok) 12%, transparent)',     border: 'var(--ok)' },
    warn:    { color: 'var(--warn)',     bg: 'color-mix(in srgb, var(--warn) 12%, transparent)',   border: 'var(--warn)' },
    danger:  { color: 'var(--danger)',   bg: 'color-mix(in srgb, var(--danger) 12%, transparent)', border: 'var(--danger)' },
    info:    { color: 'var(--accent-2)', bg: 'color-mix(in srgb, var(--accent-2) 12%, transparent)', border: 'var(--accent-2)' },
  };
  const t = tones[tone] || tones.neutral;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 7px',
        fontFamily: 'var(--font-mono)',
        fontSize: 11,
        fontWeight: 700,
        lineHeight: 1.5,
        borderRadius: 'var(--r-sm)',
        background: t.bg,
        color: t.color,
        border: `1px solid ${t.border}`,
        ...style,
      }}
      {...rest}
    >
      {children}
    </span>
  );
}
