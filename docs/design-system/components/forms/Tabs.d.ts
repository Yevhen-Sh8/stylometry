import * as React from 'react';

/**
 * Segmented pill tab switcher (controlled). Renders the tab bar only —
 * you own the panel content.
 *
 * @startingPoint section="Forms" subtitle="Segmented pill tabs" viewport="700x120"
 */
export interface TabItem {
  id: string;
  label: React.ReactNode;
}

export interface TabsProps {
  tabs?: TabItem[];
  /** Active tab id (controlled). Defaults to the first tab. */
  active?: string;
  onChange?: (id: string) => void;
  style?: React.CSSProperties;
}

export function Tabs(props: TabsProps): JSX.Element;
