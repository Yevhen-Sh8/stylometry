import React from 'react';

const CARET = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='10' height='6' viewBox='0 0 10 6'><path d='M1 1l4 4 4-4' stroke='%236680A0' stroke-width='1.5' fill='none' stroke-linecap='round'/></svg>";

/**
 * DIMS select — label + native dropdown styled to match form controls.
 */
export function Select({
  label,
  hint,
  value,
  onChange,
  options = [],   // [{ value, label }] or [string]
  id,
  disabled = false,
  style = {},
  ...rest
}) {
  const opts = options.map((o) => (typeof o === 'string' ? { value: o, label: o } : o));

  return (
    <div style={{ marginBottom: 'var(--s-3)' }}>
      {label && (
        <label
          htmlFor={id}
          style={{
            display: 'block',
            fontFamily: 'var(--font-sans)',
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--text-1)',
            marginBottom: 'var(--s-1)',
          }}
        >
          {label}
        </label>
      )}
      <select
        id={id}
        value={value}
        onChange={onChange}
        disabled={disabled}
        style={{
          width: '100%',
          padding: '8px 28px 8px 12px',
          background: 'var(--bg-1)',
          border: '1px solid var(--border-1)',
          color: 'var(--text-0)',
          fontFamily: 'var(--font-sans)',
          fontSize: 13,
          lineHeight: 1.4,
          borderRadius: 'var(--r-sm)',
          minHeight: 36,
          appearance: 'none',
          WebkitAppearance: 'none',
          backgroundImage: `url("${CARET}")`,
          backgroundRepeat: 'no-repeat',
          backgroundPosition: 'right 10px center',
          cursor: 'pointer',
          outline: 'none',
          ...style,
        }}
        {...rest}
      >
        {opts.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {hint && (
        <p style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 'var(--s-1)', lineHeight: 1.5 }}>{hint}</p>
      )}
    </div>
  );
}
