"""Read-only native USDC-on-Base receipt checks. Never sends or signs transactions."""
import argparse
import datetime
from decimal import Decimal, InvalidOperation, localcontext
import json
import pathlib
import re
import urllib.request

from moltbook_coordinator import validate_payout

TRANSFER_TOPIC = '0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef'
RPC_URL = 'https://mainnet.base.org'
RPC_ENDPOINTS = {'base': RPC_URL, 'publicnode': 'https://base-rpc.publicnode.com'}
READ_METHODS = {'eth_chainId', 'eth_getTransactionReceipt', 'eth_getBlockByNumber'}


def rpc(method, params, provider='base'):
    if method not in READ_METHODS:
        raise ValueError('Only read-only receipt RPC methods are allowed')
    request = urllib.request.Request(RPC_ENDPOINTS[provider], method='POST', headers={'Content-Type': 'application/json'},
        data=json.dumps({'jsonrpc': '2.0', 'method': method, 'params': params, 'id': 1}).encode())
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
        payload = json.load(response)
    if payload.get('error') or 'result' not in payload:
        raise RuntimeError('Public RPC did not return a result')
    return payload['result']


def hex_value(value, label):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]+', value):
        raise ValueError('Invalid ' + label)
    return int(value, 16)


def hash_value(value):
    if not isinstance(value, str) or not re.fullmatch(r'0x[0-9a-fA-F]{64}', value):
        raise ValueError('Invalid transaction or block hash')
    return value.lower()


def check_claim(claim, payment, get):
    tx = hash_value(claim['transaction_hash'])
    result = {'transaction_hash': tx, 'claim_id': claim.get('id'), 'status': 'unverified',
              'revenue_attribution': 'unverified', 'transfers': []}
    if hex_value(get('eth_chainId', []), 'chain ID') != payment['chain_id']:
        result['status'] = 'wrong_chain'
        return result
    receipt = get('eth_getTransactionReceipt', [tx])
    if receipt is None:
        result['status'] = 'pending_or_not_found'
        return result
    if hash_value(receipt.get('transactionHash')) != tx:
        raise ValueError('Receipt transaction does not match requested hash')
    if hex_value(receipt.get('status'), 'receipt status') != 1:
        result['status'] = 'transaction_failed'
        return result
    block_number = hex_value(receipt.get('blockNumber'), 'block number')
    block_hash = hash_value(receipt.get('blockHash'))
    canonical = get('eth_getBlockByNumber', [receipt['blockNumber'], False])
    if not canonical or hash_value(canonical.get('hash')) != block_hash or hex_value(canonical.get('number'), 'canonical block') != block_number:
        result['status'] = 'noncanonical_receipt'
        return result
    finalized = get('eth_getBlockByNumber', ['finalized', False])
    if not finalized or hex_value(finalized.get('number'), 'finalized block') < block_number:
        result['status'] = 'awaiting_finalization'
        return result
    recipient = payment['receiving_address'].lower()
    contract = payment['token_contract'].lower()
    seen = set()
    for log in receipt.get('logs', []):
        if log.get('removed') is True or str(log.get('address', '')).lower() != contract:
            continue
        topics = log.get('topics', [])
        if len(topics) != 3 or str(topics[0]).lower() != TRANSFER_TOPIC:
            continue
        sender_topic, recipient_topic = hash_value(topics[1]), hash_value(topics[2])
        if sender_topic[2:26] != '0' * 24 or recipient_topic[2:26] != '0' * 24:
            raise ValueError('Malformed transfer address topics')
        if '0x' + recipient_topic[-40:] != recipient:
            continue
        sender = '0x' + sender_topic[-40:]
        if claim.get('expected_sender') and sender != str(claim['expected_sender']).lower():
            continue
        if hash_value(log.get('transactionHash')) != tx or hash_value(log.get('blockHash')) != block_hash:
            raise ValueError('Transfer log does not match its receipt')
        if hex_value(log.get('blockNumber'), 'log block') != block_number:
            raise ValueError('Transfer log block number mismatch')
        index = hex_value(log.get('logIndex'), 'log index')
        amount = hex_value(hash_value(log.get('data')), 'token amount')
        if index in seen or amount <= 0:
            continue
        seen.add(index)
        amount_text = str(amount // 1000000) + '.' + str(amount % 1000000).zfill(6)
        result['transfers'].append({'event_id': tx + ':' + str(index), 'sender': sender,
                                    'recipient': recipient, 'amount_usdc': amount_text})
    if not result['transfers']:
        result['status'] = 'no_matching_native_usdc_transfer'
        return result
    with localcontext() as context:
        context.prec = 100
        total = sum((Decimal(t['amount_usdc']) for t in result['transfers']), Decimal(0))
    expected = Decimal(str(claim['expected_amount_usdc'])) if claim.get('expected_amount_usdc') is not None else None
    if expected is not None and (not expected.is_finite() or expected <= 0 or total != expected):
        result['status'] = 'amount_mismatch'
        result['transfers'] = []
        return result
    result.update(status='confirmed_receipt', amount_usdc=format(total, '.6f'), block_number=block_number)
    return result


def audit(claims, payment, get=rpc):
    validate_payout(payment)
    results, counted, total = [], set(), Decimal(0)
    for claim in claims:
        if not isinstance(claim, dict):
            results.append({'status': 'verification_error', 'error_type': 'InvalidClaim'})
            continue
        try:
            result = check_claim(claim, payment, get)
        except (ValueError, KeyError, TypeError, OSError, RuntimeError, InvalidOperation) as error:
            result = {'claim_id': claim.get('id'), 'status': 'verification_error', 'error_type': type(error).__name__}
        if result['status'] == 'confirmed_receipt':
            fresh = [t for t in result['transfers'] if t['event_id'] not in counted]
            if not fresh:
                result['status'] = 'duplicate_receipt'
            for transfer in fresh:
                counted.add(transfer['event_id'])
                with localcontext() as context:
                    context.prec = 100
                    total += Decimal(transfer['amount_usdc'])
        results.append(result)
    return {'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'results': results,
            'confirmed_received_usdc': format(total, '.6f'), 'revenue_attribution': 'unverified',
            'attributed_revenue_usd': 0, 'attributed_net_profit_usd': 0,
            'transaction_signing': False, 'transfers_sent': 0,
            'notes': 'Confirmed receipts are not automatically attributed to project earnings or valued at USD.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--claims', default='payment-claims.json')
    parser.add_argument('--payout-config', default='config/payout-destination.json')
    parser.add_argument('--report', default='receipt-verification-report.json')
    parser.add_argument('--rpc-provider', choices=sorted(RPC_ENDPOINTS), default='base')
    args = parser.parse_args()
    claims = json.loads(pathlib.Path(args.claims).read_text())
    if claims.get('schema_version') != 1:
        raise SystemExit('Unsupported payment claim schema')
    report = audit(claims['claims'], json.loads(pathlib.Path(args.payout_config).read_text()),
                   lambda method, params: rpc(method, params, args.rpc_provider))
    report['rpc_provider'] = RPC_ENDPOINTS[args.rpc_provider]
    pathlib.Path(args.report).write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({'claims': len(claims['claims']), 'confirmed_received_usdc': report['confirmed_received_usdc'],
                      'attributed_revenue_usd': 0, 'transfers_sent': 0}))
    if any(r['status'] == 'verification_error' for r in report['results']):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
