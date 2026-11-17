/** The longest SQL Logs, saved searches, and the API take as typed SQL (the server's
 * `MAX_TYPED_SQL`). A library query the server builds from the AI catalog can be longer:
 * it still answers in Ask AI, by id, but cannot open in Logs. */
export const MAX_TYPED_SQL = 20_000;

/** Whether this SQL can open in the Logs SQL mode. */
export function fitsInLogs(sql: string): boolean {
  return sql.length <= MAX_TYPED_SQL;
}

/** The plain reason shown beside a link that cannot open its SQL in Logs. */
export const TOO_LONG_FOR_LOGS = `This SQL is longer than the ${MAX_TYPED_SQL.toLocaleString("en-US")} characters Logs takes.`;
