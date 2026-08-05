import { useEffect, useState } from "preact/hooks";
import { studioV3 } from "../api/v3.client";
import type { components } from "../api/v3.gen";

export type DeliveryContext = components["schemas"]["DeliveryContext"];

export function useDeliveryContext(
  enabled: boolean,
  workflowRevision: number | undefined,
  onError: (message: string | null) => void,
): DeliveryContext | null {
  const [context, setContext] = useState<DeliveryContext | null>(null);

  useEffect(() => {
    if (!enabled) {
      setContext(null);
      return;
    }
    let active = true;
    setContext(null);
    void studioV3.GET("/api/v3/delivery/context").then((result) => {
      if (!active) return;
      if (!result.data) {
        onError("Не удалось загрузить точный состав release package.");
        return;
      }
      setContext(result.data);
    }).catch((cause: unknown) => {
      if (active) {
        onError(cause instanceof Error ? cause.message : String(cause));
      }
    });
    return () => {
      active = false;
    };
  }, [enabled, workflowRevision]);

  return context;
}
