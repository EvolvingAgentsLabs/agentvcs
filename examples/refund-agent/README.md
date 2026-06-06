# Example: refund agent

A minimal fluid agent you can version and crystallize.

```bash
cd examples/refund-agent
agentvcs init                 # note: agent.json already exists, init keeps it
agentvcs commit -m "first fluid run"
agentvcs show                 # see all four dimensions of the commit

# evolve it: tighten the goal and the code, then commit again
#   (edit agent.json's goal and app.py)
agentvcs commit -m "add amount threshold"
agentvcs diff                 # which dimension actually changed?

# you trust it now — freeze it
agentvcs freeze
cat crystal/*.json            # the deterministic recipe (temperature 0)
```
