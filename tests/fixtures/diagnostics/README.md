These are synthetic diagnostics v1 consumer fixtures for Vita Tree. No live CV,
provider response, credential or real provider request ID is represented.

The success fixture means generation was observed and content capture was off.
The failure fixture means HTTP 503 overload with no model output returned.
Fixture IDs are placeholders, not paths to real trace directories. Production
files use generated IDs and the directory layout documented in DIAGNOSTICS.md.

The checked-in schemas mirror `vita.helpers.diagnostics_contract.SCHEMAS`.
Existing `.outcome.json` files retain their separate versioned provider-error
contract. Use diagnostics correlation IDs and `outcome_run_id` to join them.
