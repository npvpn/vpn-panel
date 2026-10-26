/** Keep the same host when moving it; Extra belongs only to XHTTP transports. */
export function changeHostInbound<
  T extends { inbound_tag: string; xhttp_extra?: string | null }
>(host: T, tag: string, network?: string): T {
  if (tag === host.inbound_tag) return host;
  return {
    ...host,
    inbound_tag: tag,
    xhttp_extra: ["xhttp", "splithttp"].includes(network ?? "")
      ? host.xhttp_extra
      : "",
  };
}
