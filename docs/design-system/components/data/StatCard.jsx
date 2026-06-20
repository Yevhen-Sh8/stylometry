import React from 'react';

/**
 * DIMS KPI / stat cell. Use inside a 1px-gap grid to form the stats strip.
 */
export function StatCard({
  value,
  label,
  tone = 'default',   // default | ok | warn | danger | info
  children,           // optional extra node beside value (e.g. a GradeBadge)
  style = {},
}) {
  const toneColor = {
    default: 'var(--text-0)',
    ok: 'var(--ok)',
    warn: 'var(--warn)',
    danger: 'var(--danger)',
    info: 'var(--accent-2)',
  }[tone];

  return (
    <div
      style={{
        background: 'var(--bg-1)',
        padding: 'var(--s-4)',
        display: 'flex',
        flexDirection: 'column',
        gap: 4,
        minHeight: 76,
        ...style,
      }}
    >
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: 22,
          fontWeight: 700,
          color: toneColor,
          lineHeight: 1,
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--s-2)',
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {value}
        {children}
      </div>
      <div
        style={{
          fontSize: 10,
          color: 'var(--text-3)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          fontWeight: 600,
        }}
      >
        {label}
      </div>
    </div>
  );
}
