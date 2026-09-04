import { useState, useEffect, useCallback } from "react";
import { HealthResponse } from "../types";
import { checkBackendHealth } from "../services/api";

export type HealthStatus = "checking" | "online" | "unavailable";

export function useBackendHealth() {
  const [status, setStatus] = useState<HealthStatus>("checking");
  const [healthData, setHealthData] = useState<HealthResponse | null>(null);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [lastChecked, setLastChecked] = useState<Date | null>(null);

  const check = useCallback(async (isInitial = false) => {
    const startTime = performance.now();
    try {
      if (isInitial) {
        setStatus("checking");
      }
      const data = await checkBackendHealth(isInitial ? 4500 : 3000);
      const elapsed = Math.round(performance.now() - startTime);

      setHealthData(data);
      setLatencyMs(elapsed);
      setStatus("online");
      setErrorMessage(null);
      setLastChecked(new Date());
    } catch (err: unknown) {
      setStatus("unavailable");
      setHealthData(null);
      setLatencyMs(null);
      setLastChecked(new Date());
      const msg = err instanceof Error ? err.message : "Connection refused";
      setErrorMessage(
        `Local FastAPI backend at 127.0.0.1:24823 did not respond. (${msg})`
      );
    }
  }, []);

  useEffect(() => {
    let mounted = true;
    let attempt = 0;
    const maxInitialRetries = 6;
    let initialTimer: ReturnType<typeof setTimeout>;

    // Retry aggressively during initial app startup (up to 5s window)
    const initialPoll = async () => {
      const startTime = performance.now();
      try {
        const data = await checkBackendHealth(1200);
        if (!mounted) return;
        setHealthData(data);
        setLatencyMs(Math.round(performance.now() - startTime));
        setStatus("online");
        setErrorMessage(null);
        setLastChecked(new Date());
      } catch (err: unknown) {
        if (!mounted) return;
        attempt++;
        if (attempt < maxInitialRetries) {
          initialTimer = setTimeout(initialPoll, 600);
        } else {
          setStatus("unavailable");
          setErrorMessage(
            "Local FastAPI backend failed to start within 5 seconds. Check port 24823 availability."
          );
          setLastChecked(new Date());
        }
      }
    };

    initialPoll();

    // Regular interval poll every 6 seconds (skips when hidden)
    const interval = setInterval(() => {
      if (mounted) {
        if (typeof document !== "undefined" && document.hidden) {
          return;
        }
        check(false);
      }
    }, 6000);

    const handleVisibility = () => {
      if (mounted && typeof document !== "undefined" && !document.hidden) {
        check(false);
      }
    };
    if (typeof document !== "undefined") {
      document.addEventListener("visibilitychange", handleVisibility);
    }

    return () => {
      mounted = false;
      clearTimeout(initialTimer);
      clearInterval(interval);
      if (typeof document !== "undefined") {
        document.removeEventListener("visibilitychange", handleVisibility);
      }
    };
  }, [check]);

  return {
    status,
    healthData,
    latencyMs,
    errorMessage,
    lastChecked,
    recheck: () => check(true),
  };
}
