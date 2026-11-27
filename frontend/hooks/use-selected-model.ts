"use client";

import { useCallback, useSyncExternalStore } from "react";

import { useModels, usePreferences } from "@/hooks/queries";

const STORAGE_KEY = "kaygpt.selected_model";
const listeners = new Set<() => void>();

function read(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY);
  } catch {
    return null;
  }
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Model chosen in the composer. Remembered per browser (like the original UI), falling back to
 * the user's saved default and then the server default. Unknown/retired ids are ignored.
 */
export function useSelectedModel() {
  const models = useModels();
  const preferences = usePreferences();
  const stored = useSyncExternalStore(subscribe, read, () => null);

  const available = models.data?.models ?? [];
  const isValid = (id: string | null | undefined): id is string =>
    !!id && available.some((m) => m.id === id);

  const selected = isValid(stored)
    ? stored
    : isValid(preferences.data?.default_model)
      ? preferences.data.default_model
      : (models.data?.default_model ?? null);

  const setSelected = useCallback((id: string) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, id);
    } catch {
      /* storage unavailable: selection lasts for this render only */
    }
    listeners.forEach((l) => l());
  }, []);

  return { selected, setSelected, models: available, isLoading: models.isLoading };
}
