// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

/**
 * Presentation view mode for the landing page.
 * - 'dribbble': Framed presentation showcase card with claymorphic accents.
 * - 'full': Responsive, full-width SaaS product landing page.
 */
export type ViewMode = 'dribbble' | 'full';

/**
 * Hero diagram display mode.
 * - 'live': Dynamic interactive vector graph with real-time node parallax.
 * - 'original': Architecture overview diagram detailing the provenance pipeline.
 */
export type ArtworkMode = 'live' | 'original';

/**
 * Active tab in the Interactive Threat Tour section.
 */
export type TourTab = 'interceptor' | 'trajectory' | 'hitl' | 'backtester';

/**
 * Threat scenario identifiers for live test harness demonstrations.
 */
export type ScenarioId = 'privilege' | 'goalHijack' | 'benign';

/**
 * Human-in-the-Loop authorization state.
 */
export type HitlStatus = 'pending' | 'approved' | 'rejected';

/**
 * Structured specification of a threat scenario in the live test harness.
 */
export interface ThreatScenario {
  id: ScenarioId;
  title: string;
  badge: 'BLOCKED' | 'ESCALATE' | 'ALLOW';
  badgeClass: 'tag-block' | 'tag-escalate' | 'tag-allow';
  intent: string;
  call: string;
  distance: string;
  slope: string;
  fitR2: string;
  driftScore: string;
  ruleTrigger: string;
  narrative: string;
}

/**
 * Props for the Landing component.
 */
export interface LandingProps {
  /**
   * Initial presentation view mode (default: 'dribbble').
   */
  initialViewMode?: ViewMode;
  /**
   * Initial constellation mode (default: 'live').
   */
  initialArtworkMode?: ArtworkMode;
  /**
   * Callback fired when user clicks 'Audit Logs' or 'Sign In'.
   */
  onSignInClick?: () => void;
  /**
   * Callback fired when user launches the dashboard.
   */
  onLaunchDashboard?: () => void;
  /**
   * Optional authentication status.
   */
  authStatus?: 'authenticated' | 'unauthenticated';
  /**
   * Custom CSS class name for the wrapper root.
   */
  className?: string;
}
