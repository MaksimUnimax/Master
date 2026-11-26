# Agent v9

Agent form catalog: 28 accounting operations and 7 supplementary form/control groups, 161 field declarations. Typed, workshop-scoped drafts; partial inputs can be continued through the form assistant button. The existing preview/confirmation path is required for accounting writes. Credential, payment, admin security fields, historical corrections and binary uploads are not delegated to the model.

DeepSeek-only provider configuration, separate scoped gateway, usage journal and billing database. Admin usage aggregation includes UTC periods, users, uncached input, cache, output, confirmed costs and pending charges. Key entry is write-only. The provider account balance is not a separate balance when using the same API key.

Telegram delivery endpoints use the verified account binding, not a second bot poller. Explicit test, summary and disconnect. The requested transfer of live credentials and binding was blocked by the tool security system; do not bypass it. No credentials are in this repository. Telegram requires separately approved configuration and verified binding; the Octoport domain-specific widget is not reused on the temporary hostname.

Tests use local provider fixtures and synthetic accounts. 48 existing server checks and 2 new server checks passed. Four browser regression cases passed. Isolated gateway startup passed. Live provider requests and Telegram delivery have not been verified. Deployment must preserve existing stage database and Octoport service.
