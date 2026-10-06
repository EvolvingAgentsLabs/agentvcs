# Blame (v0.1)

`blame <bundle> --metric m` segments a run's steps by the manifest that produced
them and attributes the change of `m` between consecutive segments to the
patches applied in between.

```json
{
  "ok": true, "metric": "f1.indemnification",
  "segments": [
    {"manifest_id": "b3:A", "from_step": 0,  "to_step": 17, "n": 18, "mean": 0.41, "introduced_by": []},
    {"manifest_id": "b3:B", "from_step": 18, "to_step": 40, "n": 23, "mean": 0.66, "introduced_by": ["b3:P1"]}
  ],
  "attributions": [
    {"patches": ["b3:P1"], "from_segment": 0, "to_segment": 1, "delta": 0.25}
  ]
}
```

- `blame` refuses a ledger that does not `verify` (`E_INVALID_LEDGER`, exit 3):
  attribution over a broken chain is attribution over unknown history.
- A **segment** is a maximal run of consecutive steps (in ledger order) with the
  same `manifest_id` and no patch between them. (A patch and its rollback with no
  step in between yield two segments on the same manifest.) `from_step`/`to_step` are inclusive step indexes.
- `n` counts the segment's steps that carry `m`; `mean` is their arithmetic mean,
  or `null` when `n == 0`.
- `introduced_by` lists, in ledger order, the patches between the previous
  segment's last step and this segment's first step (empty for the first
  segment). Several patches with no step between them are attributed jointly —
  blame cannot separate them; `bisect` can.
- `attributions` has one entry per segment after the first; `delta` is
  `mean[i] − mean[i−1]`, or `null` if either is `null`.
- Patches after the last step introduce no segment and are not attributed.
- Numbers are compared by conformance with absolute tolerance `1e-9`.

**What blame does not claim.** Segmentation confounds the patch with everything
else that changed over time — later documents can be harder than earlier ones.
Blame says *which patch sits at the boundary*, not that it caused the delta.
Causal attribution is `bisect`'s job: re-execute the same steps from a checkpoint
under both manifests.
