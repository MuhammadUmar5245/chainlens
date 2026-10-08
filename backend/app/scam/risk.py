"""Wallet risk: combines findings into one explainable 0-100 score per wallet.

Per detector only the strongest finding counts (no double counting). Detector strengths combine like independent
signals:  risk = 100 * (1 - prod(1 - weight_d * score_d / 100)).  The three strongest findings become the reasons."""

from collections import defaultdict

from app.scam.detectors.base import Finding, severity_for


def wallet_risk(findings: list[Finding], weights: dict[str, float]) -> list[dict]:
    best: dict[str, dict[str, Finding]] = defaultdict(dict)
    for f in findings:
        cur = best[f.wallet].get(f.detector)
        if cur is None or f.score > cur.score:
            best[f.wallet][f.detector] = f
    out = []
    for wallet in sorted(best):
        per = best[wallet]
        remaining = 1.0
        for d, f in per.items():
            remaining *= 1 - min(1.0, weights.get(d, 0.5) * f.score / 100)
        score = int(round(100 * (1 - remaining)))
        ranked = sorted(per.values(), key=lambda f: (-weights.get(f.detector, 0.5) * f.score, f.detector))
        out.append({"wallet": wallet, "risk_score": score, "severity": severity_for(score),
                    "detectors_hit": sorted(per, key=lambda d: int(d[1:])), "top_reasons": [f.reason for f in ranked[:3]]})
    return sorted(out, key=lambda r: (-r["risk_score"], r["wallet"]))
