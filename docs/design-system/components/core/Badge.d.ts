import * as React from 'react';

/** Compact mono label or count chip. For threat grades use GradeBadge instead. */
export interface BadgeProps {
  children?: React.ReactNode;
  /** Semantic tone — tints text, fill and border together. */
  tone?: 'neutral' | 'ok' | 'warn' | 'danger' | 'info';
  style?: React.CSSProperties;
}

export function Badge(props: BadgeProps): JSX.Element;
