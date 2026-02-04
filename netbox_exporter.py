#!/usr/bin/env python3
"""
NetBox Full Exporter
Exports all NetBox data via API to JSON/CSV formats compatible with NetBox import.
"""

import json
import csv
import requests
import sys
import time
import os
from typing import Dict, List, Any, Optional
from urllib.parse import urljoin
from datetime import datetime


class NetBoxExporter:
    """Export all NetBox data via API."""
    
    # All NetBox models organized by app labels as of v4.x
    MODELS = {
        'circuits': [
            'providers',
            'circuit-types',
            'circuits',
            'circuit-terminations',
        ],
        'dcim': [
            'sites',
            'site-groups',
            'locations',
            'racks',
            'rack-roles',
            'manufacturers',
            'device-types',
            'module-types',
            'devices',
            'device-roles',
            'platforms',
            'rack-reservations',
            'cables',
            'virtual-chassis',
            'power-feeds',
            'power-panels',
        ],
        'ipam': [
            'rir',
            'aggregates',
            'roles',
            'prefixes',
            'ip-ranges',
            'ip-addresses',
            'fhrp-groups',
            'vlans',
            'vlan-groups',
            'services',
        ],
        'tenancy': [
            'tenants',
            'tenant-groups',
            'contacts',
            'contact-groups',
            'contact-roles',
            'contact-assignments',
        ],
        'virtualization': [
            'clusters',
            'cluster-types',
            'cluster-groups',
            'virtual-machines',
            'vm-interfaces',
        ],
        'wireless': [
            'wireless-lans',
            'wireless-lan-groups',
            'wireless-links',
        ],
        'vpn': [
            'ike-proposals',
            'ike-policies',
            'ipsec-proposals',
            'ipsec-policies',
            'ipsec-profiles',
            'l2vpns',
            'l2vpn-terminations',
            'tunnels',
            'tunnel-terminations',
        ],
        'extras': [
            'custom-fields',
            'custom-links',
            'export-templates',
            'saved-filters',
            'webhooks',
            'tags',
            'journal-entries',
            'config-contexts',
            'reports',
            'scripts',
        ],
        'users': [
            'users',
            'groups',
            'permissions',
        ],
    }

    def __init__(self, url: str, token: str, limit: int = 1000):
        self.base_url = url.rstrip('/') + '/'
        self.token = token
        self.limit = limit
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })
        
        # Create output directory
        self.timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.output_dir = f"netbox_export_{self.timestamp}"
        os.makedirs(self.output_dir, exist_ok=True)

    def _get(self, endpoint: str, params: Optional[Dict] = None) -> Dict:
        """Make GET request with rate limiting and pagination."""
        url = urljoin(self.base_url, f'api/{endpoint}/')
        all_results = []
        params = params or {}
        params['limit'] = self.limit
        params['offset'] = 0
        
        while True:
            try:
                response = self.session.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                
                if 'results' in data:
                    all_results.extend(data['results'])
                    if not data.get('next'):
                        break
                    params['offset'] += self.limit
                else:
                    return data
                    
                # Rate limiting
                time.sleep(0.1)
                
            except requests.exceptions.RequestException as e:
                print(f"  Error fetching {endpoint}: {e}")
                time.sleep(1)
                continue
                
        return {'results': all_results, 'count': len(all_results)}

    def _get_detail(self, url: str) -> Dict:
        """Fetch full object details from URL."""
        try:
            # Convert API URL to local path
            if url.startswith(self.base_url):
                url = url[len(self.base_url):]
            if not url.startswith('http'):
                url = urljoin(self.base_url, url)
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"  Error fetching detail {url}: {e}")
            return {}

    def _resolve_nested(self, obj: Any, depth: int = 0) -> Any:
        """Resolve nested objects to their identifiers."""
        if depth > 2 or obj is None:
            return obj
            
        if isinstance(obj, dict):
            # If it's a nested object with minimal data, try to get full details
            if 'id' in obj and 'url' in obj and len(obj) <= 5:
                full_obj = self._get_detail(obj['url'])
                if full_obj:
                    return self._clean_object(full_obj)
            return {k: self._resolve_nested(v, depth+1) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_nested(i, depth+1) for i in obj]
        return obj

    def _clean_object(self, obj: Dict) -> Dict:
        """Clean object for export, removing non-importable fields."""
        # Fields to remove (auto-generated or read-only)
        remove_fields = {
            'id', 'url', 'display', 'created', 'last_updated', 
            'custom_fields',  # Handle separately
        }
        
        cleaned = {}
        for key, value in obj.items():
            if key in remove_fields:
                continue
                
            # Resolve nested objects
            if isinstance(value, dict):
                if 'slug' in value:
                    cleaned[key] = value['slug']
                elif 'name' in value:
                    cleaned[key] = value['name']
                elif 'id' in value:
                    cleaned[key] = value['id']
                else:
                    cleaned[key] = self._resolve_nested(value)
            elif isinstance(value, list):
                # Handle tags specially
                if key == 'tags':
                    cleaned[key] = ','.join([t.get('slug', t.get('name', str(t))) for t in value])
                else:
                    cleaned[key] = [self._resolve_nested(v) for v in value]
            else:
                cleaned[key] = value
                
        return cleaned

    def _flatten_dict(self, d: Dict, parent_key: str = '', sep: str = '.') -> Dict:
        """Flatten nested dictionary for CSV export."""
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep).items())
            elif isinstance(v, list):
                items.append((new_key, json.dumps(v)))
            else:
                items.append((new_key, v))
        return dict(items)

    def export_model(self, app: str, model: str) -> Dict:
        """Export a single model."""
        endpoint = f"{app}/{model}"
        print(f"Exporting {endpoint}...")
        
        data = self._get(endpoint)
        results = data.get('results', [])
        
        if not results:
            print(f"  No data found for {endpoint}")
            return {}
            
        # Clean and resolve all objects
        cleaned_results = []
        for item in results:
            cleaned = self._clean_object(item)
            cleaned_results.append(cleaned)
            
        return {
            'endpoint': endpoint,
            'count': len(cleaned_results),
            'data': cleaned_results
        }

    def export_all(self):
        """Export all models."""
        full_export = {}
        total_objects = 0
        
        for app, models in self.MODELS.items():
            print(f"\n=== {app.upper()} ===")
            app_data = {}
            
            for model in models:
                result = self.export_model(app, model)
                if result:
                    app_data[model] = result
                    total_objects += result['count']
                    
                    # Save individual CSV
                    self._save_csv(result)
                    
            full_export[app] = app_data
            
        # Save full JSON export
        json_path = os.path.join(self.output_dir, 'full_export.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(full_export, f, indent=2, ensure_ascii=False, default=str)
            
        # Save import manifest
        manifest = {
            'exported_at': self.timestamp,
            'netbox_url': self.base_url,
            'total_objects': total_objects,
            'files': [f"{app}/{model}.csv" for app in self.MODELS for model in self.MODELS[app]],
        }
        manifest_path = os.path.join(self.output_dir, 'manifest.json')
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)
            
        print(f"\n✓ Export complete!")
        print(f"  Total objects: {total_objects}")
        print(f"  Output directory: {self.output_dir}")
        return full_export

    def _save_csv(self, result: Dict):
        """Save data as CSV in NetBox import format."""
        if not result or not result['data']:
            return
            
        endpoint = result['endpoint']
        data = result['data']
        
        # Create subdirectory for app
        app_name = endpoint.split('/')[0]
        app_dir = os.path.join(self.output_dir, app_name)
        os.makedirs(app_dir, exist_ok=True)
        
        # Determine filename
        model_name = endpoint.split('/')[-1]
        filename = f"{model_name}.csv"
        filepath = os.path.join(app_dir, filename)
        
        if not data:
            return
            
        # Flatten first object to get headers
        flat_data = [self._flatten_dict(obj) for obj in data]
        headers = set()
        for obj in flat_data:
            headers.update(obj.keys())
        headers = sorted(list(headers))
        
        # Write CSV
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for obj in flat_data:
                # Convert non-string values
                row = {k: str(v) if v is not None else '' for k, v in obj.items()}
                writer.writerow(row)
                
        print(f"  ✓ Saved {result['count']} records to {filepath}")


class NetBoxImporter:
    """Import data back into NetBox from exported files."""
    
    def __init__(self, url: str, token: str):
        self.base_url = url.rstrip('/') + '/'
        self.token = token
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Token {token}',
            'Accept': 'application/json',
            'Content-Type': 'application/json',
        })

    def import_from_csv(self, csv_path: str, endpoint: str):
        """Import data from CSV file."""
        print(f"Importing {csv_path} to {endpoint}...")
        
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            rows = list(reader)
            
        url = urljoin(self.base_url, f'api/{endpoint}/')
        success = 0
        errors = []
        
        for i, row in enumerate(rows):
            # Clean empty values and unflatten nested keys
            data = {}
            for key, value in row.items():
                if value == '':
                    continue
                    
                # Handle nested keys (e.g., "site.name")
                if '.' in key:
                    parts = key.split('.')
                    current = data
                    for part in parts[:-1]:
                        if part not in current:
                            current[part] = {}
                        current = current[part]
                    current[parts[-1]] = value
                else:
                    data[key] = value
                    
                # Parse JSON strings
                if value.startswith('[') or value.startswith('{'):
                    try:
                        data[key] = json.loads(value)
                    except:
                        pass
                        
            try:
                response = self.session.post(url, json=data, timeout=30)
                if response.status_code == 201:
                    success += 1
                    print(f"  ✓ [{i+1}/{len(rows)}] Created: {data.get('name', data.get('slug', 'Unknown'))}")
                else:
                    errors.append({
                        'row': i,
                        'data': data,
                        'error': response.text,
                        'status': response.status_code
                    })
                    print(f"  ✗ [{i+1}/{len(rows)}] Failed: {response.status_code}")
                    
                time.sleep(0.1)  # Rate limiting
                
            except Exception as e:
                errors.append({'row': i, 'error': str(e)})
                print(f"  ✗ [{i+1}/{len(rows)}] Error: {e}")
                
        print(f"\n  Summary: {success}/{len(rows)} successful")
        if errors:
            error_path = csv_path.replace('.csv', '_errors.json')
            with open(error_path, 'w') as f:
                json.dump(errors, f, indent=2)
            print(f  Errors saved to {error_path}")
            
        return success, errors

    def import_all(self, export_dir: str):
        """Import all CSV files from export directory."""
        manifest_path = os.path.join(export_dir, 'manifest.json')
        if os.path.exists(manifest_path):
            with open(manifest_path) as f:
                manifest = json.load(f)
            files = manifest.get('files', [])
        else:
            # Scan directory
            files = []
            for root, dirs, filenames in os.walk(export_dir):
                for f in filenames:
                    if f.endswith('.csv'):
                        rel_path = os.path.relpath(os.path.join(root, f), export_dir)
                        files.append(rel_path.replace(os.sep, '/'))
                        
        # Import order matters (dependencies first)
        import_order = [
            'tenancy', 'circuits', 'dcim', 'ipam', 
            'virtualization', 'wireless', 'vpn', 'extras'
        ]
        
        sorted_files = []
        for app in import_order:
            app_files = [f for f in files if f.startswith(app)]
            sorted_files.extend(sorted(app_files))
            
        for file_path in sorted_files:
            csv_path = os.path.join(export_dir, file_path)
            endpoint = file_path.replace('.csv', '')
            self.import_from_csv(csv_path, endpoint)


def main():
    """CLI interface."""
    import argparse
    
    parser = argparse.ArgumentParser(description='NetBox Exporter/Importer')
    parser.add_argument('--url', '-u', required=True, help='NetBox URL (e.g., http://netbox.example.com)')
    parser.add_argument('--token', '-t', required=True, help='NetBox API token')
    parser.add_argument('--import-dir', '-i', help='Import from directory')
    parser.add_argument('--limit', '-l', type=int, default=1000, help='API page limit')
    
    args = parser.parse_args()
    
    if args.import_dir:
        print(f"Importing to {args.url}")
        importer = NetBoxImporter(args.url, args.token)
        importer.import_all(args.import_dir)
    else:
        print(f"Exporting from {args.url}")
        exporter = NetBoxExporter(args.url, args.token, args.limit)
        exporter.export_all()


if __name__ == '__main__':
    main()
