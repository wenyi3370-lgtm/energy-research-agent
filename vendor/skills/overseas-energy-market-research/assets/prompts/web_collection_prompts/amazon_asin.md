# Amazon ASIN Verification Prompt

You must use `kimi-webbridge` only. Do not invent any product data.
For Amazon.de, this ASIN search/verification task must finish before any price, promotion, review, ranking, availability, channel, service, or parameter collection task.

Task:

- Target marketplace: `{{marketplace}}`
- Brand: `{{brand}}`
- Exact model requested by user: `{{exact_model}}`
- Search query: `{{query}}`
- Maximum ASIN candidates: `{{max_candidates}}`

Required procedure:

1. Run the Kimi WebBridge health check and continue only when the daemon and browser extension are connected.
2. Use one task-level session, search Amazon for the exact brand plus exact model, and keep comparison pages in that same session.
3. Identify ASIN candidates before collecting any product facts, including selling price and promotion data.
4. Open every ASIN URL one by one.
5. Compare product title, brand, exact model, capacity/version, variant, bundle contents, images/spec hints, and seller/listing context.
6. Mark `exact_match` only when the product model fully matches the requested exact model.
7. Mark `conflict` or `待核实` when the listing mixes variants, bundles, generations, or the exact model cannot be isolated.

Output exactly two JSON arrays:

```json
{
  "model_identifier_rows": [
    {
      "model_id": "",
      "brand": "",
      "product_family": "",
      "exact_model": "",
      "asin": "",
      "sku": "",
      "model_code": "",
      "product_url": "",
      "page_title": "",
      "variant_bundle": "",
      "identifier_source_url": "",
      "checked_date": "",
      "match_status": "exact_match|conflict|excluded|待核实|unclear",
      "conflict_note": ""
    }
  ],
  "source_ledger_rows": [
    {
      "source_id": "",
      "stage": "2",
      "evidence_item": "Amazon ASIN verification",
      "value_class": "observed",
      "source_type": "marketplace",
      "collection_tool": "kimi-webbridge",
      "source_title": "",
      "publisher": "Amazon",
      "source_url": "",
      "local_file_path": "",
      "source_location": "",
      "publication_date": "",
      "access_date": "",
      "data_type": "model identifier",
      "global_region": "",
      "country": "{{market}}",
      "province_state": "",
      "city_site": "",
      "reliability_tier": "marketplace",
      "exact_model": "",
      "product_identifier": "",
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

Every row must include a URL. If no exact model match is found, output the candidate rows as `excluded`, `conflict`, or `待核实` with reasons.
