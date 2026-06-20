import React from 'react';

/**
 * DIMS Button — the workspace action control.
 * Variants map 1:1 to the production .btn classes.
 */
export function Button({
  children,
  variant = 'default',   // default | primary | secondary | ghost
  size = 'md',           // xs | sm | md | large
  iconLeft = null,
  iconRight = null,
  disabled = false,
  type = 'button',
  style = {},
  ...rest
}) {
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 'var(--s-2)',
    fontFamily: 'var(--font-sans)',
    fontWeight: 600,
    border: '1px solid var(--border-1)',
    borderRadius: 'var(--r-sm)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    whiteSpace: 'nowrap',
    textDecoration: 'none',
    color: 'var(--text-1)',
    background: 'var(--bg-2)',
    transition: 'background 120ms, border-color 120ms, color 120ms',
    opacity: disabled ? 0.35 : 1,
    pointerEvents: disabled ? 'none' : 'auto',
  };

  const sizes = {
    xs:    { padding: '3px 8px',  fontSize: 11, minHeight: 24 },
    sm:    { padding: '5px 10px', fontSize: 11, minHeight: 28 },
    md:    { padding: '7px 14px', fontSize: 12, minHeight: 32 },
    large: { padding: '12px 22px', fontSize: 13, minHeight: 44 },
  };

  const variants = {
    default: {},
    primary: { background: 'var(--accent)', color: '#fff', borderColor: 'var(--accent)' },
    secondary: { background: 'var(--bg-2)' },
    ghost: { background: 'transparent', borderColor: 'transparent' },
  };

  return (
    <button
      type={type}
      disabled={disabled}
      style={{ ...base, ...sizes[size], ...variants[variant], ...style }}
      {...rest}
    >
      {iconLeft}
      {children != null && <span>{children}</span>}
      {iconRight}
    </button>
  );
}
