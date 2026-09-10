// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0
//
// Adapted from the shadcn/aceternity sidebar component.
// Next.js-specific APIs (next/link, next/image) replaced with
// react-router-dom equivalents for this Vite project.

import { cn } from '../../lib/utils';
import { NavLink, type NavLinkProps } from 'react-router-dom';
import React, { useState, createContext, useContext } from 'react';
import { AnimatePresence, motion } from 'framer-motion';
import { Menu, X } from 'lucide-react';

export interface SidebarLinkDef {
  label: string;
  href: string;
  icon: React.JSX.Element | React.ReactNode;
  /** Optional badge count rendered on the link */
  badge?: number;
  /** If true, require exact path match for active state */
  end?: boolean;
}

interface SidebarContextProps {
  open: boolean;
  setOpen: React.Dispatch<React.SetStateAction<boolean>>;
  animate: boolean;
}

const SidebarContext = createContext<SidebarContextProps | undefined>(undefined);

export const useSidebar = () => {
  const context = useContext(SidebarContext);
  if (!context) {
    throw new Error('useSidebar must be used within a SidebarProvider');
  }
  return context;
};

export const SidebarProvider = ({
  children,
  open: openProp,
  setOpen: setOpenProp,
  animate = true,
}: {
  children: React.ReactNode;
  open?: boolean;
  setOpen?: React.Dispatch<React.SetStateAction<boolean>>;
  animate?: boolean;
}) => {
  const [openState, setOpenState] = useState(false);

  const open = openProp !== undefined ? openProp : openState;
  const setOpen = setOpenProp !== undefined ? setOpenProp : setOpenState;

  return (
    <SidebarContext.Provider value={{ open, setOpen, animate }}>
      {children}
    </SidebarContext.Provider>
  );
};

export const Sidebar = ({
  children,
  open,
  setOpen,
  animate,
}: {
  children: React.ReactNode;
  open?: boolean;
  setOpen?: React.Dispatch<React.SetStateAction<boolean>>;
  animate?: boolean;
}) => {
  return (
    <SidebarProvider open={open} setOpen={setOpen} animate={animate}>
      {children}
    </SidebarProvider>
  );
};

export const SidebarBody = (props: React.ComponentProps<typeof motion.div>) => {
  return (
    <>
      <DesktopSidebar {...props} />
      <MobileSidebar {...(props as React.ComponentProps<'div'>)} />
    </>
  );
};

export const DesktopSidebar = ({
  className,
  children,
  ...props
}: React.ComponentProps<typeof motion.div>) => {
  const { open, setOpen, animate } = useSidebar();
  return (
    <motion.div
      className={cn('ariadne-sidebar-desktop', className)}
      animate={{
        width: animate ? (open ? '220px' : '56px') : '220px',
      }}
      transition={{ duration: 0.25, ease: [0.4, 0, 0.2, 1] }}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      {...props}
    >
      {children}
    </motion.div>
  );
};

export const MobileSidebar = ({
  className,
  children,
  ...props
}: React.ComponentProps<'div'>) => {
  const { open, setOpen } = useSidebar();
  return (
    <>
      <div className={cn('ariadne-sidebar-mobile-trigger')} {...props}>
        <button
          className="ariadne-sidebar-hamburger"
          onClick={() => setOpen(!open)}
          aria-label="Open navigation"
        >
          <Menu size={20} />
        </button>
        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ x: '-100%', opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: '-100%', opacity: 0 }}
              transition={{ duration: 0.28, ease: 'easeInOut' }}
              className={cn('ariadne-sidebar-mobile-overlay', className)}
            >
              <button
                className="ariadne-sidebar-close"
                onClick={() => setOpen(false)}
                aria-label="Close navigation"
              >
                <X size={20} />
              </button>
              {children}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </>
  );
};

export const SidebarLink = ({
  link,
  className,
}: {
  link: SidebarLinkDef;
  className?: string;
  props?: Omit<NavLinkProps, 'to'>;
}) => {
  const { open, animate } = useSidebar();
  const hasBadge = link.badge !== undefined && link.badge > 0;

  return (
    <NavLink
      to={link.href}
      end={link.end}
      title={link.label}
      className={({ isActive }) =>
        cn('ariadne-sidebar-link', isActive && 'active', className)
      }
    >
      <span className="ariadne-sidebar-link-icon">
        {link.icon}
        {hasBadge && !open && (
          <span className="ariadne-sidebar-link-dot" />
        )}
      </span>
      <motion.span
        animate={{
          display: animate ? (open ? 'inline-flex' : 'none') : 'inline-flex',
          opacity: animate ? (open ? 1 : 0) : 1,
        }}
        transition={{ duration: 0.18, ease: 'easeInOut' }}
        className="ariadne-sidebar-link-label"
      >
        <span>{link.label}</span>
        {hasBadge && (
          <span className="ariadne-sidebar-link-badge">{link.badge}</span>
        )}
      </motion.span>
    </NavLink>
  );
};
