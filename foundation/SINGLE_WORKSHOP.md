# Single-workshop mode (v20)

The original multi-workshop storage, demo generator, data separation and archive/restore implementation are retained.

Default: `PODMASTERYE_MULTI_WORKSHOP=0` (also disabled if the variable is unset).
No database migration or deletion is required. The account's original/default workshop remains accessible.

When disabled: the UI does not render selection/creation/demo/archive controls, secondary workshop selection and mutation are refused, and the agent does not advertise or prepare the creation form. The original workshop's settings, accounting, integrations, wallet and history remain available.

To restore the feature, an operator sets `PODMASTERYE_MULTI_WORKSHOP=1` in the Podmasterye service environment and restarts that service. The native worker forwards this flag to the product MCP process. Do not change Octoport's environment. Existing secondary workshop rows are retained.

The single-workshop and enabled-feature regression scenarios use isolated test accounts.
