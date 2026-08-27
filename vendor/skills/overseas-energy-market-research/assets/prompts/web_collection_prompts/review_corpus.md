# Exact-Model Review Corpus Crawl Prompt

You must use `kimi-webbridge` only. Do not summarize before saving raw review rows.

Task:

- Platform: `{{platform}}`
- Market: `{{market}}`
- Brand: `{{brand}}`
- Exact model: `{{exact_model}}`
- Identifier type: `{{identifier_type}}`
- Identifier value: `{{identifier_value}}`
- Product URL: `{{product_url}}`
- Review scope: crawl the full available review corpus. If the platform imposes a limit, document it.

Required procedure:

1. Confirm Kimi WebBridge daemon and browser extension are connected, then use one stable task-level session.
2. Confirm the review page belongs to the exact model and identifier.
3. Crawl all available review pages for that exact model, or document the platform-imposed limit.
4. Save raw reviews before extracting themes.
5. Do not mix variants, bundles, product families, or generations unless each review can be tied to the exact requested model.

Output JSON:

```json
{
  "raw_review_rows": [
    {
      "review_id": "",
      "platform": "{{platform}}",
      "product_url": "{{product_url}}",
      "review_url": "",
      "exact_model": "{{exact_model}}",
      "product_identifier": "{{identifier_value}}",
      "asin": "",
      "sku": "",
      "crawl_date": "",
      "rating": "",
      "original_text": "",
      "collection_tool": "kimi-webbridge",
      "review_limit_note": "",
      "verification_status": ""
    }
  ],
  "source_ledger_rows": [
    {
      "source_id": "",
      "stage": "4",
      "evidence_item": "Raw user review",
      "value_class": "observed",
      "source_type": "review platform",
      "collection_tool": "kimi-webbridge",
      "source_title": "",
      "publisher": "{{platform}}",
      "source_url": "",
      "local_file_path": "",
      "source_location": "",
      "publication_date": "",
      "access_date": "",
      "data_type": "raw review",
      "global_region": "",
      "country": "{{market}}",
      "province_state": "",
      "city_site": "",
      "reliability_tier": "user generated",
      "exact_model": "{{exact_model}}",
      "product_identifier": "{{identifier_value}}",
      "asin": "",
      "sku": "",
      "raw_value": "",
      "unit": "",
      "currency": "",
      "tax_basis": "",
      "evidence_row_ids": "",
      "notes": "",
      "verification_status": ""
    }
  ]
}
```

Only after these raw rows are saved may later scripts or agents perform coding and synthesis.
