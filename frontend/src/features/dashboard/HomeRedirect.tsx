import { useQuery } from "@tanstack/react-query";
import { useEffect } from "react";
import { api } from "@/lib/api";
import { redirect } from "@/lib/route";

/** The root address (ADR-0031): the Dashboard when the viewer sees at least one panel,
 * the Overview otherwise, including when the list cannot be loaded. */
export function HomeRedirect() {
  const schedules = useQuery({ queryKey: ["schedules"], queryFn: api.schedules });
  useEffect(() => {
    if (schedules.isSuccess) redirect(schedules.data.length > 0 ? "dashboard" : "overview");
    else if (schedules.isError) redirect("overview");
  }, [schedules.isSuccess, schedules.isError, schedules.data]);
  return <div aria-busy="true" className="flex-1" />;
}
