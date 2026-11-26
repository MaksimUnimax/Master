# Provider readiness and recovery v16

Incident: authenticated free-form turn reached the native agent, but the configured local DeepSeek credential was absent. The gateway returned 503 before admitting any provider attempt. The native worker left a closed dispatch marker and returned turn_unconfirmed. No provider usage or charge was recorded.

Before starting a new paid turn through the local credential store, verify that the provider credential is configured. Local matrix turns, cached replies and guest mode remain independent of the key. Return provider_key with HTTP 503; browser shows actionable Russian text. Allow existing native publication to be recovered without requiring a new provider request.

A closed native dispatch marker may be reclaimed only for the same request hash and authorized operation if the ledger proves zero admitted attempts and all previous grants are inactive. Active/cancelled markers and any operation with a prior attempt remain protected. Never delete or settle uncertain provider attempts. Credentials are configured separately per service and not copied from Octoport.

Tests use a local fixture and synthetic credentials, not the production DeepSeek account. Live provider acceptance remains dependent on configuring the key.
