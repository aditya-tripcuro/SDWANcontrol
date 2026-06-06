import React, { createContext, useContext, useState } from "react";

const STORAGE_KEY = "wancontrol_timezone";

export const TIMEZONE_LIST = [
  { label: "UTC", value: "UTC" },
  { label: "US Eastern (New York)", value: "America/New_York" },
  { label: "US Central (Chicago)", value: "America/Chicago" },
  { label: "US Mountain (Denver)", value: "America/Denver" },
  { label: "US Pacific (Los Angeles)", value: "America/Los_Angeles" },
  { label: "US Alaska", value: "America/Anchorage" },
  { label: "US Hawaii", value: "Pacific/Honolulu" },
  { label: "Brazil (São Paulo)", value: "America/Sao_Paulo" },
  { label: "UK (London)", value: "Europe/London" },
  { label: "France (Paris)", value: "Europe/Paris" },
  { label: "Germany (Berlin)", value: "Europe/Berlin" },
  { label: "Russia (Moscow)", value: "Europe/Moscow" },
  { label: "Egypt (Cairo)", value: "Africa/Cairo" },
  { label: "South Africa (Johannesburg)", value: "Africa/Johannesburg" },
  { label: "India (Kolkata)", value: "Asia/Kolkata" },
  { label: "UAE (Dubai)", value: "Asia/Dubai" },
  { label: "Pakistan (Karachi)", value: "Asia/Karachi" },
  { label: "Bangladesh (Dhaka)", value: "Asia/Dhaka" },
  { label: "Thailand (Bangkok)", value: "Asia/Bangkok" },
  { label: "Singapore", value: "Asia/Singapore" },
  { label: "China (Shanghai)", value: "Asia/Shanghai" },
  { label: "Japan (Tokyo)", value: "Asia/Tokyo" },
  { label: "Korea (Seoul)", value: "Asia/Seoul" },
  { label: "Indonesia (Jakarta)", value: "Asia/Jakarta" },
  { label: "Australia (Sydney)", value: "Australia/Sydney" },
  { label: "Australia (Melbourne)", value: "Australia/Melbourne" },
  { label: "Australia (Perth)", value: "Australia/Perth" },
  { label: "New Zealand (Auckland)", value: "Pacific/Auckland" },
];

interface TimezoneContextType {
  timezone: string;
  setTimezone: (tz: string) => void;
  formatTs: (ts: number, options?: Intl.DateTimeFormatOptions) => string;
}

const TimezoneContext = createContext<TimezoneContextType>({
  timezone: "UTC",
  setTimezone: () => {},
  formatTs: (ts) => new Date(ts * 1000).toLocaleString(),
});

export const TimezoneProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [timezone, setTimezoneState] = useState<string>(
    () => localStorage.getItem(STORAGE_KEY) || "UTC"
  );

  const setTimezone = (tz: string) => {
    localStorage.setItem(STORAGE_KEY, tz);
    setTimezoneState(tz);
  };

  const formatTs = (ts: number, options?: Intl.DateTimeFormatOptions) =>
    new Intl.DateTimeFormat("en-US", { timeZone: timezone, ...options }).format(new Date(ts * 1000));

  return (
    <TimezoneContext.Provider value={{ timezone, setTimezone, formatTs }}>
      {children}
    </TimezoneContext.Provider>
  );
};

export const useTimezone = () => useContext(TimezoneContext);
