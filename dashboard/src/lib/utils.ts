// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/**
 * Standard shadcn cn() utility: Combines clsx conditionality with tailwind-merge deduping.
 */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
