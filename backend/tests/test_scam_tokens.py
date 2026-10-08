"""Phase 1: ERC-20 log decoding (pure functions, no network)."""

from app.scam.tokens import APPROVAL, TRANSFER, UNLIMITED, decode_abi_string, parse_logs

A = "0x" + "11" * 20
B = "0x" + "22" * 20
TOKEN = "0xdac17f958d2ee523a2206206994597c13d831ec7"


def topic(addr):
    return "0x" + "0" * 24 + addr[2:]


def log(t0, a, b, amount, extra_topic=False, idx=0):
    topics = [t0, topic(a), topic(b)] + (["0x" + "0" * 63 + "1"] if extra_topic else [])
    return {"address": TOKEN.upper().replace("0X", "0x"), "topics": topics, "data": "0x" + format(amount, "064x"),
            "blockNumber": hex(100), "transactionHash": "0xABC", "logIndex": hex(idx)}


def test_transfer_and_approval_are_split():
    transfers, approvals = parse_logs([log(TRANSFER, A, B, 5_000_000), log(APPROVAL, A, B, UNLIMITED, idx=1)])
    assert len(transfers) == 1 and len(approvals) == 1
    t = transfers[0]
    assert (t["from_addr"], t["to_addr"], t["raw"], t["token_address"], t["tx_hash"]) == (A, B, 5_000_000, TOKEN, "0xabc")
    assert approvals[0]["owner"] == A and approvals[0]["spender"] == B and approvals[0]["raw"] >= UNLIMITED


def test_erc721_and_removed_logs_are_skipped():
    removed = log(TRANSFER, A, B, 1) | {"removed": True}
    transfers, approvals = parse_logs([log(TRANSFER, A, B, 1, extra_topic=True), removed])
    assert transfers == [] and approvals == []


def test_zero_amount_with_empty_data():
    transfers, _ = parse_logs([log(TRANSFER, A, B, 0) | {"data": "0x"}])
    assert transfers[0]["raw"] == 0


def test_symbol_decoding():
    abi = "0x" + format(32, "064x") + format(4, "064x") + "USDT".encode().hex().ljust(64, "0")
    assert decode_abi_string(abi) == "USDT"
    assert decode_abi_string("0x" + "MKR".encode().hex().ljust(64, "0")) == "MKR"     # bytes32 style
    assert decode_abi_string("0x") == ""
