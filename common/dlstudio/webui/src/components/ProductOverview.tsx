import type { ProductOverview as ProductOverviewData } from "../api/types";

export interface ProductOverviewProps {
  product: ProductOverviewData;
}

export function ProductOverview({ product }: ProductOverviewProps) {
  return (
    <section class="product-overview" aria-label="Product productions">
      <span class="product-title">{product.title}</span>
      <div class="production-list">
        {product.productions.map((production) => (
          <span
            key={production.id}
            class={"production-chip" + (production.current ? " current" : "")}
            title={`Open with: dl2 studio ${production.studio_ref}`}
          >
            <b>{production.kind === "devlog" ? "DEVLOG" : "REEL"}</b>
            <span>{production.id.slice(0, 10)}</span>
            {production.current && <em>open</em>}
          </span>
        ))}
      </div>
    </section>
  );
}
