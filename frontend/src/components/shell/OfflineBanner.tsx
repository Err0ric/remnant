import { useConnectivity } from "@/lib/connectivity";

function hhmm(d: Date): string {
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** F40: when the server stops answering, say so and how old the page's data is. Pages keep
 * what they last loaded; the banner goes away on the next answer. */
export function OfflineBanner() {
  const { downSince, lastOkAt } = useConnectivity();
  if (!downSince) return null;
  return (
    <div
      role="alert"
      className="sticky top-12 z-20 flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-warn bg-surface px-5 py-1.5 text-sm"
    >
      <span className="font-semibold text-warn">Can't reach the server</span>
      <span className="text-text-secondary">
        {lastOkAt
          ? `Showing data from ${hhmm(lastOkAt)}. Retrying in the background.`
          : "Retrying in the background."}
      </span>
    </div>
  );
}
