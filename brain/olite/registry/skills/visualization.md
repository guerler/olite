## Visualizing datasets

When the user asks to visualize, chart, plot, or graph a tabular dataset (for
example a histogram, scatter plot, bar chart, distribution, correlation, comparison,
or trend), call the `run_process` tool with name `visualize_dataset` and inputs
`{dataset_id, request}`, where `request` is the user's phrasing. The process profiles
the data, chooses an appropriate chart, fills its fields, and returns the chart as a
rendered artifact. Prefer this over building a chart by hand with `run_python`.
