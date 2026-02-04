# Netbox API Export / Import

**WARNING:** 99.9% vibe coded... Import not tested yet

## Usage

### Installation

No external dependencies required (uses only standard library `requests`). Install requests if not available:

```bash
pip install requests
```

### Export Data

```bash
python netbox_exporter.py --url https://netbox.example.com --token YOUR_API_TOKEN
```

This creates a timestamped directory with:

- `full_export.json` - Complete data in JSON format
- Individual CSV files organized by app (`dcim/devices.csv`, `ipam/prefixes.csv`, etc.)
- `manifest.json` - Import manifest with file list

### Import Data

```bash
python netbox_exporter.py --url https://new-netbox.example.com --token NEW_TOKEN --import-dir netbox_export_20240115_120000
```

## Features

1. **Complete Coverage**: Exports all major NetBox models including Tenancy, Circuits, DCIM, IPAM, Virtualization, Wireless, VPN, and Extras
2. **Dependency-Ordered Export**: Models are exported in correct dependency order (tenants → sites → racks → devices, etc.) to ensure import compatibility
3. **Safe Reference Handling**: Extracts slugs/names/IDs from nested objects without following URLs, preventing infinite recursion on circular references (e.g., cables ↔ devices)
4. **Rate Limiting**: Built-in delays to avoid API throttling with automatic retry on errors
5. **Pagination**: Handles large datasets efficiently with configurable page limits
6. **Error Resilience**: Continues on errors, logs failures for review, and retries failed requests
7. **CSV Format**: Generates NetBox-compatible CSV files organized by app for bulk import
8. **Shallow Flattening**: Converts nested structures to dot-notation for CSV compatibility without deep recursion
9. **SSL Flexibility**: Option to disable SSL verification for self-signed certificates
10. **Incremental Export**: Option to export single models via `--model` flag
11. **Import Manifest**: Generates manifest.json tracking exported files and metadata 

## Notes

- **Dependencies**: The import order respects NetBox's foreign key constraints (tenants → sites → racks → devices)
- **Circular References**: Objects with mutual references (e.g., cables connected to devices) are exported using identifiers only (slug/name/id) rather than full nested objects to prevent infinite recursion
- **Custom Fields**: Exported as flat values; may need manual mapping if field IDs differ between instances
- **Images/Attachments**: Not exported (requires direct file system access)
- **Secrets**: Not included in standard API exports for security reasons
- **Users/Permissions**: Exported but passwords cannot be migrated via API (use admin setup)
- **API Limitations**: Some endpoints differ from model names (e.g., `virtualization/interfaces` not `vm-interfaces`)
- **SSL**: Set `session.verify = False` or use `--insecure` equivalent for self-signed certs
- **Rate Limits**: Adjust `time.sleep()` values if hitting API throttling
