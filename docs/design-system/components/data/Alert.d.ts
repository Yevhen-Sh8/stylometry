import * as React from 'react';

/** Left-ruled inline notice for warnings and contextual info. */
export interface AlertProps {
  children?: React.ReactNode;
  /** `critical` = red rule + danger title; `info` = teal rule. */
  tone?: 'info' | 'critical';
  /** Optional bold heading rendered in the tone color. */
  title?: React.ReactNode;
  style?: React.CSSProperties;
}

export function Alert(props: AlertProps): JSX.Element;
