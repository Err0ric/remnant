import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { redirect } from "@/lib/route";

/** The root address (ADR-0031, ADR-0034): the Dashboard when a dashboard the viewer sees
 * has at least one panel, the Overview otherwise, including when the list cannot load. */
export function HomeRedirect() {
  const boards = useQuery({ queryKey: ["dashboards"], queryFn: api.dashboards });
  useEffect(() => {
    if (boards.isSuccess)
      redirect(boards.data.some((d) => d.panels.length > 0) ? "dashboard" : "overview");
    else if (boards.isError) redirect("overview");
  }, [boards.isSuccess, boards.isError, boards.data]);
  return <div aria-busy="true" className="flex-1" />;
}
