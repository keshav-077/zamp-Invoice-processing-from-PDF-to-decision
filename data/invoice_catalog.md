# Invoice Catalog

Review and correct fields before building PO.xlsx.

| File | Vendor | PO Ref | Invoice # | Total | Scenario |
|------|--------|--------|-----------|-------|----------|
| d2.jpg | Microbiological Associates | 34313 | 3567003 | 5000.0 | happy |
| d8.jpg | Oconnor, Fuller and Carter | — | 851918 | 68.53 | ambiguous |
| d9.jpg | Berger, Reed and Gutierrez | PO-9009 | 955133 | 41.18 | happy |
| d11.jpg | Harrington, Kline and Butler | PO-9011 | 447295 | 332.80 | happy |
| d14.jpg | Leach Inc. | PO-9014 | 738410 | 240.73 | arithmetic |
| d15.jpg | Snyder, Hammond and Anderson | — | 308044 | 69.16 | missing_field |
| d16.jpg | CHATPATA RESTAURANT INC | — | KQ23F4T9N8T6T | 19.10 | non_po |
| d1.jpg | Weis Markets | — | — | 421000.0 | missing_field |
| d3.jpg | Branham, INC. | — | E800896 | 1345.76 | standard |
| d4.jpg | Newsweek INCORPORATED | — | 3110 | 3888.75 | standard |
| d5.jpg | Landon Associates, Inc. | — | 143980 | 874.65 | standard |
| d6.jpg | Research Triangle Institute | 346A | 311T3668-4A | 60.78 | happy |
| d7.jpg | Liberty Mutual Insurance Company | — | — | 360000.0 | missing_field |
| d10.jpg | Young, Hernandez and Garcia | PO-9010 | 853827 | 85.08 | happy |
| d12.jpg | Gates, Myers and Stone | PO-9012 | 509715 | 161.99 | happy |
| d13.jpg | Clark PLC | PO-9013 | 664905 | 176.53 | split_po |
| d17.jpg | BAR RISTORANTE... | — | 52 | 34.0 | non_po |
| rogers_clean.png | Rogers, Smith and Hobbs | — | 229655 | 300.46 | happy |
| rogers_crumpled.png | Rogers, Smith and Hobbs | — | 239435 | 300.46 | happy |

## Demo roles (PS-1 submission)

| Role | File | Expected outcome |
|------|------|------------------|
| **Crumpled Rogers (upload this)** | rogers_crumpled.png | PO-ROGERS-01 vendor+amount match, $300.46 AUTO_APPROVED |
| Rogers clean reference | rogers_clean.png | Same PO/lines as crumpled, invoice #229655 |
| Auto-approve small | d9.jpg | PO-9009, $41.18 AUTO_APPROVED |
| Crumpled scan | d11.jpg | PO-9011 header match despite poor image quality |
| Arithmetic mismatch | d14.jpg | Stage1/3 flags, REVIEW or HOLD |
| Ambiguous PO | d8.jpg | No PO on invoice, two candidate POs for vendor |
| Split PO billing | d13.jpg | PO-9013 with prior invoicing on same PO |
