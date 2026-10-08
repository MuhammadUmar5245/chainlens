import { useQuery } from "@tanstack/react-query";
import { api } from "../api/client";
import type { Chain } from "../api/types";

/** Each chain keeps one colour everywhere, whatever else is selected (CSS tokens, light + dark). */
export const CHAIN_VAR: Record<string, string> = {
  btc: "--c-btc",
  eth: "--c-eth",
  ethw: "--c-ethw",
  etc: "--c-etc",
  sol: "--c-sol",
};

export const CHAIN_SHORT: Record<string, string> = { btc: "₿", eth: "Ξ", ethw: "W", etc: "C", sol: "S" };

/** Words that differ by chain family. */
export const unitWord = (family?: string) => (family === "solana" ? "slots" : "blocks");
export const callWord = (family?: string) => (family === "solana" ? "Program call" : family === "utxo" ? "Transfer" : "Contract call");

export const chainColorVar =(key: string) => `var(${CHAIN_VAR[key] ?? "--muted"})`;

export function chainColor(key: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(CHAIN_VAR[key] ?? "--muted");
  return v.trim() || "#888";
}

export function useChains() {
  return useQuery({ queryKey: ["chains"], queryFn: api.chains, staleTime: 60_000 });
}

export function chainMap(chains: Chain[] | undefined): Record<string, Chain> {
  return Object.fromEntries((chains ?? []).map((c) => [c.key, c]));
}

export const TAGS: Record<string, { label: string; rule: string }> = {
  whale: { label: "Whale", rule: "sent + received at or above the chain's whale threshold" },
  high_frequency_bot: { label: "Likely bot", rule: "top 5% of senders and at least 1.5 tx per active block" },
  hub_exchange_like: { label: "Hub / exchange-like", rule: "top 1% by number of counterparties" },
  contract_heavy: { label: "Contract-heavy", rule: "at least 3 sent, 90% or more of them contract calls" },
  one_off: { label: "One-off", rule: "exactly one transaction in the sample" },
};
export const tagLabel = (t: string) => TAGS[t]?.label ?? t;
