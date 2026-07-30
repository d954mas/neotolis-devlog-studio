import { useEffect, useState } from "preact/hooks";

import type {
  ReviewFindingBody,
  ReviewTaskPack,
} from "./types";
import { reviewFrameEvidenceUrl } from "./types";

type FindingRegionEvidenceProps = {
  pack: ReviewTaskPack;
  finding: ReviewFindingBody;
};

type EvidenceState = "loading" | "ready" | "error";

export function FindingRegionEvidence({
  pack,
  finding,
}: FindingRegionEvidenceProps) {
  const [state, setState] = useState<EvidenceState>("loading");
  const [retryToken, setRetryToken] = useState(0);
  const locator = finding.locator;
  const region = locator?.region ?? null;
  const imageUrl =
    locator === null || locator === undefined || region === null
      ? null
      : reviewFrameEvidenceUrl(
          pack.artifact,
          locator.start_frame,
          160,
          region,
        );

  useEffect(() => {
    setState("loading");
  }, [imageUrl, retryToken]);

  if (imageUrl === null || locator === null || locator === undefined) {
    return null;
  }

  return (
    <figure class="finding-region-evidence">
      <div class={`finding-region-image state-${state}`}>
        {state === "loading" && (
          <span class="finding-region-skeleton" aria-hidden="true" />
        )}
        {state !== "error" && (
          <img
            key={`${imageUrl}:${retryToken}`}
            src={imageUrl}
            loading="lazy"
            alt={`Область прошлого замечания, кадр ${locator.start_frame}`}
            onLoad={() => setState("ready")}
            onError={() => setState("error")}
          />
        )}
        {state === "error" && (
          <button
            type="button"
            class="quiet"
            aria-label="Повторить превью области"
            onClick={() => setRetryToken((current) => current + 1)}
          >
            Повторить превью
          </button>
        )}
      </div>
      <figcaption>
        Область «До» · кадр {locator.start_frame}
      </figcaption>
    </figure>
  );
}
