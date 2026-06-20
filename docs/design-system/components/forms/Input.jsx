import React from 'react';

/**
 * DIMS form field — label + control (input / textarea) + hint.
 */
export function Input({
  label,
  hint,
  type = 'text',
  textarea = false,
  mono = false,
  value,
  placeholder,
  disabled = false,
  id,
  style = {},
  ...rest
}) {
  const controlStyle = {
    width: '100%',
    padding: textarea ? '10px 12px' : '8px 12px',
    background: 'var(--bg-1)',
    border: '1px solid var(--border-1)',
    color: 'var(--text-0)',
    fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
    fontSize: mono ? 12 : 13,
    lineHeight: 1.4,
    borderRadius: 'var(--r-sm)',
    minHeight: textarea ? 120 : 36,
    resize: textarea ? 'vertical' : undefined,
    outline: 'none',
    transition: 'border-color 120ms, box-shadow 120ms',
    ...style,
  };

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
      {textarea ? (
        <textarea id={id} value={value} placeholder={placeholder} disabled={disabled} style={controlStyle} {...rest} />
      ) : (
        <input id={id} type={type} value={value} placeholder={placeholder} disabled={disabled} style={controlStyle} {...rest} />
      )}
      {hint && (
        <p style={{ color: 'var(--text-3)', fontSize: 11, marginTop: 'var(--s-1)', lineHeight: 1.5 }}>{hint}</p>
      )}
    </div>
  );
}
