// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { motion } from 'framer-motion';
import { useTheme } from '../hooks/useTheme';
import { useSidebar } from './ui/sidebar';
import { cn } from '../lib/utils';
import SkyToggle from './ui/sky-toggle';

export function ThemeToggle({ className }: { className?: string }) {
  const { theme, toggleTheme } = useTheme();
  const { open, animate } = useSidebar();

  const isDark = theme === 'dark';

  return (
    <div
      className={cn('ariadne-sidebar-theme-toggle', className)}
      title={isDark ? 'Switch to light mode' : 'Switch to dark mode'}
    >
      {/* Sky Day/Night Toggle */}
      <SkyToggle
        checked={isDark}
        onChange={toggleTheme}
        id="sidebar-sky-toggle"
      />

      {/* Animated label shown when sidebar is expanded */}
      <motion.div
        animate={{
          display: animate ? (open ? 'flex' : 'none') : 'flex',
          opacity: animate ? (open ? 1 : 0) : 1,
        }}
        transition={{ duration: 0.18, ease: 'easeInOut' }}
        className="ariadne-sidebar-theme-content"
        style={{ pointerEvents: 'none' }}
      >
        <span className="theme-toggle-label">
          {isDark ? 'Dark Mode' : 'Light Mode'}
        </span>
      </motion.div>
    </div>
  );
}
