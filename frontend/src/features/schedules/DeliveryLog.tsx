import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";

interface DeliveryLogProps {
  scheduleId: string;
}

const STATUS: Record<string, string> = {
  pending: "Waiting to retry",
  sent: "Sent",
  failed: "Failed",
};

/** Recent alert deliveries for one schedule: status, attempts, errors; never content. */
export function DeliveryLog({ scheduleId }: DeliveryLogProps) {
  const log = useQuery({
    queryKey: ["deliveries", scheduleId],
    queryFn: () => api.scheduleDeliveries(scheduleId),
  });
  const rows = log.data ?? [];
  if (log.isSuccess && !rows.length) {
    return <p className="text-text-muted">No alerts sent yet.</p>;
  }
  return (
    <table aria-label="Alert deliveries" className="text-sm">
      <tbody>
        {rows.map((d) => (
          <tr key={d.delivery_id} className="border-b border-border last:border-0">
            <td className="py-1 pr-6 font-mono text-text-secondary">
              {d.created_at.slice(0, 16).replace("T", " ")}
            </td>
            <td className="py-1 pr-6">{d.target_name ?? "Deleted target"}</td>
            <td className="py-1 pr-6">{d.kind}</td>
            <td
              className={`py-1 pr-6 ${d.status === "failed" ? "text-danger" : d.status === "pending" ? "text-warn" : ""}`}
            >
              {d.status === "pending" && d.attempts === 0 ? "Queued" : STATUS[d.status]}
              {d.attempts > 1 ? ` after ${d.attempts} tries` : ""}
            </td>
            <td className="py-1 text-text-secondary">{d.last_error ?? ""}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
