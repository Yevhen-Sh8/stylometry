import * as React from 'react';

/**
 * A single KPI cell. Place several inside a 1px-gap grid (background:var(--border-0))
 * to build the results stats strip.
 */
export interface StatCardProps {
  value?: React.ReactNode;
  label?: React.ReactNode;
  /** Tints the numeral. Use danger/warn/ok to signal result severity. */
  tone?: 'default' | 'ok' | 'warn' | 'danger' | 'info';
  /** Extra node beside the value, e.g. a <GradeBadge/>. */
  children?: React.ReactNode;
  style?: React.CSSProperties;
}

export function StatCard(props: StatCardProps): JSX.Element;
