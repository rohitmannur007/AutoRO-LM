# Data sources

Access date for the checks below: **2026-10-13**.

Demo fixtures in `backend/data/demo/` are hand-authored. They are not NHTSA records. The UI badges them DEMO.

## NHTSA complaints API

- Documentation: https://www.nhtsa.gov/nhtsa-datasets-and-apis
- Use policy: https://api.nhtsa.gov/ (public API, not for bulk VIN lookup; last updated on that page January 2023)
- Endpoint verified 2026-10-13: `GET https://api.nhtsa.gov/complaints/complaintsByVehicle?make=&model=&modelYear=`
- Observed root keys: `count`, `message`, `results`
- Observed complaint keys: `odiNumber`, `manufacturer`, `crash`, `fire`, `numberOfInjuries`, `numberOfDeaths`, `dateOfIncident`, `dateComplaintFiled`, `vin`, `components`, `summary`, `products`
- Product keys observed: `type`, `productYear`, `productMake`, `productModel`, `manufacturer`
- The loader requires `odiNumber` and `summary`. VINs are dropped and not stored.
- Flat file (not downloaded by the demo): https://static.nhtsa.gov/odi/ffdd/cmpl/FLAT_CMPL.zip (large; dictionary https://static.nhtsa.gov/odi/ffdd/cmpl/CMPL.txt)

## NHTSA recalls API

- Endpoint verified 2026-10-13: `GET https://api.nhtsa.gov/recalls/recallsByVehicle?make=&model=&modelYear=`
- Observed root keys: `Count`, `Message`, `results` (capital Count, unlike complaints)
- Observed recall keys include `NHTSACampaignNumber`, `Summary`, `Consequence`, `Remedy`, `Component`, `Make`, `Model`, `ModelYear`, `ReportReceivedDate`
- The loader requires `NHTSACampaignNumber` and `Summary` and refuses the payload if those names are absent.

## Manufacturer communications

The datasets page lists flat files, not a JSON API, for manufacturer communications. On 2026-10-13 these JSON guesses returned HTTP 403:

- `https://api.nhtsa.gov/communications/communicationsByVehicle`
- `https://api.nhtsa.gov/safetyIssues/byVehicle`

Supported path:

- Dictionary: https://static.nhtsa.gov/odi/ffdd/tsbs/TSBS.txt (fetched 2026-10-13; the file says it was renamed conceptually to MfrComms.txt on 2024-05-13)
- Concise CSV zip example: `https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_1995-1999.zip`
- Default opt-in URL in the app: `https://static.nhtsa.gov/odi/ffdd/tsbs/MFR_COMMS_RECEIVED_2025-2026.zip`
- CSV header observed in the 1995–1999 file: `TSB/Document ID`, `Make`, `Model`, `Model Year`, `Concise Summary`
- Model year `9999` is treated as unknown. The parser rejects a file whose header does not contain the document id and a summary column.
- Downloads are limited to HTTPS hosts `api.nhtsa.gov` and `static.nhtsa.gov`, with a byte cap (`AUTORO_DOWNLOAD_MAX_BYTES`, default 30 MB).

## Licensing

NHTSA datasets are US federal public data. This repository’s MIT license covers the project code, not redistributed agency files. The demo pack does not include a dump of complaints, recalls, or communications.

## Schema drift

Parsers read fields case-insensitively and fail if required names are missing. Do not add silent aliases for a new layout. Update this file with the access date and the new observed keys after checking the official documentation.
