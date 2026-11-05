/** CloudWatch Embedded Metric Format: one structured log line becomes a custom metric. No extra IAM, never contains message text or identifiers. */
export const NAMESPACE = "FtusaExchange";
export function emf(name: string, value = 1, unit = "Count", dims: Record<string, string> = {}): void {
  console.log(JSON.stringify({ _aws: { Timestamp: Date.now(), CloudWatchMetrics: [{ Namespace: NAMESPACE, Dimensions: [Object.keys(dims)], Metrics: [{ Name: name, Unit: unit }] }] }, [name]: value, ...dims }));
}
