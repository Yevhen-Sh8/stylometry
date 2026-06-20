import * as React from 'react';

/**
 * One ingested document in the left-panel corpus list: a type badge,
 * title, mono metadata line, and remove control.
 */
export interface SourceItemProps {
  label?: React.ReactNode;
  /** Mono sub-line, e.g. "tass.ru · 1 240 ток. · 14:02". */
  meta?: React.ReactNode;
  /** Ingest channel — colors the leading badge. */
  type?: 'TXT' | 'PDF' | 'URL' | 'RSS' | 'TELEGRAM' | 'GOOGLE';
  /** Render the meta line in amber (e.g. under the 500-token floor). */
  warn?: boolean;
  onRemove?: () => void;
  style?: React.CSSProperties;
}

export function SourceItem(props: SourceItemProps): JSX.Element;
