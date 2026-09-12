# Pre-registered train-only custody declarations

`CustodyStore.split()` accepts an optional exact `train_only_item_ids` list and
a SHA-256 `train_only_reason_commitment`. It is for a controller that chooses
to reserve an official development item for training before any validation
allocation. It does not modify `InventoryItem.exposure`, assert non-exposure,
or create an independent-clean attestation.

The store resolves every declared item through its existing source-group and
content-hash transitive closure. The full closure is assigned `train`, so no
partial member list can leave a connected item eligible for validation later.
The frozen split payload
records the original declared item list, resolved group IDs, and reason
commitment. A declaration with an unknown item, duplicate item, or missing
reason is refused.

Without a declaration, `split()` emits its historical payload exactly and
keeps the historical digest. Once a split exists, a changed, added, or removed
declaration produces a different digest and is rejected as reallocation.

This is a voluntary loss of validation eligibility only. All other unknown
items remain quarantine unless the existing independent-attestation path
qualifies their complete group. No real extended inventory is split by this
change; a controller must create and review its declaration separately.
