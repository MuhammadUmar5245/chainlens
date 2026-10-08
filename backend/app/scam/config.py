"""Settings for scam tracing. New keys only; the existing app settings are untouched.

Each field maps to a dotted key from the requirements and reads an environment variable of the same
name in upper case, e.g. scam.poison.real_min_eth -> SCAM_POISON_REAL_MIN_ETH.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_WEIGHTS = {
    "D1": 0.9,   # address poisoning
    "D2": 0.5,   # pass-through
    "D3": 0.6,   # hop chain
    "D4": 0.4,   # collector
    "D5": 0.4,   # distributor
    "D6": 0.5,   # new wallet, big money
    "D7": 0.3,   # dust spam
    "D8": 0.9,   # approval phishing
    "D9": 1.0,   # blacklist match
    "D10": 0.3,  # linked wallets
}


class ScamSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # D1 address poisoning                                       scam.poison.*
    scam_poison_real_min_eth: float = 0.001
    scam_poison_fake_max_eth: float = 0.0001
    scam_poison_prefix_len: int = 4
    scam_poison_suffix_len: int = 4
    scam_poison_real_min_token: float = 1.0          # token variant: real transfer of at least 1 token unit
    scam_poison_fake_max_token: float = 0.01          # token variant: fake transfer of at most 0.01 (or zero)
    scam_poison_fast_blocks: int = 30                 # severity up when the fake follows within this many blocks
    # D2 pass-through                                            scam.passthrough.*
    scam_passthrough_min_in_eth: float = 1.0
    scam_passthrough_min_forward_ratio: float = 0.8
    scam_passthrough_max_hold_blocks: int = 0         # 0 = no limit; Bitcoin uses a limit (see overrides)
    # D3 hop chains                                              scam.hops.*
    scam_hops_min_eth: float = 0.5
    scam_hops_min_ratio: float = 0.8
    scam_hops_max_ratio: float = 1.0
    scam_hops_max_depth: int = 4
    scam_hops_max_paths: int = 5000
    scam_hops_max_branch: int = 10                    # a wallet with more qualifying payouts is an endpoint (batch payer), not a hop
    # D4 / D5 fan-in / fan-out                                   scam.fanin.* / scam.fanout.*
    scam_fanin_min_senders: int = 20
    scam_fanin_max_contract_share: float = 0.5        # skip addresses mostly receiving contract calls
    scam_fanout_min_receivers: int = 20
    # D6 new wallet, big money                                   scam.newwallet.*
    scam_newwallet_min_eth: float = 10.0
    scam_newwallet_min_stable: float = 10_000.0       # USDT / USDC
    scam_newwallet_forward_ratio: float = 0.8
    scam_newwallet_window_blocks: int = 300
    # D7 dust spam                                               scam.dust.*
    scam_dust_max_eth: float = 0.0001
    scam_dust_min_count: int = 10
    # D8 approval phishing                                       scam.approval.*
    scam_approval_new_spender_blocks: int = 7200      # spender first seen within ~1 day before the approval
    # D10 linked wallets                                         scam.linked.*
    scam_linked_min_group: int = 3
    scam_linked_max_group: int = 50                   # bigger groups are usually exchanges or faucets
    scam_linked_window_blocks: int = 10
    # trace                                                      trace.*
    trace_default_depth: int = 2
    trace_max_depth: int = 3
    trace_max_nodes: int = 500
    trace_hub_degree_limit: int = 200
    trace_use_blockbook: bool = False
    # risk                                                       risk.weights.*
    risk_weights: dict[str, float] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    # token enrichment
    enrich_chunk_blocks: int = 10                     # blocks per eth_getLogs call
    # per-chain overrides. The value fields above are named *_eth but mean "in the chain's own coin";
    # non-ETH chains need their own amounts (and block windows, since block times differ).
    # Env: SCAM_CHAIN_OVERRIDES='{"btc": {"scam_passthrough_min_in_eth": 0.1}}'  (merged over these defaults)
    scam_chain_overrides: dict[str, dict[str, float]] = Field(default_factory=lambda: {
        "btc": {
            "scam_poison_real_min_eth": 0.0005, "scam_poison_fake_max_eth": 0.00002,     # 2,000 sats: just above dust
            "scam_poison_fast_blocks": 3,                                                  # ~30 minutes
            # Bitcoin spends whole coins and sends change to fresh addresses, so most wallets "forward" most of what
            # they receive. Only fast forwarding of larger amounts is a useful pass-through signal here.
            "scam_passthrough_min_in_eth": 1.0, "scam_passthrough_max_hold_blocks": 6,
            "scam_hops_min_eth": 0.5,
            "scam_newwallet_min_eth": 0.5, "scam_dust_max_eth": 0.00002,
            "scam_linked_window_blocks": 1, "scam_linked_min_group": 5,          # exchange payouts fund many addresses at once
        },
        "sol": {
            "scam_poison_real_min_eth": 0.01, "scam_poison_fake_max_eth": 0.0001,
            "scam_poison_fast_blocks": 1500,                                               # ~10 minutes of slots
            "scam_passthrough_min_in_eth": 20, "scam_hops_min_eth": 10,
            "scam_newwallet_min_eth": 200, "scam_dust_max_eth": 0.0001,
            "scam_linked_window_blocks": 50,
        },
    })

    def for_chain(self, chain: str) -> "ScamSettings":
        """A copy with this chain's overrides applied (unknown keys are ignored)."""
        upd = {k: v for k, v in (self.scam_chain_overrides.get(chain) or {}).items() if k in type(self).model_fields}
        return self.model_copy(update=upd) if upd else self


@lru_cache
def get_scam_settings() -> ScamSettings:
    return ScamSettings()
