import * as React from 'react';

/**
 * DIMS threat-grade badge — the signature data element.
 * Grades per Наказ МО України № 46: F (background) → B → S → SS → SSS (critical).
 */
export interface GradeBadgeProps {
  /** Threat grade. F/B render cool; S amber; SS/SSS red escalation. */
  grade?: 'F' | 'B' | 'S' | 'SS' | 'SSS';
  size?: 'sm' | 'md' | 'lg';
  /** Optional R_DIMS value rendered beside the code, e.g. "0.78". */
  meta?: React.ReactNode;
  /** Appends a ⚑ escalation marker (use for SS/SSS). */
  flag?: boolean;
  title?: string;
  style?: React.CSSProperties;
}

export function GradeBadge(props: GradeBadgeProps): JSX.Element;
