import { Select } from "@/components/forms/Select";
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
      <Select
        aria-label={`Model for ${providerName}`}
        className="h-7 max-w-[16rem] font-mono text-sm"
        optionClassName="font-mono"
        value={model}
        disabled={saving}
        onChange={(v) => {
          if (v) onChoose(v);
        }}
        placeholder={model ? undefined : "Choose a model"}
        options={options.map((m) => ({ value: m, label: m }))}
      />
    );
  }
  if (model) return <span className="font-mono">{model}</span>;
  return <span className="text-text-muted">No model chosen. Test to list models.</span>;
}
