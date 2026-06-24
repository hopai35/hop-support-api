# Ledger - Portfolio Synchronization

## Ledger Live Sync Issues

### "Out of Sync" Error
This is common after a period of not opening Ledger Live.

**Solutions:**
1. Go to Settings > Accounts and click "Synchronize" on each affected account.
2. If that fails: Settings > Help > Clear Cache. This re-downloads blockchain data.
3. For Bitcoin accounts: full sync may take 30-60 minutes depending on your connection.

### Balance Not Updating
1. Verify on a blockchain explorer (e.g., etherscan.io for Ethereum).
2. If the explorer shows a different balance, your nodes may be behind.
3. Switch to a different node in Settings > Node (try Ledger's built-in nodes).

### Transaction Pending for Hours
- Bitcoin: Check the transaction on mempool.space. If unconfirmed, consider a CPFP (child-pays-for-parent) acceleration.
- Ethereum: If stuck as "pending" in Ledger Live, it may be a nonce conflict. Reset your nonce via Settings > Reset.

## Blockchain Confirmation Times
- Bitcoin: 10-60 minutes (varies with network congestion and fee paid)
- Ethereum: 5-15 minutes
- Solana: 2-5 seconds
- Polygon: 2-5 minutes

## Supported Coins
Ledger Live supports 100+ cryptocurrencies including BTC, ETH, SOL, MATIC, ADA, DOT, and XRP.