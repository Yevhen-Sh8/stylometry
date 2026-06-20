import React from 'react';

/**
 * DIMS pill tabs — the segmented input switcher (Файли / Текст / Новини …).
 */
export function Tabs({
  tabs = [],          // [{ id, label }]
  active,
  onChange = () => {},
  style = {},
}) {
  const activeId = active != null ? active : (tabs[0] && tabs[0].id);

  return (
    <div
      role="tablist"
      style={{
        display: 'flex',
        gap: 4,
        padding: 4,
        background: 'var(--bg-0)',
        border: '1px solid var(--border-0)',
        borderRadius: 'var(--r-md)',
        ...style,
      }}
    >
      {tabs.map((t) => {
        const on = t.id === activeId;
        return (
          <button
            key={t.id}
            role="tab"
            aria-selected={on}
            type="button"
            onClick={() => onChange(t.id)}
            style={{
              flex: 1,
              padding: '6px 10px',
              fontFamily: 'var(--font-sans)',
              fontSize: 11,
              fontWeight: 600,
              borderRadius: 'var(--r-md)',
              border: on ? '1px solid var(--border-0)' : '1px solid transparent',
              cursor: 'pointer',
              background: on ? 'var(--bg-1)' : 'transparent',
              color: on ? 'var(--text-0)' : 'var(--text-2)',
              boxShadow: on ? 'var(--shadow-sm)' : 'none',
              whiteSpace: 'nowrap',
              textAlign: 'center',
              transition: 'all 0.15s',
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
