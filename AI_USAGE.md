# AI Tool Usage

Tools used: Claude (Anthropic), via the Claude web interface.

The table below summarises AI assistance used during initial project setup, requirements analysis, and design documentation. Prompts and responses are summarised rather than reproduced verbatim.

| Tool | Prompt Given | Response Received | How the output was used |
|---|---|---|---|
| Claude | Review the proposed data model and API contract for order intake, retrieval, stock lookup, and daily reporting. | Identified design considerations around order identity, stored order-line prices, response behaviour, and report definitions. | Used to refine the proposed entities, endpoint list, and documented assumptions. |
| Claude | Review the proposed background stock-processing approach, including temporary worker interruption and recovery. | Highlighted the need for durable pending work, safe concurrent stock updates, transactional processing, and protection against repeated stock deductions. | Used to document the database-backed work queue, transaction requirements, and recovery test scenarios. |
| Claude | Critically review the solution design and challenge unresolved business rules and scope decisions. | Identified ambiguities around insufficient stock, duplicate submissions, order status, revenue reporting, and out-of-scope functionality. | Used to clarify the intended rejection policy, idempotency behaviour, report semantics, and remaining implementation decisions. |