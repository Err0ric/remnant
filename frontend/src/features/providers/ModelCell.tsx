interface ModelCellProps {
  providerName: string;
  model: string;
  /** Models from the last Test; empty until the provider has been tested. */
  models: string[];
  saving: boolean;
  onChoose: (model: string) => void;
}

/** The Model column: the saved model, or a picker once Test has listed what the server has. */
export function ModelCell({ providerName, model, models, saving, onChoose }: ModelCellProps) {
  if (models.length) {
    const options = models.includes(model) || !model ? models : [model, ...models];
    return (
      <select
        aria-label={`Model for ${providerName}`}
        className="h-7 max-w-[16rem] rounded border border-border bg-surface px-1 font-mono text-sm"
        value={model}
        disabled={saving}
        onChange={(e) => {
          if (e.target.value) onChoose(e.target.value);
        }}
      >
        {model ? null : <option value="">Choose a model</option>}
        {options.map((m) => (
          <option key={m} value={m}>
            {m}
          </option>
        ))}
      </select>
    );
  }
  if (model) return <span className="font-mono">{model}</span>;
  return <span className="text-text-muted">No model chosen. Test to list models.</span>;
}
