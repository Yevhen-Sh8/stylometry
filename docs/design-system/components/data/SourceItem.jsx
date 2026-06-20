import React from 'react';

const TYPE_TINT = {
  GOOGLE:   { bg: 'rgba(66,133,244,.2)',  fg: '#3b82f6' },
  RSS:      { bg: 'rgba(251,191,36,.18)', fg: 'var(--signal-amber)' },
  TELEGRAM: { bg: 'rgba(0,136,204,.2)',   fg: '#2f86d6' },
  TXT:      { bg: 'var(--bg-2)',          fg: 'var(--text-2)' },
  PDF:      { bg: 'var(--bg-2)',          fg: 'var(--text-2)' },
  URL:      { bg: 'var(--bg-2)',          fg: 'var(--text-2)' },
};

/**
 * DIMS source row — one ingested document in the left-panel corpus list.
 */
export function SourceItem({
  label,
  meta,                 // mono sub-line: domain · tokens · date
  type = 'TXT',         // FILES badge: TXT | PDF | URL | RSS | TELEGRAM | GOOGLE
  warn = false,         // amber meta — e.g. < 500 tokens
  onRemove,
  style = {},
}) {
  const tint = TYPE_TINT[String(type).toUpperCase()] || TYPE_TINT.TXT;

  return (
    <div
      role="listitem"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '10px 12px',
        borderRadius: 'var(--r-md)',
        border: '1px solid var(--border-0)',
        marginBottom: 6,
        background: 'var(--bg-1)',
        ...style,
      }}
    >
      <span
        style={{
          minWidth: 44,
          padding: '2px 6px',
          borderRadius: 'var(--r-sm)',
          fontFamily: 'var(--font-mono)',
          fontSize: 10,
          fontWeight: 700,
          textAlign: 'center',
          letterSpacing: '0.04em',
          textTransform: 'uppercase',
          flexShrink: 0,
          background: tint.bg,
          color: tint.fg,
        }}
      >
        {type}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            fontSize: 12,
            fontWeight: 600,
            color: 'var(--text-0)',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {label}
        </div>
        {meta && (
          <div
            style={{
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              color: warn ? 'var(--warn)' : 'var(--text-2)',
              marginTop: 2,
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {meta}
          </div>
        )}
      </div>
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Видалити джерело"
          style={{
            background: 'transparent',
            border: '1px solid var(--border-1)',
            color: 'var(--text-3)',
            width: 26,
            height: 26,
            borderRadius: 'var(--r-sm)',
            cursor: 'pointer',
            fontSize: 12,
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            flexShrink: 0,
          }}
        >
          ✕
        </button>
      )}
    </div>
  );
}
