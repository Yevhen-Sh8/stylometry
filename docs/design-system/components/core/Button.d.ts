import * as React from 'react';

/** Primary workspace action control. Use for any clickable command. */
export interface ButtonProps {
  children?: React.ReactNode;
  /** Visual weight. `primary` is the signal-blue CTA; `ghost` for low-emphasis. */
  variant?: 'default' | 'primary' | 'secondary' | 'ghost';
  /** Control height. `large` (44px) is the minimum touch target. */
  size?: 'xs' | 'sm' | 'md' | 'large';
  iconLeft?: React.ReactNode;
  iconRight?: React.ReactNode;
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  style?: React.CSSProperties;
  onClick?: (e: React.MouseEvent<HTMLButtonElement>) => void;
}

export function Button(props: ButtonProps): JSX.Element;
