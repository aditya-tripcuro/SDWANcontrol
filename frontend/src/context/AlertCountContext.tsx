import React, { createContext, useContext, useState } from "react";

interface AlertCountContextValue {
  unresolved: number;
  increment: () => void;
  decrement: () => void;
  setCount: (n: number) => void;
}

const AlertCountContext = createContext<AlertCountContextValue | undefined>(undefined);

export function useAlertCount() {
  const ctx = useContext(AlertCountContext);
  if (!ctx) throw new Error("useAlertCount must be used inside provider");
  return ctx;
}

export const AlertCountProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [unresolved, setUnresolved] = useState<number>(0);
  const increment = () => setUnresolved((n) => n + 1);
  const decrement = () => setUnresolved((n) => Math.max(0, n - 1));
  const setCount = (n: number) => setUnresolved(n);
  return (
    <AlertCountContext.Provider value={{ unresolved, increment, decrement, setCount }}>
      {children}
    </AlertCountContext.Provider>
  );
};
