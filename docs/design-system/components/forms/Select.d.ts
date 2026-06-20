import * as React from 'react';

/** Labelled native dropdown styled to match DIMS form controls. */
export interface SelectOption {
  value: string;
  label: string;
}

export interface SelectProps {
  label?: React.ReactNode;
  hint?: React.ReactNode;
  value?: string;
  /** Array of `{value,label}` objects or plain strings. */
  options?: Array<SelectOption | string>;
  id?: string;
  disabled?: boolean;
  style?: React.CSSProperties;
  onChange?: (e: React.ChangeEvent<HTMLSelectElement>) => void;
}

export function Select(props: SelectProps): JSX.Element;
