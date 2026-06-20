import * as React from 'react';

/** Labelled text field (input or textarea) with optional hint line. */
export interface InputProps {
  label?: React.ReactNode;
  /** Helper text rendered below the control in tertiary color. */
  hint?: React.ReactNode;
  type?: string;
  /** Render a resizable multi-line textarea instead of a single-line input. */
  textarea?: boolean;
  /** Use JetBrains Mono — for URLs, code, raw text paste. */
  mono?: boolean;
  value?: string;
  placeholder?: string;
  disabled?: boolean;
  id?: string;
  style?: React.CSSProperties;
  onChange?: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => void;
}

export function Input(props: InputProps): JSX.Element;
