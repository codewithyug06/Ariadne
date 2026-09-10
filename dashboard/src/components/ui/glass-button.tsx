// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import React from 'react';

export interface GlassButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  size?: 'sm' | 'md' | 'lg';
  children: React.ReactNode;
}

export function GlassButton({
  size = 'md',
  className = '',
  children,
  ...props
}: GlassButtonProps) {
  const padding = size === 'sm' ? '8px 18px' : size === 'lg' ? '14px 28px' : '10px 22px';
  const fontSize = size === 'sm' ? '13px' : size === 'lg' ? '15px' : '14px';

  return (
    <div className={`glass-button-wrap ${className}`}>
      <div className="glass-button-shadow" />
      <button
        type="button"
        className="glass-button"
        style={{ padding, fontSize }}
        {...props}
      >
        <span className="glass-button-text">{children}</span>
      </button>
    </div>
  );
}
