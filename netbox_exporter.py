#!/usr/bin/env python3
"""
NetBox Full Exporter
Exports all NetBox data via API to JSON/CSV formats compatible with NetBox import.
"""

import json
import csv
import requests
import time
import os
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin
from datetime import datetime


class NetBoxExporter:
    """Export all NetBox data via API."""

    # Import order matters for dependencies
    MODELS_ORDERED = [
        # Tenancy (no dependencies)
        ("tenancy", "tenant-groups"),
        ("tenancy", "tenants"),
        ("tenancy", "contact-groups"),
        ("tenancy", "contact-roles"),
        ("tenancy", "contacts"),
        ("tenancy", "contact-assignments"),
        # Circuits
        ("circuits", "providers"),
        ("circuits", "circuit-types"),
        ("circuits", "circuits"),
        ("circuits", "circuit-terminations"),
        # DCIM - Infrastructure
        ("dcim", "site-groups"),
        ("dcim", "sites"),
        ("dcim", "locations"),
        ("dcim", "rack-roles"),
        ("dcim", "racks"),
        ("dcim", "rack-reservations"),
        ("dcim", "manufacturers"),
        ("dcim", "device-types"),
        ("dcim", "module-types"),
        ("dcim", "device-roles"),
        ("dcim", "platforms"),
        ("dcim", "devices"),
        ("dcim", "virtual-chassis"),
        ("dcim", "cables"),
        ("dcim", "power-panels"),
        ("dcim", "power-feeds"),
        # IPAM
        ("ipam", "rirs"),
        ("ipam", "aggregates"),
        ("ipam", "roles"),
        ("ipam", "vlan-groups"),
        ("ipam", "vlans"),
        ("ipam", "prefixes"),
        ("ipam", "ip-ranges"),
        ("ipam", "ip-addresses"),
        ("ipam", "fhrp-groups"),
        ("ipam", "services"),
        # Virtualization
        ("virtualization", "cluster-types"),
        ("virtualization", "cluster-groups"),
        ("virtualization", "clusters"),
        ("virtualization", "virtual-machines"),
        ("virtualization", "interfaces"),
        # Wireless
        ("wireless", "wireless-lan-groups"),
        ("wireless", "wireless-lans"),
        ("wireless", "wireless-links"),
        # VPN
        ("vpn", "ike-proposals"),
        ("vpn", "ike-policies"),
        ("vpn", "ipsec-proposals"),
        ("vpn", "ipsec-policies"),
        ("vpn", "ipsec-profiles"),
        ("vpn", "tunnels"),
        ("vpn", "tunnel-terminations"),
        ("vpn", "l2vpns"),
        ("vpn", "l2vpn-terminations"),
        # Extras
        ("extras", "tags"),
        ("extras", "custom-fields"),
        ("extras", "custom-links"),
        ("extras", "export-templates"),
        ("extras", "saved-filters"),
        ("extras", "webhooks"),
        ("extras", "journal-entries"),
        ("extras", "config-contexts"),
    ]

    def __init__(self, url: str, token: str, limit: int = 1000):
        self.base_url = url.rstrip("/") + "/"
        self.token = token
        self.limit = limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.session.verify = False  # Disable SSL verification if needed

        # Create output directory
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.output_dir = f"netbox_export_{self.timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)

        # Cache for resolved objects to prevent duplicate lookups
        self._cache = {}

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> List[Dict]:
        """Make GET request with pagination."""
        url = urljoin(self.base_url, f"api/{endpoint}/")
        all_results = []
        params = params or {}
        params["limit"] = self.limit
        offset = 0

        while True:
            params["offset"] = offset
            try:
                response = self.session.get(url, params=params, timeout=60)
                response.raise_for_status()
                data = response.json()

                if "results" in data:
                    all_results.extend(data["results"])
                    if not data.get("next"):
                        break
                    offset += self.limit
                    print(
                        f"  Fetched {len(all_results)}/{data.get('count', '?')}...",
                        end="\r",
                    )
                else:
                    return [data]

                time.sleep(0.05)  # Gentle rate limiting

            except requests.exceptions.RequestException as e:
                print(f"\n  Error fetching {endpoint}: {e}")
                time.sleep(2)
                continue

        print(f"  Fetched {len(all_results)} total.          ")
        return all_results

    def _get_cached(self, url: str) -> Optional[Dict]:
        """Cached object fetch."""
        if url in self._cache:
            return self._cache[url]
        try:
            # Convert to full URL if relative
            if url.startswith("/"):
                url = urljoin(self.base_url, url.lstrip("/"))
            elif not url.startswith("http"):
                url = urljoin(self.base_url, f"api/{url}/")

            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            data = response.json()
            self._cache[url] = data
            time.sleep(0.05)
            return data
        except Exception:
            return None

    def _extract_ref(self, obj: Any) -> Any:
        """Safely extract reference from nested object without deep recursion."""
        if obj is None:
            return None

        if isinstance(obj, dict):
            # Priority order for references
            if "slug" in obj:
                return obj["slug"]
            if "name" in obj:
                return obj["name"]
            if "id" in obj:
                # For cables and other objects, just use ID to avoid recursion
                return obj["id"]
            return None

        return obj

    def _clean_object(self, obj: Dict, depth: int = 0) -> Dict:
        """Clean object for export, handling nested references safely."""
        if depth > 3 or not isinstance(obj, dict):
            return obj

        # Fields to remove (auto-generated or read-only)
        remove_fields = {
            "id",
            "url",
            "display",
            "display_url",
            "created",
            "last_updated",
            "custom_fields",  # Handle separately if needed
        }

        cleaned = {}

        for key, value in obj.items():
            if key in remove_fields:
                continue

            # Handle tags specially
            if key == "tags":
                if isinstance(value, list):
                    tag_names = []
                    for tag in value:
                        if isinstance(tag, dict):
                            tag_names.append(tag.get("slug", tag.get("name", "")))
                        else:
                            tag_names.append(str(tag))
                    cleaned[key] = ",".join(filter(None, tag_names))
                else:
                    cleaned[key] = value
                continue

            # Handle nested objects (single references)
            if isinstance(value, dict):
                ref = self._extract_ref(value)
                if ref is not None:
                    cleaned[key] = ref
                else:
                    # Shallow clean of nested dict, don't recurse into sub-objects
                    cleaned[key] = {
                        k: v
                        for k, v in value.items()
                        if k not in remove_fields and not isinstance(v, (dict, list))
                    }

            # Handle lists
            elif isinstance(value, list):
                # Simple lists of primitives
                if value and not isinstance(value[0], dict):
                    cleaned[key] = value
                else:
                    # List of objects - extract references
                    refs = []
                    for item in value:
                        if isinstance(item, dict):
                            ref = self._extract_ref(item)
                            if ref:
                                refs.append(ref)
                        else:
                            refs.append(item)
                    cleaned[key] = refs if len(refs) != 1 else refs[0]
            else:
                cleaned[key] = value

        return cleaned

    def export_model(self, app: str, model: str) -> Dict:
        """Export a single model."""
        endpoint = f"{app}/{model}"
        print(f"\nExporting {endpoint}...")

        results = self._get(endpoint)

        if not results:
            print(f"  No data found for {endpoint}")
            return {}

        # Clean objects
        cleaned_results = []
        for item in results:
            cleaned = self._clean_object(item)
            cleaned_results.append(cleaned)

        return {
            "endpoint": endpoint,
            "count": len(cleaned_results),
            "data": cleaned_results,
        }

    def export_all(self):
        """Export all models in dependency order."""
        full_export = {}
        total_objects = 0

        for app, model in self.MODELS_ORDERED:
            result = self.export_model(app, model)
            if result:
                if app not in full_export:
                    full_export[app] = {}
                full_export[app][model] = result
                total_objects += result["count"]
                self._save_csv(result)

        # Save full JSON export
        json_path = os.path.join(self.output_dir, "full_export.json")
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(full_export, f, indent=2, ensure_ascii=False, default=str)

        # Save import manifest
        manifest = {
            "exported_at": self.timestamp,
            "netbox_url": self.base_url,
            "total_objects": total_objects,
            "files": [f"{app}/{model}.csv" for app, model in self.MODELS_ORDERED],
        }
        manifest_path = os.path.join(self.output_dir, "manifest.json")
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)

        print(f"\n{'=' * 50}")
        print(f"✓ Export complete!")
        print(f"  Total objects: {total_objects}")
        print(f"  Output directory: {self.output_dir}")
        print(f"{'=' * 50}")
        return full_export

    def _flatten_dict(self, d: Dict, parent_key: str = "", sep: str = ".") -> Dict:
        """Flatten nested dictionary for CSV export."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k

            if isinstance(v, dict):
                # Only flatten one level deep for CSV
                for sub_k, sub_v in v.items():
                    items.append((f"{new_key}.{sub_k}", sub_v))
            elif isinstance(v, list):
                items.append((new_key, json.dumps(v)))
            else:
                items.append((new_key, v))
        return dict(items)

    def _save_csv(self, result: Dict):
        """Save data as CSV in NetBox import format."""
        if not result or not result["data"]:
            return

        endpoint = result["endpoint"]
        data = result["data"]

        # Create subdirectory for app
        app_name = endpoint.split("/")[0]
        model_name = endpoint.split("/")[-1]
        app_dir = os.path.join(self.output_dir, app_name)
        os.makedirs(app_dir, exist_ok=True)

        filename = f"{model_name}.csv"
        filepath = os.path.join(app_dir, filename)

        # Flatten data
        flat_data = [self._flatten_dict(obj) for obj in data]

        # Get all unique headers
        headers = set()
        for obj in flat_data:
            headers.update(obj.keys())
        headers = sorted(list(headers))

        # Write CSV
        with open(filepath, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for obj in flat_data:
                # Clean values for CSV
                row = {}
                for k, v in obj.items():
                    if v is None:
                        row[k] = ""
                    elif isinstance(v, (list, dict)):
                        row[k] = json.dumps(v)
                    else:
                        row[k] = str(v)
                writer.writerow(row)

        print(f"  ✓ Saved {result['count']} records to {app_name}/{filename}")


class NetBoxImporter:
    """Import data back into NetBox from exported files."""

    def __init__(self, url: str, token: str):
        self.base_url = url.rstrip("/") + "/"
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Token {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )
        self.session.verify = False

    def import_from_csv(self, csv_path: str, endpoint: str):
        """Import data from CSV file."""
        print(f"\nImporting {csv_path} to {endpoint}...")

        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        if not rows:
            print("  No rows to import")
            return 0, []

        url = urljoin(self.base_url, f"api/{endpoint}/")
        success = 0
        errors = []

        for i, row in enumerate(rows):
            # Clean empty values
            data = {}
            for key, value in row.items():
                if value == "" or value is None:
                    continue

                # Handle dot-notation keys (flattened nested objects)
                if "." in key:
                    parts = key.split(".")
                    current = data
                    for part in parts[:-1]:
                        if part not in current:
                            current[part] = {}
                        current = current[part]
                    current[parts[-1]] = value
                else:
                    # Try to parse JSON
                    if value.startswith("[") or value.startswith("{"):
                        try:
                            data[key] = json.loads(value)
                        except:
                            data[key] = value
                    else:
                        data[key] = value

            # Skip if only ID present (no real data)
            if len(data) <= 1 and "id" in data:
                continue

            try:
                response = self.session.post(url, json=data, timeout=30)
                if response.status_code in [201, 200]:
                    success += 1
                    identifier = data.get("name", data.get("slug", f"row {i + 1}"))
                    print(f"  ✓ [{i + 1}/{len(rows)}] Created: {identifier}")
                else:
                    err_msg = (
                        response.text[:200]
                        if len(response.text) > 200
                        else response.text
                    )
                    errors.append(
                        {
                            "row": i,
                            "data": data,
                            "error": err_msg,
                            "status": response.status_code,
                        }
                    )
                    print(f"  ✗ [{i + 1}/{len(rows)}] Failed: {response.status_code}")

                time.sleep(0.05)

            except Exception as e:
                errors.append({"row": i, "error": str(e)})
                print(f"  ✗ [{i + 1}/{len(rows)}] Error: {str(e)[:100]}")

        print(f"  Summary: {success}/{len(rows)} successful")
        if errors and len(errors) > 0:
            error_path = csv_path.replace(".csv", "_errors.json")
            with open(error_path, "w") as f:
                json.dump(errors, f, indent=2)
            print(f"  Errors saved to {error_path}")

        return success, errors

    def import_all(self, export_dir: str):
        """Import all CSV files from export directory."""
        manifest_path = os.path.join(export_dir, "manifest.json")

        files_to_import = []
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            files_to_import = manifest.get("files", [])
        else:
            # Discover files
            for root, dirs, files in os.walk(export_dir):
                for file in files:
                    if file.endswith(".csv"):
                        rel_path = os.path.relpath(os.path.join(root, file), export_dir)
                        files_to_import.append(rel_path.replace(os.sep, "/"))

        if not files_to_import:
            print("No CSV files found to import")
            return

        print(f"Found {len(files_to_import)} files to import")

        total_success = 0
        total_errors = 0

        for file_path in files_to_import:
            csv_path = os.path.join(export_dir, file_path)
            if not os.path.exists(csv_path):
                print(f"Warning: {csv_path} not found, skipping")
                continue

            endpoint = file_path.replace(".csv", "")
            success, errors = self.import_from_csv(csv_path, endpoint)
            total_success += success
            total_errors += len(errors)

        print(f"\n{'=' * 50}")
        print("Import complete!")
        print(f"  Total successful: {total_success}")
        print(f"  Total errors: {total_errors}")
        print(f"{'=' * 50}")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="NetBox Exporter/Importer")
    parser.add_argument("--url", "-u", required=True, help="NetBox URL")
    parser.add_argument("--token", "-t", required=True, help="NetBox API token")
    parser.add_argument("--import-dir", "-i", help="Import from directory")
    parser.add_argument("--limit", "-l", type=int, default=1000, help="API page limit")
    parser.add_argument(
        "--model", "-m", help="Export only specific model (e.g., dcim/devices)"
    )

    args = parser.parse_args()

    # Disable SSL warnings
    import urllib3

    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    if args.import_dir:
        print(f"Importing to {args.url}")
        importer = NetBoxImporter(args.url, args.token)
        importer.import_all(args.import_dir)
    else:
        print(f"Exporting from {args.url}")
        exporter = NetBoxExporter(args.url, args.token, args.limit)

        if args.model:
            parts = args.model.split("/")
            if len(parts) == 2:
                result = exporter.export_model(parts[0], parts[1])
                exporter._save_csv(result)
            else:
                print("Invalid model format. Use: app/model (e.g., dcim/devices)")
        else:
            exporter.export_all()


if __name__ == "__main__":
    main()
