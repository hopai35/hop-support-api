# Ledger - Passphrase & Advanced Security

## Understanding the 25th Word (BIP39 Passphrase)
Ledger devices support an optional "passphrase" that creates a completely new set of wallets.

**How it works:**
- Your standard 24-word phrase + passphrase = a new, independent wallet.
- Each different passphrase generates a different wallet.
- Without the passphrase, those wallets CANNOT be recovered.

**IMPORTANT WARNINGS:**
- The passphrase is NOT stored on the device.
- If you forget your passphrase, your funds are permanently lost.
- Always test with a small amount first.
- Store your passphrase separately from your 24-word recovery phrase.

## How to Set Up a Passphrase
1. On your Ledger, go to Settings > Security > Passphrase.
2. Choose "Set temporary" (lasts until device disconnects) or "Attach to PIN" (creates a second PIN for the passphrase wallet).
3. Enter your passphrase using the device buttons.

## Hidden Accounts
- Use the "Add Account" feature in Ledger Live while your passphrase is active.
- Accounts created under a passphrase will appear as "hidden" accounts.
- They only show up when the correct passphrase is entered.

## Multi-Signature Setup
- Multi-sig requires external software (Sparrow Wallet, Electrum).
- Ledger devices can be one of the signers in a 2-of-3 or 3-of-5 arrangement.
- Each signer must use a separate Ledger device.

## Security Best Practices
- NEVER share your 24-word recovery phrase with anyone.
- Ledger will NEVER ask for your recovery phrase.
- Only enter your passphrase directly on the device, never on a computer.
- Use the "Verify Address" feature to confirm receiving addresses on the device screen.