# Pro Tips

Catalog of Grafana Cloud onboarding pro tips, consumed by the `pro-tip-of-the-day` Grafana dashboard panel via the Infinity datasource.

## Format

`tips.json` is an array of objects:

```json
{
  "title": "Short, action-oriented headline",
  "body":  "1-3 sentence explanation. No markdown formatting.",
  "doc_url": "https://grafana.com/docs/..."
}
```

## Rotation

The consuming dashboard picks today's tip with `dayOfYear(now()) % count(tips)`. Add new tips to the end of the array; ordering only matters in that it determines which day each tip first appears.

## Raw URL

The dashboard fetches: `https://raw.githubusercontent.com/tupperd/grafana-reference/main/pro-tips/tips.json`
