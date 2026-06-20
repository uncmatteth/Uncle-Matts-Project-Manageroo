# Repair duplicate checkout processing

## What I want

Repair the checkout flow so retrying or receiving a duplicate payment event cannot create a second order or charge.

## Required outcomes

- The existing successful checkout path remains unchanged for users.
- Replaying the same event produces exactly one order.
- Two concurrent deliveries produce exactly one successful state transition.
- The system records enough evidence to diagnose future failures.
- Existing payment-provider and authentication integrations are reused.

## Must not happen

- Do not replace the payment provider.
- Do not hide the issue by swallowing errors.
- Do not delete or weaken existing billing tests.
- Do not change public response formats unless required for correctness.

## Existing product

The checkout currently works in normal cases but duplicate delivery sometimes creates duplicate state.
