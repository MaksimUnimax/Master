# Guest helper menu and payment form v24

The helper restore menu entry is hidden whenever the guest chat is visible. It appears only while the helper is collapsed, and restores the existing chat without a network request.

The public payment section has a quantity input and server-calculated total, visible without authentication. No unit price is displayed on this page. The five payment methods match Octoport: SBP, bank cards, YooMoney, SberPay, T-Pay. The live quote determines payment availability. Actual checkout remains authenticated and uses the existing account-bound payment contract; guest selection can carry forward to the existing checkout after login. No payments are enabled by this change.
