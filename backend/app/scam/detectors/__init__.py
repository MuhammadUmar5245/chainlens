"""Detector registry, in run order (D10 uses D1's findings)."""

from app.scam.detectors import (d01_poisoning, d02_passthrough, d03_hops, d04_collector, d05_distributor, d06_new_wallet,
                                d07_dust, d08_approvals, d09_blacklist, d10_linked)

DETECTORS = {
    "D1": ("Address poisoning", d01_poisoning.detect),
    "D2": ("Pass-through / mule", d02_passthrough.detect),
    "D3": ("Hop chain / peeling", d03_hops.detect),
    "D4": ("Collector (fan-in)", d04_collector.detect),
    "D5": ("Distributor (fan-out)", d05_distributor.detect),
    "D6": ("New wallet, big money", d06_new_wallet.detect),
    "D7": ("Dust spam", d07_dust.detect),
    "D8": ("Approval phishing", d08_approvals.detect),
    "D9": ("Blacklist match", d09_blacklist.detect),
    "D10": ("Linked wallets", d10_linked.detect),
}
