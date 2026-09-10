// Copyright 2026 The Ariadne Authors
// SPDX-License-Identifier: Apache-2.0

import { cn } from "@/lib/utils";
import { useState } from "react";

export interface AuthSwitchProps {
  className?: string;
  activeTab?: "credentials" | "demo";
  onTabChange?: (tab: "credentials" | "demo") => void;
  showCounter?: boolean;
}

export const Component = ({
  className,
  activeTab = "credentials",
  onTabChange,
  showCounter = false,
}: AuthSwitchProps = {}) => {
  const [count, setCount] = useState(0);
  const [internalTab, setInternalTab] = useState<"credentials" | "demo">(activeTab);

  const currentTab = onTabChange ? activeTab : internalTab;

  const handleSelect = (tab: "credentials" | "demo") => {
    setInternalTab(tab);
    onTabChange?.(tab);
  };

  return (
    <div className={cn("flex flex-col items-center gap-3 w-full", className)}>
      <div
        className="auth-switch-container flex w-full p-1 rounded-xl"
        style={{
          background: "rgba(15, 23, 42, 0.5)",
          border: "1px solid rgba(124, 58, 237, 0.2)",
          backdropFilter: "blur(12px)",
        }}
      >
        <button
          type="button"
          onClick={() => handleSelect("credentials")}
          className={cn(
            "flex-1 py-2 px-3 text-xs font-semibold rounded-lg transition-all duration-200 cursor-pointer text-center",
            currentTab === "credentials"
              ? "bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md shadow-violet-500/20"
              : "text-slate-400 hover:text-slate-200 bg-transparent border-0"
          )}
          style={
            currentTab === "credentials"
              ? {
                  background: "linear-gradient(135deg, #7C3AED 0%, #4F46E5 100%)",
                  color: "#FFFFFF",
                  boxShadow: "0 4px 12px rgba(124, 58, 237, 0.35)",
                }
              : { color: "var(--text-dim)", background: "transparent" }
          }
        >
          Operator Sign In
        </button>
        <button
          type="button"
          onClick={() => handleSelect("demo")}
          className={cn(
            "flex-1 py-2 px-3 text-xs font-semibold rounded-lg transition-all duration-200 cursor-pointer text-center",
            currentTab === "demo"
              ? "bg-gradient-to-r from-violet-600 to-indigo-600 text-white shadow-md shadow-violet-500/20"
              : "text-slate-400 hover:text-slate-200 bg-transparent border-0"
          )}
          style={
            currentTab === "demo"
              ? {
                  background: "linear-gradient(135deg, #7C3AED 0%, #4F46E5 100%)",
                  color: "#FFFFFF",
                  boxShadow: "0 4px 12px rgba(124, 58, 237, 0.35)",
                }
              : { color: "var(--text-dim)", background: "transparent" }
          }
        >
          Quick Demo Fill
        </button>
      </div>

      {showCounter && (
        <div
          className="flex items-center justify-between w-full px-3 py-2 rounded-lg text-xs"
          style={{ background: "rgba(124, 58, 237, 0.08)", border: "1px solid rgba(124, 58, 237, 0.15)" }}
        >
          <span style={{ color: "var(--text-muted)" }}>Component Counter:</span>
          <div className="flex items-center gap-2">
            <span style={{ fontWeight: 700, color: "#A78BFA" }}>{count}</span>
            <div className="flex gap-1">
              <button
                type="button"
                className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold cursor-pointer"
                style={{
                  background: "rgba(255, 255, 255, 0.08)",
                  border: "1px solid rgba(255, 255, 255, 0.12)",
                  color: "var(--text-bright)",
                }}
                onClick={() => setCount((prev) => prev - 1)}
              >
                -
              </button>
              <button
                type="button"
                className="w-6 h-6 rounded flex items-center justify-center text-xs font-bold cursor-pointer"
                style={{
                  background: "rgba(255, 255, 255, 0.08)",
                  border: "1px solid rgba(255, 255, 255, 0.12)",
                  color: "var(--text-bright)",
                }}
                onClick={() => setCount((prev) => prev + 1)}
              >
                +
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export const AuthSwitch = Component;
export default Component;
