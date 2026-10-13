import copy
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import verify_receipts as v


class ReceiptTests(unittest.TestCase):
    def setUp(self):
        self.payment = json.loads((ROOT / 'config/payout-destination.json').read_text())
        self.tx, self.block = '0x' + '1' * 64, '0x' + '2' * 64
        self.claim = {'id': 'simulated-payment', 'transaction_hash': self.tx, 'expected_amount_usdc': '5'}
        sender = '0x' + '3' * 40
        self.log = {'address': self.payment['token_contract'], 'topics': [v.TRANSFER_TOPIC,
            '0x' + '0' * 24 + sender[2:], '0x' + '0' * 24 + self.payment['receiving_address'][2:]],
            'data': '0x' + format(5000000, '064x'), 'transactionHash': self.tx, 'blockHash': self.block,
            'blockNumber': '0x64', 'logIndex': '0x0'}
        self.receipt = {'transactionHash': self.tx, 'blockHash': self.block, 'blockNumber': '0x64',
                        'status': '0x1', 'logs': [self.log]}
        self.chain, self.finalized = '0x2105', '0x65'
        self.canonical_hash = self.block

    def rpc(self, method, params):
        if method == 'eth_chainId': return self.chain
        if method == 'eth_getTransactionReceipt': return self.receipt
        if method == 'eth_getBlockByNumber':
            return {'number': self.finalized if params[0] == 'finalized' else '0x64', 'hash': self.canonical_hash}
        self.fail('Unexpected RPC method')

    def test_finalized_native_usdc_receipt_is_not_automatically_revenue(self):
        report = v.audit([self.claim], self.payment, self.rpc)
        self.assertEqual(report['confirmed_received_usdc'], '5.000000')
        self.assertEqual(report['results'][0]['status'], 'confirmed_receipt')
        self.assertEqual(report['attributed_revenue_usd'], 0)
        self.assertFalse(report['transaction_signing'])

    def test_duplicates_count_once(self):
        report = v.audit([self.claim, self.claim], self.payment, self.rpc)
        self.assertEqual(report['confirmed_received_usdc'], '5.000000')
        self.assertEqual(report['results'][1]['status'], 'duplicate_receipt')

    def test_wrong_chain_failed_pending_and_reorg_do_not_count(self):
        for attribute, value, status in [('chain', '0x1', 'wrong_chain'),
            ('receipt', None, 'pending_or_not_found'), ('finalized', '0x63', 'awaiting_finalization'),
            ('canonical_hash', '0x' + '4' * 64, 'noncanonical_receipt')]:
            original = getattr(self, attribute)
            with self.subTest(attribute=attribute):
                setattr(self, attribute, value)
                report = v.audit([self.claim], self.payment, self.rpc)
                self.assertEqual(report['confirmed_received_usdc'], '0.000000')
                self.assertEqual(report['results'][0]['status'], status)
            setattr(self, attribute, original)
        self.receipt['status'] = '0x0'
        self.assertEqual(v.audit([self.claim], self.payment, self.rpc)['results'][0]['status'], 'transaction_failed')

    def test_wrong_token_recipient_removed_log_and_amount(self):
        for modify in [lambda: self.log.update(address='0x' + '5' * 40),
                       lambda: self.log['topics'].__setitem__(2, '0x' + '0' * 24 + '6' * 40),
                       lambda: self.log.update(removed=True),
                       lambda: self.claim.update(expected_amount_usdc='6')]:
            original_log, original_claim = copy.deepcopy(self.log), copy.deepcopy(self.claim)
            modify()
            self.assertEqual(v.audit([self.claim], self.payment, self.rpc)['confirmed_received_usdc'], '0.000000')
            self.log.clear(); self.log.update(original_log)
            self.claim.clear(); self.claim.update(original_claim)

    def test_malformed_receipt_and_wrong_sender(self):
        self.log['blockHash'] = '0x' + '7' * 64
        self.assertEqual(v.audit([self.claim], self.payment, self.rpc)['results'][0]['status'], 'verification_error')
        self.log['blockHash'] = self.block
        self.claim['expected_sender'] = '0x' + '8' * 40
        self.assertEqual(v.audit([self.claim], self.payment, self.rpc)['confirmed_received_usdc'], '0.000000')

    def test_empty_claims_make_no_rpc_calls(self):
        report = v.audit([], self.payment, lambda *args: self.fail('No claims require no network reads'))
        self.assertEqual(report['confirmed_received_usdc'], '0.000000')

    def test_transaction_sending_method_is_rejected(self):
        with self.assertRaises(ValueError): v.rpc('eth_sendRawTransaction', ['0xdeadbeef'])

    def test_invalid_claim_and_amount_never_count(self):
        report = v.audit(['bad claim'], self.payment, lambda *args: self.fail('Invalid claim must not query RPC'))
        self.assertEqual(report['results'][0]['status'], 'verification_error')
        self.claim['expected_amount_usdc'] = 'not-a-number'
        report = v.audit([self.claim], self.payment, self.rpc)
        self.assertEqual(report['results'][0]['status'], 'verification_error')
        self.assertEqual(report['confirmed_received_usdc'], '0.000000')


if __name__ == '__main__': unittest.main()
