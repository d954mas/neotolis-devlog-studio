import { useState } from "preact/hooks";

interface NodeProps {
  keyName: string | null;
  value: unknown;
  depth: number;
  defaultOpenDepth: number;
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === "object" && v !== null && !Array.isArray(v);
}

function Leaf({ value }: { value: unknown }) {
  if (value === null) return <span class="json-null">null</span>;
  switch (typeof value) {
    case "string":
      return <span class="json-string">"{value}"</span>;
    case "number":
      return <span class="json-number">{String(value)}</span>;
    case "boolean":
      return <span class="json-bool">{String(value)}</span>;
    default:
      return <span class="json-null">{String(value)}</span>;
  }
}

function JsonNode({ keyName, value, depth, defaultOpenDepth }: NodeProps) {
  const branch = isObject(value) || Array.isArray(value);
  const [open, setOpen] = useState(depth < defaultOpenDepth);

  if (!branch) {
    return (
      <div class="json-node">
        <span class="json-toggle" />
        {keyName !== null && <span class="json-key">{keyName}: </span>}
        <Leaf value={value} />
      </div>
    );
  }

  const entries: Array<[string, unknown]> = Array.isArray(value)
    ? value.map((v, i) => [String(i), v])
    : Object.entries(value as Record<string, unknown>);
  const open_b = Array.isArray(value) ? "[" : "{";
  const close_b = Array.isArray(value) ? "]" : "}";
  const summary = Array.isArray(value)
    ? `${entries.length} items`
    : `${entries.length} keys`;

  return (
    <div class="json-node">
      <div onClick={() => setOpen((o) => !o)} style={{ cursor: "pointer" }}>
        <span class="json-toggle">{open ? "▾" : "▸"}</span>
        {keyName !== null && <span class="json-key">{keyName}: </span>}
        <span>{open_b}</span>
        {!open && (
          <>
            {" "}
            <span class="json-summary">{summary}</span> <span>{close_b}</span>
          </>
        )}
      </div>
      {open && (
        <div class="json-children">
          {entries.map(([k, v]) => (
            <JsonNode
              key={k}
              keyName={k}
              value={v}
              depth={depth + 1}
              defaultOpenDepth={defaultOpenDepth}
            />
          ))}
          <div>
            <span class="json-toggle" />
            <span>{close_b}</span>
          </div>
        </div>
      )}
    </div>
  );
}

interface Props {
  data: unknown;
  defaultOpenDepth?: number;
}

export function JsonTree({ data, defaultOpenDepth = 1 }: Props) {
  return (
    <div class="json-tree">
      <JsonNode
        keyName={null}
        value={data}
        depth={0}
        defaultOpenDepth={defaultOpenDepth}
      />
    </div>
  );
}
