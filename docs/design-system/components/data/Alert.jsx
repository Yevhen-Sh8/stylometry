import React from 'react';

/**
 * DIMS alert — left-ruled inline notice. Critical / info tones.
 */
export function Alert({
  children,
  tone = 'info',   // info | critical
  title,
  style = {},
}) {
  const ruleColor = tone === 'critical' ? 'var(--danger)' : 'var(--accent-2)';
  const tint = tone === 'critical'
    ? 'color-mix(in srgb, var(--danger) 7%, transparent)'
    : 'color-mix(in srgb, var(--accent-2) 7%, transparent)';

  return (
    <div
      role={tone === 'critical' ? 'alert' : 'status'}
      style={{
        padding: 'var(--s-3) var(--s-4)',
        border: '1px solid var(--border-1)',
        borderLeft: `3px solid ${ruleColor}`,
        borderRadius: 'var(--r-sm)',
        fontSize: 12,
        lineHeight: 1.6,
        color: 'var(--text-1)',
        background: tint,
        ...style,
      }}
    >
      {title && (
        <strong style={{ color: ruleColor, display: 'block', marginBottom: 2 }}>{title}</strong>
      )}
      {children}
    </div>
  );
}
