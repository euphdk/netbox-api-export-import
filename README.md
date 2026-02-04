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

1. **Complete Coverage**: Exports all major NetBox models including DCIM, IPAM, Circuits, Tenancy, Virtualization, Wireless, VPN, and Extras
2. **Dependency Resolution**: Resolves nested objects to slugs/names for import compatibility
3. **Rate Limiting**: Built-in delays to avoid API throttling
4. **Pagination**: Handles large datasets efficiently
5. **Error Handling**: Continues on errors, logs failures for review
6. **CSV Format**: Generates NetBox-compatible CSV files for bulk import
7. **Flattening**: Converts nested structures to dot-notation for CSV compatibility
    

## Notes

- **Dependencies**: The import order respects NetBox's foreign key constraints (tenants → sites → racks → devices)
- **Custom Fields**: Exported but may need manual mapping if field IDs differ between instances
- **Images/Attachments**: Not exported (requires direct file system access)
- **Secrets**: Not included in standard API exports for security
- **Users/Permissions**: Exported but passwords cannot be migrated via API
