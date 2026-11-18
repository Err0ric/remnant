import { api } from "@/lib/api";
import { NumberSetting, type NumberValue } from "@/components/NumberSetting";

const minutes = (m: number): NumberValue => ({ value: m, min: 1, max: 1440 });

/** The live search time limit (ADR-0036 row 5): one setting for every role. */
export function LiveLimit({ canEdit }: { canEdit: boolean }) {
  return (
    <NumberSetting
      title="Live search time limit"
      help="A live search stops after this long and offers Resume, so a forgotten tab does not keep a query running. Everyone has the same limit and at most 2 live searches at once."
      unit="minutes"
      queryKey="live-limit"
      load={async () => minutes((await api.liveLimit()).minutes)}
      save={async (n) => minutes((await api.setLiveLimit(n)).minutes)}
      canEdit={canEdit}
    />
  );
}
