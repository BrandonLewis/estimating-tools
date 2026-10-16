# estimating_tools

Deterministic construction-estimating tools: the open canonical models
(estimates, assemblies, rates, quotes, takeoffs, directories, cost codes),
the importers that free legacy data into them, the `est-*` command-line tools,
and the pure "plan" modules that turn those models into operations an agent
executes against BidSheet.ai through its MCP server. Nothing here opens a
network connection; BIM and CAD live in the separate `bimforge` package.

```bash
pip install 'estimating_tools[all]'
est-import --help
```

Source, documentation and the agent skills that drive these tools:
<https://github.com/BrandonLewis/estimating-tools>. Apache-2.0.
