# Ariadne — AI Agent Provenance Firewall & Drift Guardrail

> **Interactive Landing Page & Threat Showcase** for Ariadne: The real-time inline proxy protecting autonomous AI agents executing tool calls at the `/mcp` boundary.

---

## 🌟 Modern TypeScript Architecture

The landing page is fully implemented as an enterprise-grade **TypeScript React (`.tsx`)** component, complete with strong typing, event hooks, and reactive UI states.

### 📦 Component & Types Export

```tsx
import { Landing } from './Landing';
import type { 
  LandingProps, 
  ViewMode, 
  ArtworkMode, 
  TourTab, 
  ScenarioId, 
  ThreatScenario, 
  HitlStatus 
} from './types';

export default function Page() {
  return (
    <Landing
      initialViewMode="dribbble"
      initialArtworkMode="live"
      onSignInClick={() => console.log('Go to login')}
      onLaunchDashboard={() => console.log('Go to dashboard')}
    />
  );
}
```

---

## 🌟 Highlights & Architecture Showcase

1. **Interactive Constellation Pipeline**:
   - **Intent Anchor (Yellow Squircle)**: Vector mission baseline embedded via `sentence-transformers/all-MiniLM-L6-v2`.
   - **Autonomous Agent Caller (Avatar)**: LLMs (Claude 3.5, GPT-4o, LangGraph, AutoGPT) dispatching tool executions.
   - **Trajectory & Slope Scorer (Cyan Squircle)**: Least-squares regression slope over 5-step sliding window with R² trend confidence discount.
   - **Ariadne Core Gateway (Center Purple Squircle)**: Inline proxy evaluating hard policies and the 4-tier graduated verdict ladder.
   - **Hard Policy Shield (Red Squircle)**: Zero-tolerance immediate blocking of privilege escalation (`grant_role`, `sudo`), destructive operations (`rm -rf`, `drop table`), and human approval on fund transfers.
   - **Human-in-the-Loop Operator (Avatar)**: Cryptographic single-use approval token workflow for quarantined sensitive actions.
   - **Live Sentinel Eye**: Dynamic cursor-tracking pupil surveillance monitoring real-time agent telemetry and generating deterministic drift narratives.

2. **Dual Presentation Views**:
   - **Showcase Card View**: Framed presentation card with soft shadow and claymorphic accents.
   - **Full Page Experience**: Expands to a responsive SaaS security product page.

3. **Core Architectural Sections**:
   - **Ecosystem Strip**: Model Context Protocol (MCP), Anthropic Claude, LangChain, CrewAI, AutoGPT, OpenAI Swarm, LlamaIndex.
   - **Modular Bento Grid**:
     - *Trajectory & Slope Drift Scorer*: Distinguishing one-off exploratory lookups from escalating slow-burn prompt injections.
     - *4-Tier Graduated Ladder*: ALLOW (<40), WARN (≥40), ESCALATE (≥66.5), and BLOCK (≥86.5).
     - *Deterministic Narrative Engine*: Rule-based plain-English explanations with zero LLM hallucinations in the hot path.
     - *5-Dimensional Risk Engine*: Intent drift, Contextual Tool Risk, Provenance Privilege Escalation, Identity Heuristics, and Sensitive Data (PII/tokens).
   - **Interactive Threat & Interception Tour**:
     - Live MCP Interceptor: Test Scenario A (Privilege Escalation -> BLOCKED), Scenario B (Slow-Burn Goal Hijack -> ESCALATE), and Scenario C (Benign Order Query -> ALLOW).
     - Trajectory & Slope: Visual step-by-step drift cards showing slope calculation and R² fit gating.
     - Human-in-the-Loop (HITL) Queue: Real-time authorization card with interactive "Sign & Approve Token" and "Block & Revoke Session" workflows.
     - Policy Backtester & Provenance: Replaying candidate threshold changes across 138+ recorded red-team sessions with measured 0.0% FPR.
   - **Security Comparison Matrix**: Side-by-side technical evaluation against prompt-only LLM guardrails (LlamaGuard, NeMo).
   - **Deployment Pricing**: Developer / Open Source, Production Team ($49/mo or $39/mo annual), and Enterprise Guardrail.
   - **Technical FAQ**: Addressing interception latency (<15ms), slope regression mechanics, FAIL_CLOSED posture, and policy backtesting.
   - **Interactive Sandbox Modal**: Instant API gateway provisioning and quickstart curl command.

---

## 📁 File Structure

- [`Landing.tsx`](file:///d:/Projects/Notes/jist/frontend/frontend/Landing.tsx): Modern, typed React component with full state hooks, pupil tracking physics, 3D parallax, threat simulations, and modal handlers.
- [`types.ts`](file:///d:/Projects/Notes/jist/frontend/frontend/types.ts): TypeScript type definitions, scenario interfaces, view modes, and component props.
- [`index.ts`](file:///d:/Projects/Notes/jist/frontend/frontend/index.ts): Main library export for `@ariadne/landing`.
- [`package.json`](file:///d:/Projects/Notes/jist/frontend/frontend/package.json): Package manifest for consumption within any TypeScript/React workspace.
- [`tsconfig.json`](file:///d:/Projects/Notes/jist/frontend/frontend/tsconfig.json): TypeScript compiler configuration targeting ES2020 + React JSX.
- [`style.css`](file:///d:/Projects/Notes/jist/frontend/frontend/style.css): Custom Urbanist design system, claymorphic 3D styling, responsive breakpoints, and keyframe animations.
- [`index.html`](file:///d:/Projects/Notes/jist/frontend/frontend/index.html): Legacy standalone HTML5 version.
- [`script.js`](file:///d:/Projects/Notes/jist/frontend/frontend/script.js): Legacy vanilla JS script.
- [`server.js`](file:///d:/Projects/Notes/jist/frontend/frontend/server.js): Zero-dependency Node.js static file server for testing legacy HTML.
