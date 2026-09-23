'use client'

import React, { createContext, useContext, useId, useRef, useCallback } from 'react';

type TabsContextType = {
  value: string;
  onValueChange: (value: string) => void;
  baseId: string;
};

const TabsContext = createContext<TabsContextType | null>(null);

export function Tabs({
  value,
  onValueChange,
  className = '',
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const baseId = useId();
  return (
    <TabsContext.Provider value={{ value, onValueChange, baseId }}>
      <div className={className}>{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({
  className = '',
  'aria-label': ariaLabel,
  children,
}: {
  className?: string;
  'aria-label'?: string;
  children: React.ReactNode;
}) {
  const listRef = useRef<HTMLDivElement>(null);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLDivElement>) => {
    const list = listRef.current;
    if (!list) return;
    const tabs = Array.from(list.querySelectorAll<HTMLButtonElement>('[role="tab"]:not([disabled])'));
    const activeIndex = tabs.findIndex((t) => t === document.activeElement);
    if (activeIndex < 0) return;

    let nextIndex = activeIndex;
    if (e.key === 'ArrowRight') nextIndex = (activeIndex + 1) % tabs.length;
    else if (e.key === 'ArrowLeft') nextIndex = (activeIndex - 1 + tabs.length) % tabs.length;
    else if (e.key === 'Home') nextIndex = 0;
    else if (e.key === 'End') nextIndex = tabs.length - 1;
    else return;

    e.preventDefault();
    tabs[nextIndex]?.focus();
    tabs[nextIndex]?.click();
  }, []);

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      className={className}
    >
      {children}
    </div>
  );
}

export function TabsTrigger({
  value,
  className = '',
  children,
  disabled,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
  disabled?: boolean;
}) {
  const ctx = useContext(TabsContext);
  if (!ctx) return null;
  const isActive = ctx.value === value;

  return (
    <button
      type="button"
      role="tab"
      id={`${ctx.baseId}-tab-${value}`}
      aria-selected={isActive}
      aria-controls={`${ctx.baseId}-panel-${value}`}
      tabIndex={isActive ? 0 : -1}
      disabled={disabled}
      onClick={() => ctx.onValueChange(value)}
      className={`${className} px-3 py-2 rounded-md text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 ${
        isActive ? 'bg-slate-900 text-white' : 'text-slate-600 hover:bg-slate-100'
      } ${disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
    >
      {children}
    </button>
  );
}

export function TabsContent({
  value,
  className = '',
  children,
}: {
  value: string;
  className?: string;
  children: React.ReactNode;
}) {
  const ctx = useContext(TabsContext);
  if (!ctx || ctx.value !== value) return null;
  return (
    <div
      role="tabpanel"
      id={`${ctx.baseId}-panel-${value}`}
      aria-labelledby={`${ctx.baseId}-tab-${value}`}
      tabIndex={0}
      className={className}
    >
      {children}
    </div>
  );
}
